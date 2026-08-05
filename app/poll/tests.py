from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone

from poll.models import ProvisionalUserApplication, Team, User, UserRole


class ProvisionalApplicationTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.schema_editor() as schema_editor:
            for model in (Team, User, UserRole, ProvisionalUserApplication):
                schema_editor.create_model(model)

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as schema_editor:
            for model in (ProvisionalUserApplication, UserRole, User, Team):
                schema_editor.delete_model(model)
        super().tearDownClass()

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
