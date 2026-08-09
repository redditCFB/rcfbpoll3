from unittest.mock import Mock, patch

from cryptography.fernet import Fernet
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, SimpleTestCase, TransactionTestCase
from django.test.utils import override_settings
from django.contrib import admin

from poll.models import RedditAccount, RedditRoleAssignment
from poll.reddit_crypto import TokenEncryptionError, decrypt_refresh_token, encrypt_refresh_token
from poll.reddit_integration import (
    RedditAutomationNotConfigured,
    RedditRoleNotAssigned,
    RedditScopesMissing,
    reddit_client_for_role,
    required_scopes_for_roles,
)
from poll.reddit_admin import RedditAccountAdmin, RedditRoleAssignmentAdmin


class RedditScopeAndTokenTests(SimpleTestCase):
    @override_settings(REDDIT_AUTOMATION_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode())
    def test_role_scope_union_and_encrypted_round_trip(self):
        scopes = required_scopes_for_roles([
            RedditRoleAssignment.Role.APPLICATION_REVIEW,
            RedditRoleAssignment.Role.RESULTS_PUBLISHER,
        ])
        self.assertEqual(scopes, {'identity', 'read', 'submit'})
        ciphertext = encrypt_refresh_token('secret-refresh-token')
        self.assertNotIn('secret-refresh-token', ciphertext)
        self.assertEqual(decrypt_refresh_token(ciphertext), 'secret-refresh-token')

    @override_settings(REDDIT_AUTOMATION_TOKEN_ENCRYPTION_KEY='')
    def test_missing_encryption_key_fails_safely(self):
        with self.assertRaises(TokenEncryptionError):
            encrypt_refresh_token('secret-refresh-token')


class RedditOAuthFlowTests(SimpleTestCase):
    def test_only_superusers_can_manage_reddit_admin_models_and_views(self):
        account_admin = RedditAccountAdmin(RedditAccount, admin.site)
        assignment_admin = RedditRoleAssignmentAdmin(RedditRoleAssignment, admin.site)
        request = RequestFactory().get('/admin/')
        request.user = Mock(is_authenticated=True, is_superuser=False, is_staff=True)

        for model_admin in (account_admin, assignment_admin):
            self.assertFalse(model_admin.has_module_permission(request))
            self.assertFalse(model_admin.has_view_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))
        self.assertFalse(account_admin.has_add_permission(request))
        self.assertFalse(assignment_admin.has_add_permission(request))
        with self.assertRaises(PermissionDenied):
            account_admin.connect_view(request)
        with self.assertRaises(PermissionDenied):
            account_admin.oauth_callback(request)
        with self.assertRaises(PermissionDenied):
            account_admin.reauthorize_view(request, 1)

        request.user = Mock(is_authenticated=True, is_superuser=True, is_staff=True)
        self.assertTrue(account_admin.has_module_permission(request))
        self.assertTrue(assignment_admin.has_add_permission(request))

    @override_settings(
        REDDIT_AUTOMATION_CLIENT_ID='automation-id',
        REDDIT_AUTOMATION_CLIENT_SECRET='automation-secret',
        REDDIT_AUTOMATION_USER_AGENT='poll automation',
        REDDIT_AUTOMATION_REDIRECT_URI='https://poll.example/admin/poll/redditaccount/oauth/callback/',
    )
    @patch('poll.reddit_admin.oauth_client')
    def test_connect_requests_permanent_union_scopes_and_tracks_state(self, oauth_client):
        request = Mock()
        class Session(dict):
            modified = False
        request.session = Session()
        client = oauth_client.return_value
        client.auth.url.return_value = 'https://reddit.example/authorize'
        model_admin = RedditAccountAdmin(RedditAccount, admin.site)

        response = model_admin._start_oauth(
            request,
            [RedditRoleAssignment.Role.APPLICATION_REVIEW, RedditRoleAssignment.Role.RESULTS_PUBLISHER],
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'https://reddit.example/authorize')
        pending = request.session['reddit_automation_oauth']
        self.assertTrue(pending['state'])
        client.auth.url.assert_called_once_with(
            scopes=['identity', 'read', 'submit'], state=pending['state'], duration='permanent',
        )


class RedditClientResolverTests(TransactionTestCase):
    @override_settings(
        REDDIT_AUTOMATION_CLIENT_ID='automation-id',
        REDDIT_AUTOMATION_CLIENT_SECRET='automation-secret',
        REDDIT_AUTOMATION_USER_AGENT='poll automation',
        REDDIT_AUTOMATION_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    )
    @patch('poll.reddit_integration.praw.Reddit')
    def test_resolver_uses_assigned_account_and_automation_credentials(self, reddit_class):
        account = RedditAccount(username='automation-user', granted_scopes=['identity', 'privatemessages'])
        account.set_refresh_token('refresh-token')
        account.save()
        RedditRoleAssignment.objects.create(role=RedditRoleAssignment.Role.NOTIFICATIONS, account=account)

        client = reddit_client_for_role(RedditRoleAssignment.Role.NOTIFICATIONS)

        self.assertIs(client, reddit_class.return_value)
        reddit_class.assert_called_once_with(
            client_id='automation-id', client_secret='automation-secret',
            user_agent='poll automation', refresh_token='refresh-token',
        )

    @override_settings(
        REDDIT_AUTOMATION_CLIENT_ID='automation-id',
        REDDIT_AUTOMATION_CLIENT_SECRET='automation-secret',
        REDDIT_AUTOMATION_USER_AGENT='poll automation',
        REDDIT_AUTOMATION_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    )
    def test_unassigned_role_fails(self):
        with self.assertRaises(RedditRoleNotAssigned):
            reddit_client_for_role(RedditRoleAssignment.Role.NOTIFICATIONS)

    @override_settings(
        REDDIT_AUTOMATION_CLIENT_ID='automation-id',
        REDDIT_AUTOMATION_CLIENT_SECRET='automation-secret',
        REDDIT_AUTOMATION_USER_AGENT='poll automation',
        REDDIT_AUTOMATION_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    )
    def test_missing_scope_fails(self):
        account = RedditAccount(username='scope-user', granted_scopes=['identity'])
        account.set_refresh_token('refresh-token')
        account.save()
        RedditRoleAssignment.objects.create(role=RedditRoleAssignment.Role.NOTIFICATIONS, account=account)
        with self.assertRaises(RedditScopesMissing):
            reddit_client_for_role(RedditRoleAssignment.Role.NOTIFICATIONS)

    @override_settings(
        REDDIT_AUTOMATION_CLIENT_ID='', REDDIT_AUTOMATION_CLIENT_SECRET='',
        REDDIT_AUTOMATION_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    )
    def test_missing_automation_app_fails(self):
        account = RedditAccount(username='configured-user', granted_scopes=['identity', 'privatemessages'])
        account.set_refresh_token('refresh-token')
        account.save()
        RedditRoleAssignment.objects.create(role=RedditRoleAssignment.Role.NOTIFICATIONS, account=account)
        with self.assertRaises(RedditAutomationNotConfigured):
            reddit_client_for_role(RedditRoleAssignment.Role.NOTIFICATIONS)

    def _callback_request(self, account_id, roles, state='state-value'):
        from django.test import RequestFactory
        request = RequestFactory().get('/admin/poll/redditaccount/oauth/callback/', {'state': state, 'code': 'code'})
        request.user = Mock(is_authenticated=True, is_superuser=True, is_staff=True)
        request.session = {'reddit_automation_oauth': {'state': state, 'roles': roles, 'account_id': account_id}}
        return request

    @override_settings(
        REDDIT_AUTOMATION_CLIENT_ID='automation-id',
        REDDIT_AUTOMATION_CLIENT_SECRET='automation-secret',
        REDDIT_AUTOMATION_USER_AGENT='poll automation',
        REDDIT_AUTOMATION_REDIRECT_URI='https://poll.example/callback',
        REDDIT_AUTOMATION_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    )
    @patch('poll.reddit_admin.messages.error')
    @patch('poll.reddit_admin.oauth_client')
    def test_duplicate_connect_does_not_downgrade_existing_account(self, oauth_client, message_error):
        account = RedditAccount(username='sirgippy', granted_scopes=['identity', 'read'])
        account.set_refresh_token('old-token')
        account.save()
        RedditRoleAssignment.objects.create(role=RedditRoleAssignment.Role.APPLICATION_REVIEW, account=account)
        client = oauth_client.return_value
        client.auth.authorize.return_value = 'new-token'
        client.auth.scopes.return_value = {'identity', 'submit'}
        client.user.me.return_value.name = 'sirgippy'

        response = RedditAccountAdmin(RedditAccount, admin.site).oauth_callback(
            self._callback_request(None, [RedditRoleAssignment.Role.RESULTS_PUBLISHER])
        )

        self.assertEqual(response.status_code, 302)
        account.refresh_from_db()
        self.assertEqual(decrypt_refresh_token(account.encrypted_refresh_token), 'old-token')
        self.assertEqual(account.granted_scopes, ['identity', 'read'])
        self.assertEqual(list(account.role_assignments.values_list('role', flat=True)), ['APPLICATION_REVIEW'])
        message_error.assert_called_once()

    @override_settings(
        REDDIT_AUTOMATION_CLIENT_ID='automation-id',
        REDDIT_AUTOMATION_CLIENT_SECRET='automation-secret',
        REDDIT_AUTOMATION_USER_AGENT='poll automation',
        REDDIT_AUTOMATION_REDIRECT_URI='https://poll.example/callback',
        REDDIT_AUTOMATION_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    )
    @patch('poll.reddit_admin.messages.success')
    @patch('poll.reddit_admin.oauth_client')
    def test_reauthorization_replaces_credential_for_same_identity(self, oauth_client, message_success):
        account = RedditAccount(username='SirGippy', granted_scopes=['identity', 'read'])
        account.set_refresh_token('old-token')
        account.save()
        RedditRoleAssignment.objects.create(role=RedditRoleAssignment.Role.APPLICATION_REVIEW, account=account)
        RedditRoleAssignment.objects.create(role=RedditRoleAssignment.Role.RESULTS_PUBLISHER, account=account)
        client = oauth_client.return_value
        client.auth.authorize.return_value = 'new-token'
        client.auth.scopes.return_value = {'identity', 'read', 'submit'}
        client.user.me.return_value.name = 'sirgippy'

        RedditAccountAdmin(RedditAccount, admin.site).oauth_callback(
            self._callback_request(account.pk, [
                RedditRoleAssignment.Role.APPLICATION_REVIEW,
                RedditRoleAssignment.Role.RESULTS_PUBLISHER,
            ])
        )

        account.refresh_from_db()
        self.assertEqual(decrypt_refresh_token(account.encrypted_refresh_token), 'new-token')
        self.assertEqual(set(account.granted_scopes), {'identity', 'read', 'submit'})
        self.assertEqual(RedditAccount.objects.count(), 1)
        message_success.assert_called_once()

    @override_settings(
        REDDIT_AUTOMATION_CLIENT_ID='automation-id',
        REDDIT_AUTOMATION_CLIENT_SECRET='automation-secret',
        REDDIT_AUTOMATION_USER_AGENT='poll automation',
        REDDIT_AUTOMATION_REDIRECT_URI='https://poll.example/callback',
        REDDIT_AUTOMATION_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    )
    @patch('poll.reddit_admin.messages.error')
    @patch('poll.reddit_admin.oauth_client')
    def test_reauthorization_different_identity_preserves_old_credential(self, oauth_client, message_error):
        account = RedditAccount(username='sirgippy', granted_scopes=['identity', 'read'])
        account.set_refresh_token('old-token')
        account.save()
        RedditRoleAssignment.objects.create(role=RedditRoleAssignment.Role.APPLICATION_REVIEW, account=account)
        client = oauth_client.return_value
        client.auth.authorize.return_value = 'new-token'
        client.auth.scopes.return_value = {'identity', 'read'}
        client.user.me.return_value.name = 'other-user'

        RedditAccountAdmin(RedditAccount, admin.site).oauth_callback(
            self._callback_request(account.pk, [RedditRoleAssignment.Role.APPLICATION_REVIEW])
        )

        account.refresh_from_db()
        self.assertEqual(decrypt_refresh_token(account.encrypted_refresh_token), 'old-token')
        message_error.assert_called_once()

    @override_settings(
        REDDIT_AUTOMATION_CLIENT_ID='automation-id',
        REDDIT_AUTOMATION_CLIENT_SECRET='automation-secret',
        REDDIT_AUTOMATION_USER_AGENT='poll automation',
        REDDIT_AUTOMATION_REDIRECT_URI='https://poll.example/callback',
        REDDIT_AUTOMATION_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    )
    @patch('poll.reddit_admin.messages.error')
    @patch('poll.reddit_admin.oauth_client')
    def test_missing_refresh_token_does_not_create_account(self, oauth_client, message_error):
        client = oauth_client.return_value
        client.auth.authorize.return_value = None
        client.auth.scopes.return_value = {'identity', 'privatemessages'}
        client.user.me.return_value.name = 'new-user'
        RedditAccountAdmin(RedditAccount, admin.site).oauth_callback(
            self._callback_request(None, [RedditRoleAssignment.Role.NOTIFICATIONS])
        )
        self.assertEqual(RedditAccount.objects.count(), 0)
        message_error.assert_called_once()

    @override_settings(
        REDDIT_AUTOMATION_CLIENT_ID='automation-id',
        REDDIT_AUTOMATION_CLIENT_SECRET='automation-secret',
        REDDIT_AUTOMATION_USER_AGENT='poll automation',
        REDDIT_AUTOMATION_REDIRECT_URI='https://poll.example/callback',
        REDDIT_AUTOMATION_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    )
    @patch('poll.reddit_admin.messages.error')
    @patch('poll.reddit_admin.oauth_client')
    def test_unknown_scopes_do_not_create_account(self, oauth_client, message_error):
        client = oauth_client.return_value
        client.auth.authorize.return_value = 'new-token'
        client.auth.scopes.return_value = set()
        client.user.me.return_value.name = 'new-user'
        RedditAccountAdmin(RedditAccount, admin.site).oauth_callback(
            self._callback_request(None, [RedditRoleAssignment.Role.NOTIFICATIONS])
        )
        self.assertEqual(RedditAccount.objects.count(), 0)
        message_error.assert_called_once()

    @override_settings(
        REDDIT_AUTOMATION_CLIENT_ID='automation-id',
        REDDIT_AUTOMATION_CLIENT_SECRET='automation-secret',
        REDDIT_AUTOMATION_USER_AGENT='poll automation',
        REDDIT_AUTOMATION_REDIRECT_URI='https://poll.example/callback',
        REDDIT_AUTOMATION_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    )
    @patch('poll.reddit_admin.messages.error')
    @patch('poll.reddit_admin.RedditRoleAssignment.objects.update_or_create', side_effect=RuntimeError('write failed'))
    @patch('poll.reddit_admin.oauth_client')
    def test_persistence_failure_rolls_back_new_account(self, oauth_client, update_role, message_error):
        client = oauth_client.return_value
        client.auth.authorize.return_value = 'new-token'
        client.auth.scopes.return_value = {'identity', 'privatemessages'}
        client.user.me.return_value.name = 'new-user'
        RedditAccountAdmin(RedditAccount, admin.site).oauth_callback(
            self._callback_request(None, [RedditRoleAssignment.Role.NOTIFICATIONS])
        )
        self.assertEqual(RedditAccount.objects.count(), 0)
        message_error.assert_called_once()
