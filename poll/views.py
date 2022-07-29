from math import ceil

from django.db.models.functions import Lower
from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect
from django.utils import timezone

from .models import AboutPage, Ballot, BallotEntry, Poll, UserRole, Team
from .utils import get_outlier_analysis, get_result_set, get_results_comparison


def index(request):
    most_recent_poll = Poll.objects.filter(close_date__lt=timezone.now()).order_by('-close_date').first()

    results = get_results_comparison(most_recent_poll)

    top25 = [r for r in results if r['rank'] <= 25]
    others = [r for r in results if r['rank'] > 25]
    up_movers = sorted(results, key=lambda r: r['ppv_diff'], reverse=True)[0:5]
    down_movers = sorted(results, key=lambda r: r['ppv_diff'])[0:5]

    if most_recent_poll.last_week:
        lw_results = get_result_set(most_recent_poll.last_week)
        top25_teams = [team['team'] for team in top25]
        dropped = lw_results.filter(rank__lte=25).exclude(team__in=top25_teams)
    else:
        dropped = []

    return render(request, 'home.html', {
        'poll': most_recent_poll,
        'top25': top25,
        'others': others,
        'up_movers': up_movers,
        'down_movers': down_movers,
        'dropped': dropped
    })


def poll_index(request):
    polls = Poll.objects.exclude(publish_date__gt=timezone.now()).order_by('-close_date')
    polls_dict = polls.values()
    for poll in polls_dict:
        poll['top_team'] = get_result_set(polls.get(pk=poll['id'])).first().team
    years = polls.order_by('-year').values_list('year', flat=True).distinct()
    return render(request, 'poll_index.html', {'polls': polls_dict, 'years': years})


def poll_view(request, poll_id):
    poll = Poll.objects.get(pk=poll_id)

    if not poll.is_published and not request.user.is_staff:
        return HttpResponseForbidden()

    if len(request.GET) == 0:
        options = {
            'human': True,
            'computer': True,
            'hybrid': True,
            'main': True,
            'provisional': False,
            'before_ap': True,
            'after_ap': True
        }
        show_filters = False
    else:
        options = {
            'human': request.GET.get('human', None) is not None,
            'computer': request.GET.get('computer', None) is not None,
            'hybrid': request.GET.get('hybrid', None) is not None,
            'main': request.GET.get('main', None) is not None,
            'provisional': request.GET.get('provisional', None) is not None,
            'before_ap': request.GET.get('before_ap', None) is not None,
            'after_ap': request.GET.get('after_ap', None) is not None
        }
        show_filters = True

    results = get_results_comparison(poll, options)

    top25 = [r for r in results if r['rank'] <= 25]
    others = [r for r in results if r['rank'] > 25]
    up_movers = sorted(results, key=lambda r: r['ppv_diff'], reverse=True)[0:5]
    down_movers = sorted(results, key=lambda r: r['ppv_diff'])[0:5]

    if poll.last_week:
        lw_results = get_result_set(poll.last_week)
        top25_teams = [team['team'] for team in top25]
        dropped = lw_results.filter(rank__lte=25).exclude(team__in=top25_teams)
    else:
        dropped = []

    polls = Poll.objects.exclude(publish_date__gt=timezone.now()).order_by('-close_date')

    return render(request, 'poll_view.html', {
        'this_poll': poll,
        'options': options,
        'top25': top25,
        'others': others,
        'up_movers': up_movers,
        'down_movers': down_movers,
        'dropped': dropped,
        'polls': polls,
        'show_filters': show_filters
    })


def this_week(request):
    most_recent_poll = Poll.objects.filter(publish_date__lt=timezone.now()).order_by('-close_date').first()
    return redirect('/poll/view/%d/' % most_recent_poll.id)


def last_week(request):
    most_recent_poll = Poll.objects.filter(publish_date__lt=timezone.now()).order_by('-close_date').first()
    return redirect('/poll/view/%d/' % most_recent_poll.last_week.id)


def team_view(request, poll_id, team_id):
    this_poll = Poll.objects.get(pk=poll_id)
    this_team = Team.objects.get(pk=team_id)

    if not this_poll.is_published and not request.user.is_staff:
        return HttpResponseForbidden()

    entries = BallotEntry.objects.filter(
        ballot__poll=this_poll, team=this_team, ballot__submission_date__isnull=False
    ).order_by('rank', Lower('ballot__user__username'))

    polls = Poll.objects.exclude(publish_date__gt=timezone.now()).order_by('-close_date')
    teams = get_result_set(this_poll, set_options={'provisional': True}).only('team')

    return render(request, 'team_view.html', {
        'this_poll': this_poll,
        'this_team': this_team,
        'entries': entries,
        'polls': polls,
        'teams': teams
    })


def voters_view(request, poll_id):
    this_poll = Poll.objects.get(pk=poll_id)

    if not this_poll.is_published and not request.user.is_staff:
        return HttpResponseForbidden()

    ballots = Ballot.objects.filter(poll=this_poll, submission_date__isnull=False).order_by(Lower('user__username'))

    polls = Poll.objects.exclude(publish_date__gt=timezone.now()).order_by('-close_date')

    return render(request, 'voters_view.html', {
        'this_poll': this_poll,
        'ballots': ballots,
        'polls': polls
    })


def ballots_view(request, poll_id, user_type):
    this_poll = Poll.objects.get(pk=poll_id)

    if not this_poll.is_published and not request.user.is_staff:
        return HttpResponseForbidden()

    page = int(request.GET.get('page', "1"))

    ballots = Ballot.objects.filter(
        poll=this_poll, user_type=user_type, submission_date__isnull=False
    ).order_by(Lower('user__username'))
    ballot_count = ballots.count()
    this_page_ballots = ballots[(5 * (page - 1)):min(ballot_count, 5 * page)]

    ballot_entries = BallotEntry.objects.filter(ballot__in=this_page_ballots).order_by(Lower('ballot__user__username'))
    ballot_entries_pivot = {}
    for rank in range(1, 26):
        ballot_entries_pivot[rank] = ballot_entries.filter(rank=rank)

    polls = Poll.objects.exclude(publish_date__gt=timezone.now()).order_by('-close_date')

    return render(request, 'ballots_view.html', {
        'this_poll': this_poll,
        'ballots': this_page_ballots,
        'ballot_entries': ballot_entries_pivot,
        'polls': polls,
        'user_type': user_type,
        'previous_page': page - 1 if page > 1 else None,
        'next_page': page + 1 if page < ceil(ballot_count / 5) else None,
        'pages': range(1, ceil(ballot_count / 5) + 1)
    })


def analysis_view(request, poll_id):
    this_poll = Poll.objects.get(pk=poll_id)

    if not this_poll.is_published and not request.user.is_staff:
        return HttpResponseForbidden()

    include_provisional = request.GET.get('include_provisional', False)

    results = get_result_set(this_poll, {'provisional': include_provisional})

    ballots = Ballot.objects.filter(poll=this_poll, submission_date__isnull=False).order_by(Lower('user__username'))
    if not include_provisional:
        ballots = ballots.filter(user_type=1)

    ballot_analysis = []
    for ballot in ballots:
        ballot_analysis.append(get_outlier_analysis(ballot, results))

    polls = Poll.objects.exclude(publish_date__gt=timezone.now()).order_by('-close_date')

    most_unusual = sorted(ballot_analysis, key=lambda a: a['score'], reverse=True)[0:20]
    least_unusual = sorted(ballot_analysis, key=lambda a: a['score'])[0:20]

    most_disagreed = results.order_by('-std_dev')[0:10]

    return render(request, 'analysis_view.html', {
        'this_poll': this_poll,
        'include_provisional': include_provisional,
        'analysis': ballot_analysis,
        'most_unusual': most_unusual,
        'least_unusual': least_unusual,
        'most_disagreed': most_disagreed,
        'polls': polls
    })


def analysis_this_week(request):
    most_recent_poll = Poll.objects.filter(publish_date__lt=timezone.now()).order_by('-close_date').first()
    return redirect('/poll/analysis/%d/' % most_recent_poll.id)


def ballot_view(request, ballot_id):
    ballot = Ballot.objects.get(pk=ballot_id)

    if not ballot.poll.is_published and not request.user.is_staff and not ballot.user.username == request.user.username:
        return HttpResponseForbidden()

    entries = BallotEntry.objects.filter(ballot=ballot).order_by('rank')

    poll_results = get_result_set(ballot.poll)
    ballot_analysis = get_outlier_analysis(ballot, poll_results)

    return render(request, 'ballot_view.html', {
        'ballot': ballot,
        'entries': entries,
        'ballot_analysis': ballot_analysis
    })


def about(request):
    page = request.GET.get('p', "about")
    about = AboutPage.objects.get(page="about")
    process = AboutPage.objects.get(page="process")

    voter_roles = UserRole.objects.filter(role=1)
    voters = []
    for role in voter_roles:
        begin = role.start_date
        end = role.end_date
        if not end:
            end = timezone.now()
        num_years = int(((end - begin).days / 365.2425) + 0.5)
        if num_years > 0:
            voters.append({'username': role.user.username, 'years': num_years})

    voters = sorted(voters, key=lambda v: v['years'], reverse=True)
    years = {}
    for voter in voters:
        if voter['years'] in years:
            years[voter['years']].append(voter['username'])
        else:
            years[voter['years']] = [voter['username']]

    for year, voters in years.items():
        years[year] = sorted(voters, key=lambda v: v.lower())

    return render(request, 'about.html', {
        'page': page,
        'about': about,
        'process': process,
        'years': years
    })
