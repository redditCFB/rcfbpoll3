import os
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command, CommandError
from django.test import TransactionTestCase, override_settings


class EnsureLocalAdminCommandTests(TransactionTestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            'LOCAL_ADMIN_USERNAME': 'localadmin',
            'LOCAL_ADMIN_PASSWORD': 'RcfbPollLocal2026!',
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    @override_settings(DEBUG=True)
    def test_creates_a_local_admin_with_hashed_password(self):
        call_command('ensure_local_admin', stdout=StringIO())
        user = get_user_model().objects.get(username='localadmin')

        self.assertTrue(user.check_password('RcfbPollLocal2026!'))
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertNotEqual(user.password, 'RcfbPollLocal2026!')

    @override_settings(DEBUG=True)
    def test_missing_username_environment_variable_fails_clearly(self):
        with patch.dict(os.environ, {
            'LOCAL_ADMIN_PASSWORD': 'RcfbPollLocal2026!',
        }, clear=True):
            with self.assertRaisesMessage(CommandError, 'LOCAL_ADMIN_USERNAME must be set and non-empty'):
                call_command('ensure_local_admin', stdout=StringIO())

    @override_settings(DEBUG=True)
    def test_missing_password_environment_variable_fails_clearly(self):
        with patch.dict(os.environ, {
            'LOCAL_ADMIN_USERNAME': 'localadmin',
        }, clear=True):
            with self.assertRaisesMessage(CommandError, 'LOCAL_ADMIN_PASSWORD must be set and non-empty'):
                call_command('ensure_local_admin', stdout=StringIO())

    @override_settings(DEBUG=True)
    def test_empty_environment_variable_fails_clearly(self):
        for name in ('LOCAL_ADMIN_USERNAME', 'LOCAL_ADMIN_PASSWORD'):
            environment = {
                'LOCAL_ADMIN_USERNAME': 'localadmin',
                'LOCAL_ADMIN_PASSWORD': 'RcfbPollLocal2026!',
                name: '',
            }
            with self.subTest(name=name), patch.dict(os.environ, environment, clear=True):
                with self.assertRaisesMessage(CommandError, f'{name} must be set and non-empty'):
                    call_command('ensure_local_admin', stdout=StringIO())

    @override_settings(DEBUG=True)
    def test_is_idempotent_and_does_not_reset_existing_password(self):
        user_model = get_user_model()
        user_model.objects.create_user(
            username='localadmin', password='custom-local-password',
            is_active=False, is_staff=False, is_superuser=False,
        )

        call_command('ensure_local_admin', stdout=StringIO())
        call_command('ensure_local_admin', stdout=StringIO())

        user = user_model.objects.get(username='localadmin')
        self.assertEqual(user_model.objects.filter(username='localadmin').count(), 1)
        self.assertTrue(user.check_password('custom-local-password'))
        self.assertTrue(user.is_active)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)

    @override_settings(DEBUG=False)
    def test_refuses_to_run_when_debug_is_disabled(self):
        with self.assertRaisesMessage(CommandError, 'only available when DEBUG=True'):
            call_command('ensure_local_admin', stdout=StringIO())
        self.assertFalse(get_user_model().objects.filter(username='localadmin').exists())
