import csv
from datetime import timedelta
import json
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import SimpleTestCase, TransactionTestCase
from django.test.utils import override_settings
from django.utils import timezone

from poll.admin import accept_applications, reject_applications
from poll.models import Ballot, BallotEntry, Poll, ProvisionalUserApplication, Team, User, UserRole
from poll.notifications import send_provisional_application_decision_message


class ProvisionalApplicationTests(TransactionTestCase):
    def setUp(self):
        self.auth_user = get_user_model().objects.create_user(
            username='former_provisional',
            password='test-password',
        )
        self.poll_user = User.objects.create(username=self.auth_user.username)
        self.client.force_login(self.auth_user)

    def test_revoked_provisional_voter_can_reapply(self):
        ProvisionalUserApplication.objects.create(
            user=self.poll_user,
            submission_date=timezone.now() - timedelta(days=1),
            status=ProvisionalUserApplication.Status.ACCEPTED,
        )
        UserRole.objects.create(
            user=self.poll_user,
            role=UserRole.Role.PROVISIONAL,
            start_date=timezone.now() - timedelta(days=30),
            end_date=timezone.now() - timedelta(days=1),
        )

        response = self.client.get('/my_ballots/')

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['app'])
        self.assertContains(response, 'Apply')

        response = self.client.get('/apply_for_provisional/')

        self.assertRedirects(response, '/my_ballots/')
        latest_application = ProvisionalUserApplication.objects.latest('submission_date')
        self.assertEqual(latest_application.user, self.poll_user)
        self.assertEqual(latest_application.status, ProvisionalUserApplication.Status.OPEN)
        self.assertEqual(ProvisionalUserApplication.objects.count(), 2)


class ProvisionalApplicationNotificationTests(TransactionTestCase):
    def setUp(self):
        self.poll_user = User.objects.create(username='notification_test_user')
        self.application = ProvisionalUserApplication.objects.create(
            user=self.poll_user,
            submission_date=timezone.now(),
            status=ProvisionalUserApplication.Status.OPEN,
        )

    @patch('poll.notifications.reddit_client_for_role')
    def test_acceptance_message_is_sent_from_configured_account(self, reddit_client):
        self.application.status = ProvisionalUserApplication.Status.ACCEPTED
        self.application.save(update_fields=['status'])

        self.assertTrue(send_provisional_application_decision_message(self.application))

        reddit_client.assert_called_once_with('NOTIFICATIONS')
        reddit_client.return_value.redditor.assert_called_once_with('notification_test_user')
        subject, body = reddit_client.return_value.redditor.return_value.message.call_args.args
        self.assertEqual(subject, 'Your r/CFB Poll provisional voter application was approved')
        self.assertIn('submit provisional ballots', body)
        self.assertIn('provisional results', body)

    @patch('poll.notifications.reddit_client_for_role')
    def test_rejection_message_is_sent_from_configured_account(self, reddit_client):
        self.application.status = ProvisionalUserApplication.Status.REJECTED
        self.application.save(update_fields=['status'])

        self.assertTrue(send_provisional_application_decision_message(self.application))

        reddit_client.return_value.redditor.assert_called_once_with('notification_test_user')
        subject, body = reddit_client.return_value.redditor.return_value.message.call_args.args
        self.assertEqual(subject, 'Your r/CFB Poll provisional voter application was not approved')
        self.assertIn('Thank you for your interest', body)
        self.assertIn('u/sirgippy', body)
        self.assertIn('r/CFB moderators', body)

    @patch('poll.notifications.reddit_client_for_role', side_effect=RuntimeError('not configured'))
    def test_message_is_skipped_when_bot_credentials_are_not_configured(self, reddit_client):
        self.application.status = ProvisionalUserApplication.Status.REJECTED
        self.application.save(update_fields=['status'])

        self.assertFalse(send_provisional_application_decision_message(self.application))
        reddit_client.assert_called_once_with('NOTIFICATIONS')

    @patch('poll.admin.send_provisional_application_decision_message', return_value=True)
    def test_admin_acceptance_decides_open_applications_once_and_notifies(self, send_message):
        already_accepted = ProvisionalUserApplication.objects.create(
            user=User.objects.create(username='already_accepted'),
            submission_date=timezone.now(),
            status=ProvisionalUserApplication.Status.ACCEPTED,
        )
        accept_applications(None, None, ProvisionalUserApplication.objects.all())

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, ProvisionalUserApplication.Status.ACCEPTED)
        self.assertEqual(UserRole.objects.filter(user=self.poll_user, role=UserRole.Role.PROVISIONAL).count(), 1)
        send_message.assert_called_once_with(self.application)
        already_accepted.refresh_from_db()
        self.assertEqual(already_accepted.status, ProvisionalUserApplication.Status.ACCEPTED)

    @patch('poll.admin.send_provisional_application_decision_message', return_value=True)
    def test_admin_rejection_notifies_open_applications(self, send_message):
        reject_applications(None, None, ProvisionalUserApplication.objects.filter(pk=self.application.pk))

        self.application.refresh_from_db()
        self.assertEqual(self.application.status, ProvisionalUserApplication.Status.REJECTED)
        send_message.assert_called_once_with(self.application)


class ProvisionalAdminRealNotificationTests(TransactionTestCase):
    def setUp(self):
        self.poll_user = User.objects.create(username='real_admin_notification_user')
        self.application = ProvisionalUserApplication.objects.create(
            user=self.poll_user, submission_date=timezone.now(),
            status=ProvisionalUserApplication.Status.OPEN,
        )
        self.model_admin = Mock()
        self.request = Mock()

    @patch('poll.notifications.reddit_client_for_role')
    def test_admin_accept_uses_updated_application_for_real_message(self, reddit_client):
        accept_applications(self.model_admin, self.request,
                            ProvisionalUserApplication.objects.filter(pk=self.application.pk))
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, ProvisionalUserApplication.Status.ACCEPTED)
        subject, body = reddit_client.return_value.redditor.return_value.message.call_args.args
        self.assertEqual(subject, 'Your r/CFB Poll provisional voter application was approved')
        self.assertIn('submit provisional ballots', body)
        self.model_admin.message_user.assert_not_called()

    @patch('poll.notifications.reddit_client_for_role')
    def test_admin_reject_uses_updated_application_for_real_message(self, reddit_client):
        reject_applications(self.model_admin, self.request,
                            ProvisionalUserApplication.objects.filter(pk=self.application.pk))
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, ProvisionalUserApplication.Status.REJECTED)
        subject, body = reddit_client.return_value.redditor.return_value.message.call_args.args
        self.assertEqual(subject, 'Your r/CFB Poll provisional voter application was not approved')
        self.assertIn('Thank you for your interest', body)
        self.model_admin.message_user.assert_not_called()

    @patch('poll.notifications.reddit_client_for_role', side_effect=RuntimeError('transport down'))
    def test_admin_notification_failure_keeps_decision_and_warns(self, reddit_client):
        accept_applications(self.model_admin, self.request,
                            ProvisionalUserApplication.objects.filter(pk=self.application.pk))
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, ProvisionalUserApplication.Status.ACCEPTED)
        self.model_admin.message_user.assert_called_once()
        self.assertEqual(self.model_admin.message_user.call_args.kwargs['level'], 'warning')


class TeamLogoUrlTagTests(SimpleTestCase):
    def test_renders_the_default_url(self):
        rendered = Template('{% load team_logo %}{% team_logo_url "notredame" %}').render(Context())

        self.assertEqual(rendered, 'https://cdn.redditcfb.com/60x40/cfb/notredame.png')

    @override_settings(TEAM_LOGO_URL_TEMPLATE='https://logos.example/{handle}.svg')
    def test_uses_the_configured_url_template(self):
        rendered = Template('{% load team_logo %}{% team_logo_url "notredame" %}').render(Context())

        self.assertEqual(rendered, 'https://logos.example/notredame.svg')


class TeamHandleMigrationTests(TransactionTestCase):
    def setUp(self):
        now = timezone.now()
        self.poll = Poll.objects.create(
            year=2026,
            week="Preseason",
            open_date=now - timedelta(days=21),
            close_date=now - timedelta(days=14),
            publish_date=now - timedelta(days=7),
            ap_date=now - timedelta(days=7),
        )
        self.user = User.objects.create(username="exporter")
        self.team = Team.objects.create(
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
            submission_date=now - timedelta(days=8),
            poll_type=Ballot.BallotType.HUMAN,
            user_type=UserRole.Role.VOTER,
            overall_rationale="=formula-like text",
        )
        BallotEntry.objects.create(
            ballot=self.ballot,
            team=self.team,
            rank=1,
            rationale="Top choice",
        )

    def test_csv_export_contains_all_ballot_entries(self):
        response = self.client.get(f"/poll/ballots/{self.poll.id}/1/export.csv")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("attachment;", response["Content-Disposition"])
        rows = list(csv.DictReader(response.content.decode().splitlines()))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["username"], "exporter")
        self.assertEqual(rows[0]["team_handle"], "ecu")
        self.assertNotIn("overall_rationale", rows[0])
        self.assertNotIn("rationale", rows[0])

    def test_json_export_groups_entries_by_ballot(self):
        response = self.client.get(f"/poll/ballots/{self.poll.id}/1/export.json")

        self.assertEqual(response.status_code, 200)
        payload = json.loads(response.content)
        self.assertEqual(payload["poll"]["voter_type"], "main")
        self.assertEqual(payload["ballots"][0]["username"], "exporter")
        self.assertEqual(payload["ballots"][0]["entries"][0]["team"]["handle"], "ecu")

    def test_exports_hide_unpublished_polls_from_anonymous_users(self):
        self.poll.publish_date = timezone.now() + timedelta(days=1)
        self.poll.save(update_fields=["publish_date"])

        self.assertEqual(self.client.get(f"/poll/ballots/{self.poll.id}/1/export.csv").status_code, 403)
        self.assertEqual(self.client.get(f"/poll/ballots/{self.poll.id}/1/export.json").status_code, 403)
