from datetime import datetime
from math import ceil
import pytz

from django.utils import timezone

from .models import Ballot, BallotEntry, ResultSet, UserRole, User

MIN_OUTLIER_FACTOR = 1
SCORE_OFFSET = 0.75


def get_result_set(poll, set_options=None):
    options = {
        'human': True,
        'computer': True,
        'hybrid': True,
        'main': True,
        'provisional': False,
        'before_ap': True,
        'after_ap': True
    }
    if set_options:
        options.update(set_options)

    result_set = ResultSet.objects.filter(
        poll=poll,
        human=options['human'],
        computer=options['computer'],
        hybrid=options['hybrid'],
        main=options['main'],
        provisional=options['provisional'],
        before_ap=options['before_ap'],
        after_ap=options['after_ap']
    ).first()

    if result_set:
        if result_set.needs_update():
            results = result_set.update()
        else:
            results = result_set.results()
    else:
        results = _create_result_set(poll, options)

    return results


def _create_result_set(poll, options):
    dt_min = datetime.min
    result_set = ResultSet(
        poll=poll,
        time_calculated=dt_min.replace(tzinfo=pytz.UTC),
        human=options['human'],
        computer=options['computer'],
        hybrid=options['hybrid'],
        main=options['main'],
        provisional=options['provisional'],
        before_ap=options['before_ap'],
        after_ap=options['after_ap']
    )
    result_set.save()
    return result_set.update()


def get_results_comparison(poll, set_options=None):
    this_week = get_result_set(poll, set_options)
    if set_options:
        baseline = get_result_set(poll)
    else:
        baseline = None
    results = []
    last_week = None
    if poll.last_week:
        last_week = get_result_set(poll.last_week, set_options)
    for result in this_week:
        this_comparison = {
            'team': result.team,
            'rank': result.rank,
            'first_place_votes': result.first_place_votes,
            'points': result.points,
            'points_per_voter': result.points_per_voter,
            'std_dev': result.std_dev,
            'votes': result.votes
        }
        lw_result = last_week.filter(team_id=result.team_id).first() if last_week else None
        if lw_result:
            this_comparison['rank_diff'] = rank_diff = lw_result.rank - result.rank
            this_comparison['rank_diff_str'] = (
                'NEW' if lw_result.rank > 25 else
                '+%d' % rank_diff if rank_diff > 0 else
                '%d' % rank_diff if rank_diff < 0 else
                '--'
            )
            this_comparison['ppv_diff'] = result.points_per_voter - lw_result.points_per_voter
        else:
            this_comparison['rank_diff'] = 0
            this_comparison['rank_diff_str'] = 'NEW'
            this_comparison['ppv_diff'] = result.points_per_voter
        if baseline:
            baseline_result = baseline.filter(team_id=result.team_id).first()
            if baseline_result:
                this_comparison['baseline_diff'] = baseline_diff = baseline_result.rank - result.rank
                this_comparison['baseline_diff_str'] = (
                    '+%d' % baseline_diff if baseline_diff > 0 else
                    '%d' % baseline_diff if baseline_diff < 0 else
                    ''
                )
            else:
                this_comparison['baseline_diff'] = 1
                this_comparison['baseline_diff_str'] = 'NEW'
        else:
            this_comparison['baseline_diff'] = 0
            this_comparison['baseline_diff_str'] = ''
        results.append(this_comparison)
    return results


def get_outlier_analysis(ballot, results_dict, top25):
    ballot_entries = ballot.get_entries()

    total_score = 0
    ranks = []
    teams_ranked = []
    for entry in ballot_entries:
        if entry.team_id in results_dict:
            result = results_dict[entry.team_id]
            score = (26 - entry.rank - result['ppv']) / max(MIN_OUTLIER_FACTOR, result['std_dev'])
            if score > 0:
                score = max(0, score - SCORE_OFFSET)
            else:
                score = min(0, score + SCORE_OFFSET)
        else:
            score = (26 - entry.rank) / MIN_OUTLIER_FACTOR - SCORE_OFFSET
        ranks.append((entry.rank, entry.team_id, score, _get_bg_color(score)))
        total_score += abs(score)
        teams_ranked.append(entry.team_id)

    omissions = []
    for team_id, result in top25.items():
        if team_id not in teams_ranked:
            score = max(0, (result['ppv'] / max(MIN_OUTLIER_FACTOR, result['std_dev'])) - SCORE_OFFSET)
            if score > 0:
                omissions.append((team_id, score, _get_bg_color(score * -1)))
                total_score += score

    return {
        'ballot': ballot,
        'ranks': ranks,
        'omissions': omissions,
        'score': total_score
    }


def _get_bg_color(score):
    if abs(score) >= 4.0:
        color_value = 0
    else:
        color_value = ceil((1 - min(abs(score) / 4.0, 1)) * 256) - 1
    if score > 0:
        color = '#%02xff%02x' % (color_value, color_value)
    else:
        color = '#ff%02x%02x' % (color_value, color_value)

    return color


def check_for_errors(ballot):
    errors = []

    entries = BallotEntry.objects.filter(ballot=ballot)
    if len(entries) < 25:
        errors.append('Too few entries.')
    if len(entries) > 25:
        errors.append('Too many entries.')

    if not ballot.poll_type:
        errors.append('Missing poll type.')

    for entry in entries:
        if not entry.team.use_for_ballot:
            errors.append('%s not a valid team option.' % entry.team.short_name)

    return errors


def check_for_warnings(ballot):
    warnings = []

    entries = BallotEntry.objects.filter(ballot=ballot).order_by('rank')

    lw_poll_results = get_result_set(ballot.poll.last_week)
    lw_user_ballot = Ballot.objects.filter(poll=ballot.poll.last_week, user=ballot.user).first()

    for entry in entries[:20]:
        if not lw_poll_results.filter(team=entry.team, rank__lte=30).exists():
            warnings.append("Ranked team in top 20 who wasn't in top 30 last week: %s" % entry.team.short_name)
    for result in lw_poll_results[:15]:
        if not entries.filter(team=result.team).exists():
            warnings.append("Missing team from last week's top 15: %s" % result.team.short_name)
    if lw_user_ballot:
        lw_entries = BallotEntry.objects.filter(ballot=lw_user_ballot).order_by('rank')
        for entry in lw_entries[:20]:
            if not entries.filter(team=entry.team).exists():
                warnings.append("Missing team from your top 20 last week: %s" % entry.team.short_name)
    ballot_count = Ballot.objects.filter(
        poll=ballot.poll, submission_date__isnull=False, user_type=UserRole.Role.VOTER
    ).count()
    if ballot_count >= 10:
        for entry in entries:
            entry_count = BallotEntry.objects.filter(
                ballot__poll=ballot.poll,
                ballot__submission_date__isnull=False,
                ballot__user_type=UserRole.Role.VOTER,
                team=entry.team
            ).count()
            if entry_count / ballot_count < 0.1:
                warnings.append("Team on less than 10% of other ballots: " + entry.team.short_name)

    return warnings


def promote_voters(voter_names):
    voters = User.objects.filter(username__in=voter_names)
    UserRole.objects.filter(role=UserRole.Role.PROVISIONAL, user__in=voters).update(end_date=timezone.now())
    UserRole.objects.bulk_create([
        UserRole(user=voter, role=UserRole.Role.VOTER, start_date=timezone.now()) for voter in voters
    ])
    Ballot.objects.filter(
        poll__open_date__lt=timezone.now(), poll__close_date__gt=timezone.now(), user__in=voters
    ).update(user_type=UserRole.Role.VOTER)
