from unittest.mock import Mock, patch

from cryptography.fernet import Fernet
from django.test import SimpleTestCase, TransactionTestCase
from django.test.utils import override_settings
from django.db import connection
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
from poll.reddit_admin import RedditAccountAdmin


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
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.schema_editor() as schema_editor:
            schema_editor.create_model(RedditAccount)
            schema_editor.create_model(RedditRoleAssignment)

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as schema_editor:
            schema_editor.delete_model(RedditRoleAssignment)
            schema_editor.delete_model(RedditAccount)
        super().tearDownClass()

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

    @override_settings(REDDIT_AUTOMATION_CLIENT_ID='', REDDIT_AUTOMATION_CLIENT_SECRET='')
    def test_missing_automation_app_fails(self):
        account = RedditAccount(username='configured-user', granted_scopes=['identity', 'privatemessages'])
        account.set_refresh_token('refresh-token')
        account.save()
        RedditRoleAssignment.objects.create(role=RedditRoleAssignment.Role.NOTIFICATIONS, account=account)
        with self.assertRaises(RedditAutomationNotConfigured):
            reddit_client_for_role(RedditRoleAssignment.Role.NOTIFICATIONS)
