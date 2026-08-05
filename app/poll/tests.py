from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.template import Context, Template
from django.test import SimpleTestCase, TransactionTestCase
from django.test.utils import override_settings
from django.utils import timezone

from poll.models import ProvisionalUserApplication, Team, User, UserRole
from poll.management.commands.update_team_logo_handles import TEAM_HANDLE_RENAMES


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


class TeamLogoUrlTagTests(SimpleTestCase):
    def test_renders_the_default_url(self):
        rendered = Template('{% load team_logo %}{% team_logo_url "notredame" %}').render(Context())

        self.assertEqual(rendered, 'https://cdn.redditcfb.com/60x40/cfb/notredame.png')

    @override_settings(TEAM_LOGO_URL_TEMPLATE='https://logos.example/{handle}.svg')
    def test_uses_the_configured_url_template(self):
        rendered = Template('{% load team_logo %}{% team_logo_url "notredame" %}').render(Context())

        self.assertEqual(rendered, 'https://logos.example/notredame.svg')


class TeamHandleMigrationTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.schema_editor() as schema_editor:
            schema_editor.create_model(Team)

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as schema_editor:
            schema_editor.delete_model(Team)
        super().tearDownClass()

    def create_team(self, handle):
        return Team.objects.create(
            handle=handle,
            name=handle,
            conference="Test",
            division="Test",
            use_for_ballot=False,
            short_name=handle,
        )

    def test_updates_and_can_be_rerun(self):
        teams = {handle: self.create_team(handle) for handle in TEAM_HANDLE_RENAMES}

        call_command("update_team_logo_handles")

        for legacy_handle, cdn_handle in TEAM_HANDLE_RENAMES.items():
            teams[legacy_handle].refresh_from_db()
            self.assertEqual(teams[legacy_handle].handle, cdn_handle)

        output = StringIO()
        call_command("update_team_logo_handles", stdout=output)
        self.assertIn("Updated 0 team handle(s); 14 already applied.", output.getvalue())

    def test_aborts_when_a_target_handle_already_exists(self):
        legacy_teams = {handle: self.create_team(handle) for handle in TEAM_HANDLE_RENAMES}
        legacy_team = legacy_teams["eastcarolina"]
        target_team = self.create_team("ecu")

        with self.assertRaises(CommandError):
            call_command("update_team_logo_handles")

        legacy_team.refresh_from_db()
        target_team.refresh_from_db()
        self.assertEqual(legacy_team.handle, "eastcarolina")
        self.assertEqual(target_team.handle, "ecu")
