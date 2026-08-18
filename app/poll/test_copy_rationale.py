from datetime import timedelta
from types import SimpleNamespace

from django.test import RequestFactory, TransactionTestCase
from django.utils import timezone

from poll import views
from poll.models import Ballot, Poll, Team, User, UserRole


class CopyPreviousRationaleTests(TransactionTestCase):
    def setUp(self):
        now = timezone.now()
        self.poll = Poll.objects.create(
            year=2026,
            week="Preseason",
            open_date=now - timedelta(days=1),
            close_date=now + timedelta(days=1),
            publish_date=now - timedelta(days=7),
            ap_date=now - timedelta(days=7),
        )
        self.user = User.objects.create(username="rationale-user")
        Team.objects.create(
            handle="ecu",
            name="ECU Pirates",
            conference="American",
            division="FBS",
            use_for_ballot=True,
            short_name="ECU",
        )
        self.ballot = Ballot.objects.create(
            user=self.user,
            poll=self.poll,
            user_type=UserRole.Role.VOTER,
        )
        self.request_factory = RequestFactory()

    def render_ballot(self):
        request = self.request_factory.get(f"/ballot/edit/{self.ballot.id}/")
        request.user = SimpleNamespace(username=self.user.username)
        return views.edit_ballot(request, self.ballot.id)

    def test_hides_copy_button_without_a_previous_submission(self):
        response = self.render_ballot()

        self.assertNotContains(response, "copy-rationale-button")

    def test_shows_copy_button_with_rationale_from_previous_submission(self):
        Ballot.objects.create(
            user=self.user,
            poll=self.poll,
            submission_date=timezone.now() - timedelta(days=1),
            user_type=UserRole.Role.VOTER,
            overall_rationale="Ranked teams by strength of schedule.",
        )

        response = self.render_ballot()

        self.assertContains(response, "copy-rationale-button")
        self.assertContains(response, 'data-rationale="Ranked teams by strength of schedule."')

    def test_hides_copy_button_when_latest_submission_has_no_rationale(self):
        Ballot.objects.create(
            user=self.user,
            poll=self.poll,
            submission_date=timezone.now() - timedelta(days=2),
            user_type=UserRole.Role.VOTER,
            overall_rationale="Older rationale",
        )
        Ballot.objects.create(
            user=self.user,
            poll=self.poll,
            submission_date=timezone.now() - timedelta(days=1),
            user_type=UserRole.Role.VOTER,
        )

        response = self.render_ballot()

        self.assertNotContains(response, "copy-rationale-button")
