from types import SimpleNamespace

from django.template.loader import get_template
from django.test import SimpleTestCase


class PollViewTemplateTests(SimpleTestCase):
    def test_mobile_results_use_compact_table_with_secondary_stats_in_dropdown(self):
        team = SimpleNamespace(id=4, handle='test-team', name='Test Team')
        rank = SimpleNamespace(
            rank=1,
            baseline_diff=2,
            baseline_diff_str='+2',
            rank_diff=1,
            rank_diff_str='+1',
            team=team,
            points=100,
            points_per_voter=20,
            ppv_diff=0.5,
            std_dev=1.25,
            votes=5,
            first_place_votes=1,
        )
        user = SimpleNamespace(is_anonymous=False, is_staff=False, username='test-user')

        rendered = get_template('poll_view.html').render({
            'this_poll': SimpleNamespace(id=123),
            'polls': [],
            'show_filters': False,
            'options': {
                'main': True,
                'provisional': True,
                'human': True,
                'computer': True,
                'hybrid': True,
                'before_ap': True,
                'after_ap': True,
            },
            'top25': [rank],
            'dropped': None,
            'others': [],
            'user': user,
        })
        mobile_results = rendered.split('<section class="poll-results-mobile', 1)[1].split('</section>', 1)[0]

        self.assertIn('class="table-responsive py-3 d-none d-md-block"', rendered)
        self.assertIn('class="poll-results-mobile d-md-none py-3"', rendered)
        self.assertIn('class="table table-sm table-striped table-bordered poll-results-mobile-table"', mobile_results)
        for label in ('Rank', 'Team', 'Change', 'Points', '#1'):
            self.assertIn(f'scope="col">{label}</th>', mobile_results)
        self.assertIn('aria-label="More stats for Test Team"', mobile_results)
        self.assertIn('<td class="text-center text-success">+1</td>', mobile_results)
        self.assertIn('<td class="text-center">100</td>', mobile_results)
        self.assertIn('<td class="text-center">1</td>', mobile_results)
        for label in ('Baseline change', 'PPV', 'Δ PPV', 'σ', '# Votes'):
            self.assertIn(f'<dt>{label}</dt>', mobile_results)
        for value in (
            '<dd class="text-success">+2</dd>',
            '<dd>20.00</dd>',
            '<dd class="text-success">+0.50</dd>',
            '<dd>1.25</dd>',
            '<dd>5</dd>',
        ):
            self.assertIn(value, mobile_results)
