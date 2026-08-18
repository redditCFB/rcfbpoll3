import csv
import io
import json


POLL_TYPE_VALUES = {'human': 1, 'computer': 2, 'hybrid': 3}


class BallotImportError(ValueError):
    pass


def parse_ballot_import(uploaded_file, teams):
    filename = (uploaded_file.name or '').lower()
    if filename.endswith('.csv'):
        return _parse_csv(uploaded_file.read(), teams)
    if filename.endswith('.json'):
        return _parse_json(uploaded_file.read(), teams)
    raise BallotImportError('Unsupported file type. Upload a UTF-8 .csv or .json file.')


def _decode(contents):
    try:
        return contents.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise BallotImportError('The file must be encoded as UTF-8.') from exc


def _parse_csv(contents, teams):
    try:
        reader = csv.DictReader(io.StringIO(_decode(contents), newline=''), strict=True)
        if reader.fieldnames != ['rank', 'team_handle']:
            raise BallotImportError('CSV must have exactly these columns: rank, team_handle.')
        entries = []
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise BallotImportError(f'CSV row {row_number} has too many columns.')
            entries.append(_entry(row.get('rank'), row.get('team_handle'), row_number, teams))
    except csv.Error as exc:
        raise BallotImportError(f'Malformed CSV: {exc}.') from exc
    return {'entries': entries, 'poll_type_supplied': False,
            'overall_rationale_supplied': False}


def _parse_json(contents, teams):
    try:
        payload = json.loads(_decode(contents))
    except json.JSONDecodeError as exc:
        raise BallotImportError(f'Malformed JSON: {exc}.') from exc
    if not isinstance(payload, dict):
        raise BallotImportError('JSON must contain one ballot object.')
    if not isinstance(payload.get('entries'), list):
        raise BallotImportError('JSON must contain an entries array.')

    poll_type_supplied = 'poll_type' in payload
    if poll_type_supplied and payload['poll_type'] not in POLL_TYPE_VALUES:
        raise BallotImportError('poll_type must be human, computer, or hybrid.')
    overall_rationale_supplied = 'overall_rationale' in payload
    if overall_rationale_supplied and not isinstance(payload['overall_rationale'], str):
        raise BallotImportError('overall_rationale must be a string.')

    entries = []
    for number, raw_entry in enumerate(payload['entries'], start=1):
        if not isinstance(raw_entry, dict):
            raise BallotImportError(f'JSON entry {number} must be an object.')
        for field in ('rank', 'team_handle'):
            if field not in raw_entry:
                raise BallotImportError(f'JSON entry {number} is missing {field}.')
        if 'rationale' in raw_entry and not isinstance(raw_entry['rationale'], str):
            raise BallotImportError(f'JSON entry {number} rationale must be a string.')
        entry = _entry(raw_entry['rank'], raw_entry['team_handle'], number, teams, strict_integer=True)
        entry['rationale_supplied'] = 'rationale' in raw_entry
        if entry['rationale_supplied']:
            entry['rationale'] = raw_entry['rationale']
        entries.append(entry)

    return {
        'entries': entries,
        'poll_type': POLL_TYPE_VALUES.get(payload.get('poll_type')),
        'overall_rationale': payload.get('overall_rationale'),
        'poll_type_supplied': poll_type_supplied,
        'overall_rationale_supplied': overall_rationale_supplied,
    }


def _entry(rank, handle, row_number, teams, strict_integer=False):
    if strict_integer:
        if not isinstance(rank, int) or isinstance(rank, bool):
            raise BallotImportError(f'Row {row_number} rank must be an integer.')
    else:
        try:
            rank = int(rank)
        except (TypeError, ValueError) as exc:
            raise BallotImportError(f'Row {row_number} rank must be an integer.') from exc
    if not isinstance(handle, str) or not handle:
        raise BallotImportError(f'Row {row_number} is missing team_handle.')
    if rank < 1 or rank > 25:
        raise BallotImportError(f'Row {row_number} rank {rank} is out of range; use 1 through 25.')
    team = teams.get(handle)
    if team is None:
        raise BallotImportError(f'Row {row_number} has unknown or ineligible team_handle {handle!r}.')
    return {'rank': rank, 'team': team, 'rationale': '', 'rationale_supplied': False}


def validate_entries(entries):
    if len(entries) != 25:
        raise BallotImportError(f'Import must contain exactly 25 entries; found {len(entries)}.')
    ranks = [entry['rank'] for entry in entries]
    if len(set(ranks)) != len(ranks):
        raise BallotImportError('Import contains duplicate ranks.')
    if set(ranks) != set(range(1, 26)):
        raise BallotImportError('Import must contain every rank from 1 through 25 exactly once.')
    handles = [entry['team'].handle for entry in entries]
    if len(set(handles)) != len(handles):
        raise BallotImportError('Import contains duplicate teams.')
