from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TransactionTestCase
from django.utils import timezone

from poll.admin import ApplicationAdmin
from poll.models import ProvisionalUserApplication, User, UserRole
from poll.provisional_screening import (
    AccountAgeGate, GateStatus, normalize_username, screen_moderator_reference, screen_username,
)
from poll.provisional_services import accept_provisional_application


class ScreeningGateTests(SimpleTestCase):
    def test_normalization_and_username_policy(self):
        self.assertEqual(normalize_username('MiXeD_Name-14'), 'mixednameia')
        self.assertEqual(screen_username('ordinary_profanity_5').status, GateStatus.PASS)
        self.assertEqual(screen_username('ordinary_name').status, GateStatus.PASS)
        self.assertEqual(screen_username('n_i_g_g_e_r').status, GateStatus.REVIEW)
        self.assertEqual(screen_username('n1gg3r').status, GateStatus.REVIEW)
        self.assertEqual(screen_username('niggor').status, GateStatus.REVIEW)
        self.assertEqual(screen_username('scunthorpe').status, GateStatus.PASS)

    def test_moderator_gate_is_conservative_and_fails_closed(self):
        class Provider:
            def usernames(self):
                return ('LongCurrentMod', 'bob')

        self.assertEqual(screen_moderator_reference('LongCurrentMod', Provider()).status, GateStatus.REVIEW)
        self.assertEqual(screen_moderator_reference('long-current-mod-fan', Provider()).status, GateStatus.REVIEW)
        self.assertEqual(screen_moderator_reference('LongCurr3ntMod', Provider()).status, GateStatus.REVIEW)
        self.assertEqual(screen_moderator_reference('bobcat', Provider()).status, GateStatus.PASS)
        self.assertEqual(screen_moderator_reference('safe_name').status, GateStatus.ERROR)
        with patch.dict('os.environ', {'RCFB_MODERATOR_USERNAMES': 'bad name'}, clear=False):
            self.assertEqual(screen_moderator_reference('safe_name').status, GateStatus.ERROR)

    def test_account_age_gate_always_passes(self):
        self.assertEqual(AccountAgeGate().evaluate('any_name').status, GateStatus.PASS)


class AcceptanceServiceTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create(username='service_user')
        self.application = ProvisionalUserApplication.objects.create(
            user=self.user, submission_date=timezone.now(), status=ProvisionalUserApplication.Status.OPEN,
        )

    @patch('poll.provisional_services.send_provisional_application_decision_message', return_value=False)
    def test_acceptance_is_saved_once_when_notification_fails(self, notify):
        accepted, notified = accept_provisional_application(
            self.application, ProvisionalUserApplication.DecisionSource.AUTOMATIC,
        )
        self.assertTrue(accepted)
        self.assertFalse(notified)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, ProvisionalUserApplication.Status.ACCEPTED)
        self.assertEqual(self.application.decision_source, ProvisionalUserApplication.DecisionSource.AUTOMATIC)
        self.assertEqual(UserRole.objects.filter(
            user=self.user, role=UserRole.Role.PROVISIONAL, end_date__isnull=True).count(), 1)
        accepted_again, _ = accept_provisional_application(
            self.application, ProvisionalUserApplication.DecisionSource.AUTOMATIC,
        )
        self.assertFalse(accepted_again)
        self.assertEqual(UserRole.objects.filter(
            user=self.user, role=UserRole.Role.PROVISIONAL, end_date__isnull=True).count(), 1)
        notify.assert_called_once()


class SubmissionAndCommandTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create(username='clean_submission_user')

    @patch('poll.provisional_services.send_provisional_application_decision_message', return_value=False)
    def test_submission_auto_accepts_with_configured_moderator_list(self, notify):
        from django.contrib.auth import get_user_model
        auth_user = get_user_model().objects.create_user(username=self.user.username, password='pw')
        self.client.force_login(auth_user)
        with patch.dict('os.environ', {'RCFB_MODERATOR_USERNAMES': 'current_mod'}, clear=False):
            response = self.client.get('/apply_for_provisional/')
        self.assertRedirects(response, '/my_ballots/')
        app = ProvisionalUserApplication.objects.get(user=self.user)
        self.assertEqual(app.status, ProvisionalUserApplication.Status.ACCEPTED)
        self.assertEqual(app.screening_flags, [])
        self.assertTrue(UserRole.objects.filter(user=self.user, role=UserRole.Role.PROVISIONAL, end_date__isnull=True).exists())
        notify.assert_called_once()

    @patch('poll.provisional_services.send_provisional_application_decision_message', return_value=False)
    def test_command_only_processes_open_and_is_idempotent(self, notify):
        clean = User.objects.create(username='command_clean')
        ProvisionalUserApplication.objects.create(
            user=clean, submission_date=timezone.now() - timedelta(days=2),
            status=ProvisionalUserApplication.Status.OPEN,
        )
        flagged = User.objects.create(username='n_i_g_g_e_r')
        ProvisionalUserApplication.objects.create(
            user=flagged, submission_date=timezone.now() - timedelta(days=1),
            status=ProvisionalUserApplication.Status.OPEN,
        )
        decided = User.objects.create(username='already_decided')
        ProvisionalUserApplication.objects.create(
            user=decided, submission_date=timezone.now(),
            status=ProvisionalUserApplication.Status.ACCEPTED,
        )
        with patch.dict('os.environ', {'RCFB_MODERATOR_USERNAMES': 'current_mod'}, clear=False):
            output = StringIO()
            call_command('screen_open_provisional_applications', stdout=output)
            call_command('screen_open_provisional_applications', stdout=output)
        self.assertIn('automatically accepted: 1', output.getvalue())
        self.assertEqual(ProvisionalUserApplication.objects.filter(status=ProvisionalUserApplication.Status.ACCEPTED).count(), 2)
        notify.assert_called_once()

class AdminOrderingTests(TransactionTestCase):
    def test_open_applications_precede_decided_and_each_group_is_newest_first(self):
        now = timezone.now()
        users = [User.objects.create(username='admin_order_%s' % index) for index in range(4)]
        records = [
            (users[0], ProvisionalUserApplication.Status.ACCEPTED, now - timedelta(days=1)),
            (users[1], ProvisionalUserApplication.Status.OPEN, now - timedelta(days=2)),
            (users[2], ProvisionalUserApplication.Status.REJECTED, now - timedelta(days=3)),
            (users[3], ProvisionalUserApplication.Status.OPEN, now - timedelta(days=4)),
        ]
        for user, status, submitted in records:
            ProvisionalUserApplication.objects.create(
                user=user, status=status, submission_date=submitted,
            )
        ordered = list(ApplicationAdmin(ProvisionalUserApplication, None).get_queryset(None))
        self.assertEqual(
            [application.status for application in ordered],
            [ProvisionalUserApplication.Status.OPEN, ProvisionalUserApplication.Status.OPEN,
             ProvisionalUserApplication.Status.ACCEPTED, ProvisionalUserApplication.Status.REJECTED],
        )
        self.assertEqual(
            [application.submission_date for application in ordered],
            [records[1][2], records[3][2], records[0][2], records[2][2]],
        )
