from datetime import datetime
import pytz

from .models import ResultSet

MIN_OUTLIER_FACTOR = 1


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
        if last_week and last_week.filter(team=result.team).exists():
            lw_result = last_week.get(team=result.team)
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
            baseline_result = baseline.get(team=result.team)
            this_comparison['baseline_diff'] = baseline_diff = baseline_result.rank - result.rank
            this_comparison['baseline_diff_str'] = (
                '+%d' % baseline_diff if baseline_diff > 0 else
                '%d' % baseline_diff if baseline_diff < 0 else
                ''
            )
        else:
            this_comparison['baseline_diff'] = 0
            this_comparison['baseline_diff_str'] = ''
        results.append(this_comparison)
    return results


def get_outlier_analysis(ballot, results):
    ballot_entries = ballot.get_entries()

    total_score = 0
    ranks = []
    teams_ranked = []
    for entry in ballot_entries:
        result = results.get(team=entry.team)
        score = max(0, (abs(26 - entry.rank - result.points_per_voter) / max(MIN_OUTLIER_FACTOR, result.std_dev)) - 0.5)
        ranks.append((entry.team, score))
        total_score += score
        teams_ranked.append(entry.team)

    omissions = []
    for rank in range(1, 26):
        result = results.get(rank=rank)
        if result.team not in teams_ranked:
            score = max(0, (result.points_per_voter / max(MIN_OUTLIER_FACTOR, result.std_dev)) - 0.5)
            if score > 0:
                omissions.append((result.team, score))
                total_score += score

    return {
        'ballot': ballot,
        'ranks': ranks,
        'omissions': omissions,
        'score': total_score
    }
