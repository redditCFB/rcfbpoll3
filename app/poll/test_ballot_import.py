import csv
import io
import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TransactionTestCase
from django.utils import timezone

from poll.ballot_import import BallotImportError, parse_ballot_import, validate_entries
from poll.models import Ballot, BallotEntry, Poll, Team, User, UserRole


class BallotImportParserTests(SimpleTestCase):
    def setUp(self):
        self.teams = {
            f'team-{number}': type('TeamStub', (), {'handle': f'team-{number}', 'id': number})()
            for number in range(1, 26)
        }

    def _csv(self, ranks=None):
        ranks = ranks or range(1, 26)
        rows = ['rank,team_handle'] + [f'{rank},team-{rank}' for rank in ranks]
        return SimpleUploadedFile('ballot.csv', '\n'.join(rows).encode())

    def _json(self, **overrides):
        payload = {
            'entries': [
                {'rank': rank, 'team_handle': f'team-{rank}'}
                for rank in range(1, 26)
            ],
            **overrides,
        }
        return SimpleUploadedFile('ballot.json', json.dumps(payload).encode())

    def test_csv_parses_complete_ranking(self):
        imported = parse_ballot_import(self._csv(), self.teams)
        validate_entries(imported['entries'])
        self.assertEqual(imported['entries'][0]['team'].handle, 'team-1')

    def test_json_integer_rank_is_accepted(self):
        imported = parse_ballot_import(self._json(), self.teams)
        self.assertEqual(imported['entries'][0]['rank'], 1)

    def test_json_float_rank_is_rejected(self):
        upload = self._json()
        payload = json.loads(upload.read())
        payload['entries'][0]['rank'] = 1.5
        with self.assertRaisesMessage(BallotImportError, 'rank must be an integer'):
            parse_ballot_import(SimpleUploadedFile('ballot.json', json.dumps(payload).encode()), self.teams)

    def test_json_boolean_rank_is_rejected(self):
        upload = self._json()
        payload = json.loads(upload.read())
        payload['entries'][0]['rank'] = True
        with self.assertRaisesMessage(BallotImportError, 'rank must be an integer'):
            parse_ballot_import(SimpleUploadedFile('ballot.json', json.dumps(payload).encode()), self.teams)

    def test_invalid_csv_rank_is_rejected(self):
        upload = SimpleUploadedFile('ballot.csv', b'rank,team_handle\nnot-an-integer,team-1')
        with self.assertRaisesMessage(BallotImportError, 'rank must be an integer'):
            parse_ballot_import(upload, self.teams)

    def test_malformed_csv_is_rejected(self):
        upload = SimpleUploadedFile('ballot.csv', b'rank,team_handle\n"1,team-1')
        with self.assertRaisesMessage(BallotImportError, 'Malformed CSV'):
            parse_ballot_import(upload, self.teams)

    def test_json_parses_metadata_and_rationale(self):
        imported = parse_ballot_import(
            self._json(
                poll_type='computer',
                overall_rationale='Methodology',
                entries=[
                    {'rank': rank, 'team_handle': f'team-{rank}', 'rationale': 'Reason'}
                    for rank in range(1, 26)
                ],
            ),
            self.teams,
        )
        validate_entries(imported['entries'])
        self.assertEqual(imported['poll_type'], 2)
        self.assertTrue(imported['entries'][0]['rationale_supplied'])

    def test_invalid_poll_type_is_rejected(self):
        with self.assertRaisesMessage(BallotImportError, 'poll_type must be'):
            parse_ballot_import(self._json(poll_type='robot'), self.teams)

    def test_duplicate_rank_is_rejected(self):
        imported = parse_ballot_import(self._csv(), self.teams)
        imported['entries'][1]['rank'] = 1
        with self.assertRaisesMessage(BallotImportError, 'duplicate ranks'):
            validate_entries(imported['entries'])

    def test_unknown_team_is_rejected(self):
        upload = SimpleUploadedFile('ballot.csv', b'rank,team_handle\n1,unknown')
        with self.assertRaisesMessage(BallotImportError, 'unknown or ineligible'):
            parse_ballot_import(upload, self.teams)

    def test_malformed_json_is_rejected(self):
        with self.assertRaises(BallotImportError):
            parse_ballot_import(SimpleUploadedFile('ballot.json', b'{not json'), self.teams)


class BallotImportWorkflowTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        now = timezone.now()
        self.poll = Poll.objects.create(
            year=2026, week='Test', open_date=now - timedelta(days=1),
            close_date=now + timedelta(days=1), publish_date=now + timedelta(days=2),
            ap_date=now + timedelta(days=2),
        )
        self.auth_user = get_user_model().objects.create_user(username='importer', password='password')
        self.other_auth_user = get_user_model().objects.create_user(username='other', password='password')
        self.user = User.objects.create(username='importer')
        self.other_user = User.objects.create(username='other')
        UserRole.objects.create(
            user=self.user, role=UserRole.Role.VOTER, start_date=timezone.now() - timedelta(days=2),
        )
        UserRole.objects.create(
            user=self.other_user, role=UserRole.Role.VOTER, start_date=timezone.now() - timedelta(days=2),
        )
        self.teams = []
        for number in range(1, 27):
            self.teams.append(Team.objects.create(
                handle=f'team-{number}', name=f'Team {number}', short_name=f'T{number}',
                conference='Test', division='FBS', use_for_ballot=True,
            ))
        self.ineligible = Team.objects.create(
            handle='ineligible', name='Ineligible', short_name='INEL', conference='Test',
            division='FBS', use_for_ballot=False,
        )
        self.ballot = Ballot.objects.create(
            user=self.user, poll=self.poll, poll_type=Ballot.BallotType.HUMAN,
            user_type=UserRole.Role.VOTER, overall_rationale='Existing overall',
            submission_date=timezone.now() - timedelta(hours=1),
        )
        BallotEntry.objects.create(ballot=self.ballot, team=self.teams[0], rank=1, rationale='Keep me')
        BallotEntry.objects.create(ballot=self.ballot, team=self.teams[1], rank=2, rationale='Replace me')
        self.client.force_login(self.auth_user)

    def _csv(self, handles=None):
        handles = handles or [team.handle for team in self.teams[1:26]]
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['rank', 'team_handle'])
        writer.writerows((rank, handle) for rank, handle in enumerate(handles, 1))
        return SimpleUploadedFile('import.csv', output.getvalue().encode())

    def _json(self, entries=None, **fields):
        entries = entries or [
            {'rank': rank, 'team_handle': team.handle}
            for rank, team in enumerate(self.teams[1:26], 1)
        ]
        return SimpleUploadedFile('import.json', json.dumps({'entries': entries, **fields}).encode())

    def _post(self, upload, ballot=None):
        ballot = ballot or self.ballot
        return self.client.post(f'/ballot/import/{ballot.id}/', {'ballot-file': upload})

    def _snapshot(self):
        ballot = Ballot.objects.get(pk=self.ballot.pk)
        return (
            ballot.poll_type, ballot.overall_rationale, ballot.submission_date,
            list(BallotEntry.objects.filter(ballot=ballot).order_by('rank').values_list(
                'team__handle', 'rank', 'rationale'
            )),
        )

    def test_csv_import_replaces_entries_preserves_values_and_unsubmits(self):
        response = self._post(self._csv())
        self.assertEqual(response.status_code, 302)
        self.ballot.refresh_from_db()
        self.assertIsNone(self.ballot.submission_date)
        self.assertEqual(self.ballot.poll_type, Ballot.BallotType.HUMAN)
        self.assertEqual(self.ballot.overall_rationale, 'Existing overall')
        self.assertEqual(BallotEntry.objects.filter(ballot=self.ballot).count(), 25)
        retained = BallotEntry.objects.get(ballot=self.ballot, team=self.teams[1])
        self.assertEqual(retained.rank, 1)
        self.assertEqual(retained.rationale, 'Replace me')
        self.assertFalse(BallotEntry.objects.filter(ballot=self.ballot, team=self.teams[0]).exists())

    def test_json_import_overrides_metadata_and_rationales(self):
        entries = [
            {'rank': rank, 'team_handle': team.handle, **({'rationale': 'New reason'} if rank == 1 else {})}
            for rank, team in enumerate(self.teams[1:26], 1)
        ]
        response = self._post(self._json(entries, poll_type='computer', overall_rationale='New overall'))
        self.assertEqual(response.status_code, 302)
        self.ballot.refresh_from_db()
        self.assertEqual(self.ballot.poll_type, Ballot.BallotType.COMPUTER)
        self.assertEqual(self.ballot.overall_rationale, 'New overall')
        self.assertEqual(BallotEntry.objects.get(ballot=self.ballot, rank=1).rationale, 'New reason')
        self.assertEqual(BallotEntry.objects.get(ballot=self.ballot, rank=2).rationale, '')

    def test_json_omitted_optional_values_preserve_existing_rationale(self):
        response = self._post(self._json())
        self.assertEqual(response.status_code, 302)
        self.assertEqual(BallotEntry.objects.get(ballot=self.ballot, team=self.teams[1]).rationale, 'Replace me')
        self.assertEqual(BallotEntry.objects.get(ballot=self.ballot, team=self.teams[2]).rationale, '')
        self.ballot.refresh_from_db()
        self.assertEqual(self.ballot.overall_rationale, 'Existing overall')

    def test_json_empty_rationale_clears_existing_value_and_new_team_is_empty(self):
        entries = [
            {'rank': rank, 'team_handle': team.handle, 'rationale': '' if rank == 1 else 'x'}
            for rank, team in enumerate(self.teams[1:26], 1)
        ]
        self._post(self._json(entries))
        self.assertEqual(BallotEntry.objects.get(ballot=self.ballot, rank=1).rationale, '')
        self.assertEqual(BallotEntry.objects.get(ballot=self.ballot, rank=2).rationale, 'x')

    def test_invalid_import_is_atomic(self):
        before = self._snapshot()
        payload = json.loads(self._json().read())
        payload['entries'][0]['team_handle'] = 'unknown'
        self._post(SimpleUploadedFile('import.json', json.dumps(payload).encode()))
        self.assertEqual(self._snapshot(), before)

    def test_validation_errors_and_authorization(self):
        cases = [
            SimpleUploadedFile('bad.csv', b'rank,team_handle\n1,team-1'),
            SimpleUploadedFile('malformed.csv', b'rank,team_handle\n"1,team-1'),
            SimpleUploadedFile('bad.json', b'{bad'),
            SimpleUploadedFile('bad.txt', b'anything'),
            self._json(entries=[{'rank': 1, 'team_handle': 'team-1'}] * 25),
            self._json(entries=[{'team_handle': 'team-1'}] + [
                {'rank': rank, 'team_handle': f'team-{rank}'}
                for rank in range(2, 26)
            ]),
            self._json(entries=[{'rank': rank, 'team_handle': 'team-1'} for rank in range(1, 26)]),
            self._json(entries=[{'rank': rank, 'team_handle': self.ineligible.handle} for rank in range(1, 26)]),
            self._json(poll_type='invalid'),
            self._json(overall_rationale=3),
            self._json(entries=[{'rank': rank, 'team_handle': team.handle, 'rationale': 3} for rank, team in enumerate(self.teams[1:26], 1)]),
        ]
        before = self._snapshot()
        for upload in cases:
            response = self._post(upload)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(self._snapshot(), before)

    def test_other_user_closed_poll_and_unsupported_methods_are_forbidden(self):
        other_ballot = Ballot.objects.create(
            user=self.other_user, poll=self.poll, user_type=UserRole.Role.VOTER,
        )
        self.assertEqual(self._post(self._csv(), other_ballot).status_code, 403)
        self.client.logout()
        self.assertEqual(self._post(self._csv()).status_code, 403)
        self.client.force_login(self.auth_user)
        self.assertEqual(self.client.get(f'/ballot/import/{self.ballot.id}/').status_code, 400)
        self.poll.close_date = timezone.now() - timedelta(seconds=1)
        self.poll.save(update_fields=['close_date'])
        self.assertEqual(self._post(self._csv()).status_code, 403)

    def test_editor_help_exposes_examples_and_eligible_handles(self):
        response = self.client.get(f'/ballot/edit/{self.ballot.id}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Import ballot')
        self.assertContains(response, 'data-bs-target="#import-ballot-modal"')
        self.assertContains(response, 'id="import-ballot-form"')
        self.assertContains(response, 'data-bs-target="#import-help"')
        self.assertContains(response, 'rank,team_handle')
        self.assertContains(response, '"poll_type": "computer"')
        self.assertContains(response, '"team_handle": "example-handle"')
        self.assertContains(response, 'team-1')
        self.assertNotContains(response, 'Import CSV/JSON')
        self.assertNotContains(response, 'class="card mb-3"')
        self.assertNotContains(response, 'ineligible')
