from django.shortcuts import render
from django.utils import timezone

from .models import Poll
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
