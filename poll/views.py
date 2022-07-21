from math import ceil

from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect
from django.utils import timezone

from .models import Ballot, BallotEntry, Poll, Team
from .utils import get_result_set, get_results_comparison


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
    print(years)
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

    entries = BallotEntry.objects.filter(ballot__poll=this_poll, team=this_team).order_by(
        'rank', 'ballot__user__username'
    )

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

    ballots = Ballot.objects.filter(poll=this_poll, submission_date__isnull=False).order_by('user__username')

    polls = Poll.objects.exclude(publish_date__gt=timezone.now()).order_by('-close_date')

    return render(request, 'voters_view.html', {
        'this_poll': this_poll,
        'ballots': ballots,
        'polls': polls
    })


def ballots_view(request, poll_id):
    this_poll = Poll.objects.get(pk=poll_id)

    if not this_poll.is_published and not request.user.is_staff:
        return HttpResponseForbidden()

    page = int(request.GET.get('page', "1"))
    user_type = int(request.GET.get('user_type', "1"))

    ballots = Ballot.objects.filter(poll=this_poll, user_type=user_type).order_by('user__username')
    ballot_count = ballots.count()
    this_page_ballots = ballots[(5 * (page - 1)):min(ballot_count, 5 * page)]

    ballot_entries = BallotEntry.objects.filter(ballot__in=this_page_ballots).order_by('ballot__user__username', 'rank')

    polls = Poll.objects.exclude(publish_date__gt=timezone.now()).order_by('-close_date')

    return render(request, 'ballots_view.html', {
        'this_poll': this_poll,
        'ballots': this_page_ballots,
        'ballot_entries': ballot_entries,
        'polls': polls,
        'user_type': user_type,
        'page': page,
        'pages': range(ceil(ballot_count / 5))
    })
