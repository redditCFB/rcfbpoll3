from types import SimpleNamespace

from django.template.loader import get_template
from django.test import SimpleTestCase


class PollViewTemplateTests(SimpleTestCase):
    def test_mobile_results_show_all_table_values_in_labeled_cards(self):
        team = SimpleNamespace(id=4, handle='test-team', name='Test Team')
        rank = SimpleNamespace(
            rank=1,
            baseline_diff=2,
            baseline_diff_str='+2',
            rank_diff=0,
            rank_diff_str='--',
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
        self.assertIn('poll-result-mobile-card', mobile_results)
        for label in ('Change', 'Points', 'PPV', 'Δ PPV', 'σ', '# Votes', '#1 Votes'):
            self.assertIn(f'<dt>{label}</dt>', mobile_results)
        for value in (
            '<dd>--</dd>',
            '<dd>100</dd>',
            '<dd>20.00</dd>',
            '<dd class="text-success">+0.50</dd>',
            '<dd>1.25</dd>',
            '<dd>5</dd>',
            '<dd>1</dd>',
        ):
            self.assertIn(value, mobile_results)
