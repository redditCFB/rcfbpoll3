from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class UpgradedAuthenticationTests(TestCase):
    def test_local_login_and_logout_keep_session_flow(self):
        user = get_user_model().objects.create_user(
            username='upgrade_voter', password='test-password-123'
        )

        login = self.client.post(
            reverse('account_login'),
            {'login': user.username, 'password': 'test-password-123'},
        )
        self.assertRedirects(
            login, '/my_ballots/', fetch_redirect_response=False
        )
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)

        logout = self.client.post(reverse('account_logout'))
        self.assertRedirects(logout, '/', fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_reddit_login_starts_provider_authorization_without_network(self):
        response = self.client.post(reverse('reddit_login'))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith(
            'https://www.reddit.com/api/v1/authorize'
        ))
        self.assertIn('state=', response['Location'])
