from math import ceil
import requests
from urllib.parse import unquote

from django.contrib.auth import logout as auth_logout
from django.db.models.functions import Lower
from django.http import HttpResponseForbidden, HttpResponseBadRequest, StreamingHttpResponse
from django.shortcuts import render, redirect
from django.utils import timezone

from .models import AboutPage, Ballot, BallotEntry, Poll, ProvisionalUserApplication, User, UserRole, Team
from .utils import check_for_errors, check_for_warnings, get_outlier_analysis, get_result_set, get_results_comparison


def index(request):
    most_recent_poll = Poll.objects.filter(publish_date__lt=timezone.now()).order_by('-close_date').first()

    results = get_results_comparison(most_recent_poll)

    display_lists = _get_results_display_lists(most_recent_poll, results)

    return render(request, 'home.html', {
        'poll': most_recent_poll,
        'top25': display_lists['top25'],
        'others': display_lists['others'],
        'up_movers': display_lists['up_movers'],
        'down_movers': display_lists['down_movers'],
        'dropped': display_lists['dropped']
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
            'after_ap': request.GET.get('after_ap', None) is not None,
            'show_distribution': request.GET.get('show_distribution', 'off') != 'off',
            'show_all': request.GET.get('show_all', 'off') != 'off',
        }
        show_filters = True

    results = get_results_comparison(poll, options)
    for result in results:
        _assign_distribution_classes(result)

    display_lists = _get_results_display_lists(poll, results)

    polls = Poll.objects.exclude(publish_date__gt=timezone.now()).order_by('-close_date')

    return render(request, 'poll_view.html', {
        'this_poll': poll,
        'options': options,
        'top25': results if options.get('show_all', False) else display_lists['top25'],
        'others': display_lists['others'],
        'up_movers': display_lists['up_movers'],
        'down_movers': display_lists['down_movers'],
        'dropped': display_lists['dropped'],
        'polls': polls,
        'rank_list': list(range(1, 26)) + ['NR'],
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
    results_dict, top25 = _prep_result_set_for_analysis(results)
    for ballot in ballots:
        ballot_analysis.append(get_outlier_analysis(ballot, results_dict, top25))

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
    results_dict, top25 = _prep_result_set_for_analysis(poll_results)
    ballot_analysis = get_outlier_analysis(ballot, results_dict, top25)
    ballot_analysis['ranks'] = [
        (rank[0], Team.objects.get(pk=rank[1]), rank[2], rank[3]) for rank in ballot_analysis['ranks']
    ]
    ballot_analysis['omissions'] = [
        (Team.objects.get(pk=omission[0]), omission[1], omission[2]) for omission in ballot_analysis['omissions']
    ]

    return render(request, 'ballot_view.html', {
        'ballot': ballot,
        'entries': entries,
        'ballot_analysis': ballot_analysis
    })


def about(request):
    page = request.GET.get('p', "about")
    about_text = AboutPage.objects.get(page="about")
    faq = AboutPage.objects.get(page="faq")
    contribute = AboutPage.objects.get(page="contribute")

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
        'about': about_text,
        'faq': faq,
        'contribute': contribute,
        'years': years
    })


def poll_post(request):
    if not request.user.is_staff:
        return HttpResponseForbidden()

    poll = Poll.objects.filter(close_date__lt=timezone.now()).order_by('-close_date').first()
    results = get_results_comparison(poll)
    display_lists = _get_results_display_lists(poll, results)

    links = {
        'results': request.build_absolute_uri('/poll/view/%d/' % poll.id),
        'provisional': request.build_absolute_uri(
            '/poll/view/%d/?main=on&provisional=on&human=on&computer=on&hybrid=on&before_ap=on&after_ap=on' % poll.id
        ),
        'voters': request.build_absolute_uri('/poll/voters/%d/' % poll.id),
        'ballots': request.build_absolute_uri('/poll/ballots/%d/' % poll.id),
        'analysis': request.build_absolute_uri('/poll/analysis/%d/' % poll.id),
        'about': request.build_absolute_uri('/about/?p=about'),
        'faq': request.build_absolute_uri('/about/?p=faq'),
        'contribute': request.build_absolute_uri('/about/?p=contribute'),
        'hall': request.build_absolute_uri('/about/?p=voters'),
    }

    return render(request, 'poll_post.html', {
        'poll': poll,
        'top25': display_lists['top25'],
        'next_ten': display_lists['others'][0:10],
        'dropped': display_lists['dropped'],
        'links': links
    })


def _get_results_display_lists(poll, results):
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

    return {
        'top25': top25,
        'others': others,
        'up_movers': up_movers,
        'down_movers': down_movers,
        'dropped': dropped
    }


def my_ballots(request):
    if not request.user.is_authenticated:
        return redirect('/login/')

    this_user = User.objects.get(username=request.user.username)
    is_provisional = this_user.is_provisional_voter

    if not this_user.is_voter and not this_user.is_provisional_voter:
        app = ProvisionalUserApplication.objects.filter(user=this_user).order_by('-submission_date').first()
        if (
            app and app.status == ProvisionalUserApplication.Status.REJECTED
            and (timezone.now() - app.submission_date).days > 180
        ):
            app = None
        return render(request, 'not_a_voter.html', {
            'this_user': this_user,
            'app': app
        })

    open_polls = []
    open_poll_objects = Poll.objects.filter(
        open_date__lt=timezone.now(), close_date__gt=timezone.now()
    ).order_by('-publish_date')
    for poll in open_poll_objects:
        open_polls.append({
            'poll': poll,
            'ballot': Ballot.objects.filter(user=this_user, poll=poll).first()
        })

    closed_ballots = Ballot.objects.filter(
        user=this_user, poll__close_date__lte=timezone.now()
    ).order_by('-poll__publish_date')

    return render(request, 'my_ballots.html', {
        'this_user': this_user,
        'is_provisional': is_provisional,
        'open_polls': open_polls,
        'closed_ballots': closed_ballots
    })


def apply_for_provisional(request):
    if not request.user.is_authenticated:
        return redirect('/login/')

    this_user = User.objects.get(username=request.user.username)

    if this_user.is_voter or this_user.is_provisional_voter:
        return redirect('/my_ballots/')

    app = ProvisionalUserApplication.objects.filter(user=this_user).order_by('-submission_date').first()
    if app and (
            app.status != ProvisionalUserApplication.Status.REJECTED
            or (timezone.now() - app.submission_date).days <= 180
    ):
        return redirect('/my_ballots/')

    new_app = ProvisionalUserApplication(
        user=this_user, submission_date=timezone.now(), status=ProvisionalUserApplication.Status.OPEN
    )
    new_app.save()
    return redirect('/my_ballots/')


def create_ballot(request, poll_id):
    poll = Poll.objects.get(pk=poll_id)

    if not request.user.is_authenticated or not poll.is_open:
        return HttpResponseForbidden()

    this_user = User.objects.get(username=request.user.username)

    if not this_user.is_voter and not this_user.is_provisional_voter:
        return HttpResponseForbidden()

    ballot = Ballot.objects.filter(poll=poll, user=this_user).first()
    if ballot:
        return redirect('/ballot/edit/%d/' % ballot.id)

    ballot = Ballot(
        user=this_user,
        poll=poll,
        user_type=UserRole.Role.VOTER if this_user.is_voter else UserRole.Role.PROVISIONAL
    )
    ballot.save()
    return redirect('/ballot/edit/%d/' % ballot.id)


def edit_ballot(request, ballot_id):
    ballot = Ballot.objects.get(pk=ballot_id)

    if not ballot.poll.is_open or not ballot.user.username == request.user.username:
        return HttpResponseForbidden()

    if ballot.submission_date:
        ballot.submission_date = None
        ballot.save()

    entries = BallotEntry.objects.filter(ballot=ballot).order_by('rank')

    page = request.GET.get('p', "teams")

    if page == "reasons":
        return render(request, 'edit_reasons.html', {
            'ballot': ballot,
            'entries': entries
        })
    else:
        teams = Team.objects.filter(use_for_ballot=True).order_by('name')
        conferences = list(
            teams.filter(division='FBS').values_list('conference', flat=True).distinct().order_by('conference')
        )

        team_groups = {}
        for conference in conferences:
            team_groups[conference] = []
        team_groups['Others'] = []

        team_dict = {}

        for team in teams:
            if team.conference in conferences:
                team_groups[team.conference].append(team)
            else:
                team_groups['Others'].append(team)
            team_dict[team.handle] = {
                'name': team.name,
                'short_name': team.short_name
            }

        return render(request, 'edit_ballot.html', {
            'ballot': ballot,
            'entries': entries,
            'teams': team_dict,
            'team_groups': team_groups,
            'ranks': range(1, 26)
        })


def save_teams(request, ballot_id):
    ballot = Ballot.objects.get(pk=ballot_id)

    if not ballot.poll.is_open or not ballot.user.username == request.user.username:
        return HttpResponseForbidden()

    page = request.POST['page']
    poll_type = int(request.POST['poll-type']) if request.POST['poll-type'] != '' else ''
    overall_rationale = unquote(request.POST['overall-rationale'])
    entries = []
    for i in range(1, 26):
        team_handle = request.POST['rank-%d' % i]
        if team_handle != '':
            entries.append(team_handle)
        else:
            break

    if poll_type in Ballot.BallotType:
        ballot.poll_type = poll_type
    ballot.overall_rationale = overall_rationale
    ballot.save()

    new_entries = []
    for i, entry in enumerate(entries):
        ballot_entry = BallotEntry.objects.filter(ballot=ballot, team=Team.objects.get(handle=entry)).first()
        if ballot_entry:
            ballot_entry.rank = i + 1
        else:
            ballot_entry = BallotEntry(
                ballot=ballot,
                team=Team.objects.get(handle=entry),
                rank=i + 1
            )
        ballot_entry.save()
        new_entries.append(ballot_entry)
    BallotEntry.objects.filter(ballot=ballot).exclude(id__in=[entry.id for entry in new_entries]).delete()

    if page == 'validate':
        return redirect('/ballot/validate/%d/' % ballot.id)
    elif page == 'reasons':
        return redirect('/ballot/edit/%d/?p=reasons' % ballot.id)
    else:
        return redirect('/ballot/edit/%d/' % ballot.id)


def save_reasons(request, ballot_id):
    ballot = Ballot.objects.get(pk=ballot_id)

    if not ballot.poll.is_open or not ballot.user.username == request.user.username:
        return HttpResponseForbidden()

    page = request.POST['page']
    poll_type = request.POST['poll-type']
    overall_rationale = unquote(request.POST['overall-rationale'])
    reasons = []
    for i in range(1, 26):
        if 'rationale-%d' % i in request.POST.keys():
            reasons.append(request.POST['rationale-%d' % i])
        else:
            break

    if poll_type in Ballot.BallotType:
        ballot.poll_type = poll_type
    ballot.overall_rationale = overall_rationale
    ballot.save()

    for i, reason in enumerate(reasons):
        ballot_entry = BallotEntry.objects.filter(ballot=ballot, rank=i + 1).first()
        if ballot_entry:
            ballot_entry.rationale = reason
            ballot_entry.save()
        else:
            return HttpResponseBadRequest()

    if page == 'validate':
        return redirect('/ballot/validate/%d/' % ballot.id)
    elif page == 'reasons':
        return redirect('/ballot/edit/%d/?p=reasons' % ballot.id)
    else:
        return redirect('/ballot/edit/%d/' % ballot.id)


def validate_ballot(request, ballot_id):
    ballot = Ballot.objects.get(pk=ballot_id)

    if not ballot.poll.is_open or not ballot.user.username == request.user.username:
        return HttpResponseForbidden()

    entries = BallotEntry.objects.filter(ballot=ballot).order_by('rank')

    errors = check_for_errors(ballot)
    warnings = check_for_warnings(ballot)

    return render(request, 'validate_ballot.html', {
        'ballot': ballot,
        'entries': entries,
        'errors': errors,
        'warnings': warnings
    })


def submit_ballot(request, ballot_id):
    ballot = Ballot.objects.get(pk=ballot_id)

    if not ballot.poll.is_open or not ballot.user.username == request.user.username:
        return HttpResponseForbidden()

    errors = check_for_errors(ballot)

    if errors:
        return redirect('/ballot/validate/%d/' % ballot.id)
    else:
        ballot.submission_date = timezone.now()
        ballot.save()

    return redirect('/my_ballots/')


def logout(request):
    auth_logout(request)
    return redirect('/')


def current_voters(request):
    if not request.user.is_staff:
        return HttpResponseForbidden()

    p = request.GET.get('p', None)

    polls = Poll.objects.filter(close_date__gt=timezone.now())

    main_voters = UserRole.objects.filter(role=UserRole.Role.VOTER, end_date__isnull=True)
    provisional_voters = UserRole.objects.filter(role=UserRole.Role.PROVISIONAL, end_date__isnull=True)

    if p:
        this_poll = Poll.objects.get(id=p)
        voted = Ballot.objects.filter(poll=this_poll, submission_date__isnull=False).values_list('user')
        main_voters = main_voters.exclude(user__in=voted)
        provisional_voters = provisional_voters.exclude(user__in=voted)

    main_voters = main_voters.values_list('user__username', flat=True).order_by(Lower('user__username'))
    provisional_voters = provisional_voters.values_list('user__username', flat=True).order_by(Lower('user__username'))

    return render(request, 'voter_list.html', {
        'polls': polls,
        'main_voters': main_voters,
        'provisional_voters': provisional_voters
    })


def _prep_result_set_for_analysis(results):
    results_list = list(results)
    results_dict = {result.team_id: {
        'ppv': result.points_per_voter, 'std_dev': result.std_dev, 'rank': result.rank,
        'votes': result.ranks
    } for result in results_list}
    top25 = {team_id: result for (team_id, result) in results_dict.items() if result['rank'] <= 25}
    return results_dict, top25


def _assign_distribution_classes(result):
    max_votes = max(result['ranks'])
    result['classes'] = [('dist-matches' if i+1 == result['rank'] else
                       'dist-most' if n == max_votes else
                       'dist-only' if n == 1 else
                       'dist-none' if n == 0 else None
                       )for i, n in enumerate(result['ranks'])]
    result['rank_class'] = zip(result['ranks'], result['classes'])


def fcs(request):
    url = 'https://www.redditcfb.com/fcstop25.txt'
    response = requests.get(url, stream=True)
    return StreamingHttpResponse(
        response.raw,
        content_type=response.headers.get('content-type'),
        status=response.status_code,
        reason=response.reason
    )
