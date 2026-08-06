import csv
from datetime import timedelta
from io import StringIO
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.template import Context, Template
from django.test import SimpleTestCase, TransactionTestCase
from django.test.utils import override_settings
from django.utils import timezone

from poll.admin import accept_applications, reject_applications
from poll.models import Ballot, BallotEntry, Poll, ProvisionalUserApplication, Team, User, UserRole
from poll.notifications import send_provisional_application_decision_message
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


class ProvisionalApplicationNotificationTests(TransactionTestCase):
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
        self.poll_user = User.objects.create(username='notification_test_user')
        self.application = ProvisionalUserApplication.objects.create(
            user=self.poll_user,
            submission_date=timezone.now(),
            status=ProvisionalUserApplication.Status.OPEN,
        )

    @override_settings(
        REDDIT_MESSAGE_CLIENT_ID='client-id',
        REDDIT_MESSAGE_CLIENT_SECRET='client-secret',
        REDDIT_MESSAGE_REFRESH_TOKEN='refresh-token',
    )
    @patch('poll.notifications.praw.Reddit')
    def test_acceptance_message_is_sent_from_configured_account(self, reddit_class):
        self.application.status = ProvisionalUserApplication.Status.ACCEPTED
        self.application.save(update_fields=['status'])

        self.assertTrue(send_provisional_application_decision_message(self.application))

        reddit_class.assert_called_once_with(
            client_id='client-id',
            client_secret='client-secret',
            refresh_token='refresh-token',
            user_agent='django:rcfbpoll:3.0 (by /u/CFB_Referee)',
        )
        reddit_class.return_value.redditor.assert_called_once_with('notification_test_user')
        subject, body = reddit_class.return_value.redditor.return_value.message.call_args.args
        self.assertEqual(subject, 'Your r/CFB Poll provisional voter application was approved')
        self.assertIn('submit provisional ballots', body)
        self.assertIn('provisional results', body)

    @override_settings(
        REDDIT_MESSAGE_CLIENT_ID='client-id',
        REDDIT_MESSAGE_CLIENT_SECRET='client-secret',
        REDDIT_MESSAGE_REFRESH_TOKEN='refresh-token',
    )
    @patch('poll.notifications.praw.Reddit')
    def test_rejection_message_is_sent_from_configured_account(self, reddit_class):
        self.application.status = ProvisionalUserApplication.Status.REJECTED
        self.application.save(update_fields=['status'])

        self.assertTrue(send_provisional_application_decision_message(self.application))

        reddit_class.return_value.redditor.assert_called_once_with('notification_test_user')
        subject, body = reddit_class.return_value.redditor.return_value.message.call_args.args
        self.assertEqual(subject, 'Your r/CFB Poll provisional voter application was not approved')
        self.assertIn('Thank you for your interest', body)
        self.assertIn('u/sirgippy', body)
        self.assertIn('r/CFB moderators', body)

    @patch('poll.notifications.praw.Reddit')
    def test_message_is_skipped_when_bot_credentials_are_not_configured(self, reddit_class):
        self.application.status = ProvisionalUserApplication.Status.REJECTED
        self.application.save(update_fields=['status'])

        self.assertFalse(send_provisional_application_decision_message(self.application))
        reddit_class.assert_not_called()

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


class ObtainRedditRefreshTokenCommandTests(SimpleTestCase):
    @override_settings(
        REDDIT_MESSAGE_CLIENT_ID='client-id',
        REDDIT_MESSAGE_CLIENT_SECRET='client-secret',
    )
    @patch('poll.management.commands.obtain_reddit_refresh_token.secrets.token_urlsafe', return_value='state-value')
    @patch('poll.management.commands.obtain_reddit_refresh_token.praw.Reddit')
    @patch('builtins.input', return_value='http://localhost:8080/?state=state-value&code=authorization-code')
    def test_exchanges_a_valid_callback_code_for_a_refresh_token(self, mocked_input, reddit_class, token_urlsafe):
        reddit_class.return_value.auth.url.return_value = 'https://www.reddit.com/api/v1/authorize?...'
        reddit_class.return_value.auth.authorize.return_value = 'refresh-token'
        output = StringIO()

        call_command('obtain_reddit_refresh_token', stdout=output)

        reddit_class.assert_called_once_with(
            client_id='client-id',
            client_secret='client-secret',
            redirect_uri='http://localhost:8080',
            user_agent='django:rcfbpoll:3.0 (by /u/CFB_Referee)',
        )
        reddit_class.return_value.auth.url.assert_called_once_with(
            scopes=['identity', 'privatemessages'],
            state='state-value',
            duration='permanent',
        )
        reddit_class.return_value.auth.authorize.assert_called_once_with('authorization-code')
        self.assertIn('REDDIT_MESSAGE_REFRESH_TOKEN=refresh-token', output.getvalue())

    @override_settings(REDDIT_MESSAGE_CLIENT_ID='', REDDIT_MESSAGE_CLIENT_SECRET='')
    def test_requires_reddit_web_app_credentials(self):
        with self.assertRaisesMessage(
            CommandError,
            'Set REDDIT_MESSAGE_CLIENT_ID and REDDIT_MESSAGE_CLIENT_SECRET before running this command.',
        ):
            call_command('obtain_reddit_refresh_token')


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


class BallotExportTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.schema_editor() as schema_editor:
            for model in (Team, User, Poll, Ballot, BallotEntry):
                schema_editor.create_model(model)

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as schema_editor:
            for model in (BallotEntry, Ballot, Poll, User, Team):
                schema_editor.delete_model(model)
        super().tearDownClass()

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
