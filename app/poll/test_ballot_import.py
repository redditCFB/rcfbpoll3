import json
from types import SimpleNamespace

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from .ballot_import import BallotImportError, parse_ballot_import, validate_entries


class BallotImportParserTests(SimpleTestCase):
    def setUp(self):
        self.teams = {
            f'team-{number}': SimpleNamespace(handle=f'team-{number}', id=number)
            for number in range(1, 26)
        }

    def _csv(self):
        rows = ['rank,team_handle'] + [
            f'{rank},team-{rank}' for rank in range(1, 26)
        ]
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
        self.assertFalse(imported['poll_type_supplied'])

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
        self.assertEqual(imported['overall_rationale'], 'Methodology')
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
        upload = SimpleUploadedFile(
            'ballot.csv',
            ('rank,team_handle\n1,unknown').encode(),
        )
        with self.assertRaisesMessage(BallotImportError, 'unknown or ineligible'):
            parse_ballot_import(upload, self.teams)

    def test_malformed_json_is_rejected(self):
        upload = SimpleUploadedFile('ballot.json', b'{not json')
        with self.assertRaises(BallotImportError):
            parse_ballot_import(upload, self.teams)
