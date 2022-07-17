from datetime import datetime
import pytz
from .models import ResultSet


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
