from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from poll.models import Ballot, Poll, ResultSet, User, UserRole
from poll.voter_forms import BulkPromotionForm, parse_usernames
from poll.voter_services import PromotionStatus, preview_provisional_voter_promotion, promote_provisional_voter


class UsernameParsingTests(SimpleTestCase):
    def test_supported_separators_whitespace_blanks_and_duplicates(self):
        self.assertEqual(
            parse_usernames(' SomeUser\n\nsomeuser, another_user\r\nThirdUser, '),
            ['SomeUser', 'another_user', 'ThirdUser'],
        )

    def test_empty_input_is_rejected_by_form(self):
        form = BulkPromotionForm({'usernames': ' ,\n '})
        self.assertFalse(form.is_valid())
        self.assertIn('at least one username', form.errors['usernames'][0])

    def test_leading_u_prefix_is_rejected_explicitly(self):
        form = BulkPromotionForm({'usernames': 'u/example'})
        self.assertFalse(form.is_valid())
        self.assertIn('without the leading "u/"', form.errors['usernames'][0])


class VoterPromotionServiceTests(TransactionTestCase):
    def setUp(self):
        self.now = timezone.now()
        self.open_poll = Poll.objects.create(
            year=2026, week='Open', open_date=self.now - timedelta(days=1),
            close_date=self.now + timedelta(days=1), publish_date=self.now,
            ap_date=self.now,
        )
        self.closed_poll = Poll.objects.create(
            year=2026, week='Closed', open_date=self.now - timedelta(days=3),
            close_date=self.now - timedelta(days=2), publish_date=self.now - timedelta(days=1),
            ap_date=self.now - timedelta(days=1),
        )

    def provisional(self, username):
        user = User.objects.create(username=username)
        role = UserRole.objects.create(
            user=user, role=UserRole.Role.PROVISIONAL,
            start_date=self.now - timedelta(days=5),
        )
        return user, role

    def test_preview_is_read_only_and_reports_impact(self):
        user, role = self.provisional('PreviewUser')
        open_ballot = Ballot.objects.create(user=user, poll=self.open_poll, user_type=UserRole.Role.PROVISIONAL)
        result = preview_provisional_voter_promotion('previewuser')
        self.assertEqual(result.status, PromotionStatus.READY)
        self.assertEqual(result.open_ballots, 1)
        role.refresh_from_db()
        open_ballot.refresh_from_db()
        self.assertIsNone(role.end_date)
        self.assertEqual(open_ballot.user_type, UserRole.Role.PROVISIONAL)

    def test_resolution_and_all_ineligible_states(self):
        self.provisional('KnownUser')
        User.objects.create(username='knownuser')
        User.objects.create(username='NoRole')
        main_user, _ = self.provisional('AlreadyMain')
        UserRole.objects.create(user=main_user, role=UserRole.Role.VOTER, start_date=self.now)
        multiple, _ = self.provisional('Multiple')
        UserRole.objects.create(user=multiple, role=UserRole.Role.PROVISIONAL, start_date=self.now)

        self.assertEqual(preview_provisional_voter_promotion('missing').reason, 'User not found')
        self.assertEqual(preview_provisional_voter_promotion('KNOWNUSER').reason, 'Ambiguous username')
        self.assertEqual(preview_provisional_voter_promotion('NoRole').reason, 'No active provisional voter role')
        self.assertEqual(preview_provisional_voter_promotion('AlreadyMain').reason, 'Already an active main voter')
        self.assertEqual(preview_provisional_voter_promotion('Multiple').reason, 'Multiple active provisional voter roles')

    def test_main_only_user_is_reported_as_already_main(self):
        user = User.objects.create(username='MainOnly')
        UserRole.objects.create(user=user, role=UserRole.Role.VOTER, start_date=self.now)
        result = preview_provisional_voter_promotion('mainonly')
        self.assertEqual(result.reason, 'Already an active main voter')

    def test_success_preserves_history_updates_open_only_and_isolated(self):
        user, provisional = self.provisional('PromoteMe')
        open_ballot = Ballot.objects.create(user=user, poll=self.open_poll, user_type=UserRole.Role.PROVISIONAL)
        closed_ballot = Ballot.objects.create(user=user, poll=self.closed_poll, user_type=UserRole.Role.PROVISIONAL)
        other, _ = self.provisional('Other')
        other_ballot = Ballot.objects.create(user=other, poll=self.open_poll, user_type=UserRole.Role.PROVISIONAL)

        result = promote_provisional_voter('promoteme')

        self.assertEqual(result.status, PromotionStatus.PROMOTED)
        self.assertEqual(result.open_ballots, 1)
        provisional.refresh_from_db()
        self.assertIsNotNone(provisional.end_date)
        self.assertEqual(UserRole.objects.filter(user=user, role=UserRole.Role.VOTER, end_date__isnull=True).count(), 1)
        open_ballot.refresh_from_db()
        closed_ballot.refresh_from_db()
        other_ballot.refresh_from_db()
        self.assertEqual(open_ballot.user_type, UserRole.Role.VOTER)
        self.assertEqual(closed_ballot.user_type, UserRole.Role.PROVISIONAL)
        self.assertEqual(other_ballot.user_type, UserRole.Role.PROVISIONAL)

    def test_promotion_invalidates_only_caches_for_affected_open_polls(self):
        user, _ = self.provisional('CacheUser')
        open_ballot = Ballot.objects.create(user=user, poll=self.open_poll, user_type=UserRole.Role.PROVISIONAL)
        already_main_ballot = Ballot.objects.create(user=user, poll=self.open_poll, user_type=UserRole.Role.VOTER)
        affected_cache = ResultSet.objects.create(poll=self.open_poll, time_calculated=self.now)
        unrelated_open_cache = ResultSet.objects.create(
            poll=self.open_poll, time_calculated=self.now, main=False, provisional=True,
        )
        closed_cache = ResultSet.objects.create(poll=self.closed_poll, time_calculated=self.now)

        result = promote_provisional_voter('CacheUser')

        self.assertEqual(result.open_ballots, 1)
        open_ballot.refresh_from_db()
        already_main_ballot.refresh_from_db()
        self.assertEqual(open_ballot.user_type, UserRole.Role.VOTER)
        self.assertEqual(already_main_ballot.user_type, UserRole.Role.VOTER)
        self.assertFalse(ResultSet.objects.filter(pk=affected_cache.pk).exists())
        self.assertFalse(ResultSet.objects.filter(pk=unrelated_open_cache.pk).exists())
        self.assertTrue(ResultSet.objects.filter(pk=closed_cache.pk).exists())

    def test_promotion_without_provisional_open_ballot_keeps_all_caches(self):
        self.provisional('NoBallot')
        open_cache = ResultSet.objects.create(poll=self.open_poll, time_calculated=self.now)
        closed_cache = ResultSet.objects.create(poll=self.closed_poll, time_calculated=self.now)

        result = promote_provisional_voter('NoBallot')

        self.assertEqual(result.status, PromotionStatus.PROMOTED)
        self.assertEqual(result.open_ballots, 0)
        self.assertTrue(ResultSet.objects.filter(pk=open_cache.pk).exists())
        self.assertTrue(ResultSet.objects.filter(pk=closed_cache.pk).exists())

    def test_repeated_execution_is_a_failure_and_does_not_duplicate_roles(self):
        user, _ = self.provisional('OnceOnly')
        self.assertEqual(promote_provisional_voter('OnceOnly').status, PromotionStatus.PROMOTED)
        result = promote_provisional_voter('OnceOnly')
        self.assertEqual(result.reason, 'Already an active main voter')
        self.assertEqual(UserRole.objects.filter(user=user, role=UserRole.Role.VOTER).count(), 1)

    @patch('django.db.models.query.QuerySet.update', side_effect=RuntimeError('database unavailable'))
    def test_unexpected_failure_rolls_back_that_user(self, update):
        user, provisional = self.provisional('RollbackMe')
        result = promote_provisional_voter('RollbackMe')
        self.assertEqual(result.reason, 'Unexpected error while promoting user')
        provisional.refresh_from_db()
        self.assertIsNone(provisional.end_date)
        self.assertFalse(UserRole.objects.filter(user=user, role=UserRole.Role.VOTER).exists())

    @patch('poll.voter_services.ResultSet.objects.filter', side_effect=RuntimeError('cache unavailable'))
    def test_cache_invalidation_failure_rolls_back_role_and_ballot(self, result_set_filter):
        user, provisional = self.provisional('CacheRollback')
        ballot = Ballot.objects.create(user=user, poll=self.open_poll, user_type=UserRole.Role.PROVISIONAL)
        ResultSet.objects.create(poll=self.open_poll, time_calculated=self.now)

        result = promote_provisional_voter('CacheRollback')

        self.assertEqual(result.reason, 'Unexpected error while promoting user')
        provisional.refresh_from_db()
        ballot.refresh_from_db()
        self.assertIsNone(provisional.end_date)
        self.assertEqual(ballot.user_type, UserRole.Role.PROVISIONAL)
        self.assertFalse(UserRole.objects.filter(user=user, role=UserRole.Role.VOTER).exists())


class BulkPromotionAdminTests(TransactionTestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user('admin', password='password')
        self.admin.is_staff = True
        self.admin.is_superuser = True
        self.admin.save()
        self.client.force_login(self.admin)
        self.user = User.objects.create(username='ReadyUser')
        UserRole.objects.create(user=self.user, role=UserRole.Role.PROVISIONAL, start_date=timezone.now())
        self.url = reverse('admin:poll_user_bulk_promote')

    def test_preview_then_confirm_revalidates_and_executes(self):
        response = self.client.post(self.url, {'usernames': ' ReadyUser\nreadyuser, missing '})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '2 unique usernames processed')
        self.assertContains(response, 'Confirm promotion')
        self.assertEqual(response.content.decode().count('<h1>Preview bulk promotion</h1>'), 1)
        self.assertContains(response, 'class="results"')
        self.assertIsNone(UserRole.objects.get(user=self.user, role=UserRole.Role.PROVISIONAL).end_date)

        response = self.client.post(self.url, {'usernames': ' ReadyUser\nreadyuser, missing ', 'confirm': '1'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Bulk promotion result')
        self.assertEqual(response.content.decode().count('<h1>Bulk promotion result</h1>'), 1)
        self.assertEqual(UserRole.objects.filter(user=self.user, role=UserRole.Role.VOTER, end_date__isnull=True).count(), 1)
        self.assertContains(response, 'User not found')

    def test_get_does_not_mutate_and_non_staff_is_denied(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(UserRole.objects.filter(user=self.user, role=UserRole.Role.VOTER).exists())
        self.admin.is_staff = False
        self.admin.save()
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_input_uses_admin_form_layout_and_single_title(self):
        response = self.client.get(self.url)
        html = response.content.decode()

        self.assertEqual(html.count('<h1>Bulk promote provisional voters</h1>'), 1)
        self.assertContains(response, 'class="form-row field-usernames"')
        self.assertContains(response, 'class="vLargeTextField"')
        self.assertContains(response, 'class="submit-row"')
        self.assertContains(response, 'value="Preview promotions" class="default"')

    def test_input_errors_use_normal_admin_error_markup(self):
        response = self.client.post(self.url, {'usernames': 'u/example'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="errorlist"')
        self.assertContains(response, 'without the leading &quot;u/&quot;')
        self.assertFalse(UserRole.objects.filter(user=self.user, role=UserRole.Role.VOTER).exists())

    def test_edit_preserves_original_input_without_mutation(self):
        original = ' ReadyUser\nreadyuser, missing '
        response = self.client.post(self.url, {'usernames': original})
        self.assertEqual(response.status_code, 200)

        response = self.client.post(self.url, {'usernames': original, 'edit': '1'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, original)
        self.assertFalse(UserRole.objects.filter(user=self.user, role=UserRole.Role.VOTER).exists())
