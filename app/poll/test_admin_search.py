from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from poll.models import Ballot, Poll, User, UserRole


class BallotAdminSearchTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.poll = Poll.objects.create(
            year=2026,
            week='Week 5',
            open_date=now - timedelta(days=1),
            close_date=now + timedelta(days=1),
            publish_date=now + timedelta(days=2),
            ap_date=now + timedelta(days=2),
        )
        self.user = User.objects.create(username='searchable_voter')
        self.ballot = Ballot.objects.create(
            user=self.user,
            poll=self.poll,
            poll_type=Ballot.BallotType.HUMAN,
            user_type=UserRole.Role.VOTER,
        )
        admin_user = get_user_model().objects.create_superuser(
            username='admin-search-test',
            email='admin-search-test@example.com',
            password='not-used-in-tests',
        )
        self.client.force_login(admin_user)

    def test_ballot_changelist_searches_by_voter_username(self):
        response = self.client.get('/admin/poll/ballot/', {'q': self.user.username})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['cl'].result_count, 1)
        self.assertEqual(list(response.context['cl'].result_list), [self.ballot])
