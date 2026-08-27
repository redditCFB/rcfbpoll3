from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from poll import views


class FakeResults:
    def __init__(self, results):
        self.results = results

    def __iter__(self):
        return iter(self.results)

    def __getitem__(self, item):
        return self.results[item]

    def order_by(self, *args):
        return self


class FakeBallots:
    def order_by(self, *args):
        return self

    def filter(self, **kwargs):
        return self

    def __iter__(self):
        return iter([])


class AnalysisBeeswarmDataTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.poll = SimpleNamespace(is_published=True, ap_date=None, id=1)
        self.results = FakeResults([
            SimpleNamespace(
                rank=index,
                team=SimpleNamespace(name='Team %d' % index, handle='team-%d' % index),
                points_per_voter=20.123456 + index,
                std_dev=1,
            )
            for index in range(1, 36)
        ])

    def run_view(self, query='', result_set_side_effect=None):
        request = self.factory.get('/poll/analysis/1/' + query)
        request.user = SimpleNamespace(is_staff=False)
        rendered = {}

        def capture_render(request, template, context):
            rendered['context'] = context
            return rendered

        result_set = patch.object(
            views, 'get_result_set',
            side_effect=result_set_side_effect,
            return_value=self.results,
        )
        with patch.object(views.Poll.objects, 'get', return_value=self.poll), \
             patch.object(views.Poll.objects, 'exclude', return_value=FakeBallots()), \
             patch.object(views.Ballot.objects, 'filter', return_value=FakeBallots()), \
             patch.object(views, '_prep_result_set_for_analysis', return_value=({}, [])), \
             patch.object(views, 'render', side_effect=capture_render) as render, \
             result_set:
            views.analysis_view(request, 1)

        render.assert_called_once()
        return rendered['context']

    def test_chart_uses_first_30_canonical_results_without_rounding(self):
        context = self.run_view()
        chart = context['chart_results']

        self.assertEqual(len(chart), 30)
        self.assertEqual(chart[0], {
            'rank': 1,
            'team_name': 'Team 1',
            'team_handle': 'team-1',
            'points_per_voter': 21.123456,
        })
        self.assertEqual(chart[-1]['rank'], 30)

    def test_chart_uses_main_and_provisional_result_set_selection(self):
        selected_options = []

        def get_results(poll, options):
            selected_options.append(options)
            return self.results

        self.run_view(result_set_side_effect=get_results)
        self.run_view('?include_provisional=True', result_set_side_effect=get_results)

        self.assertEqual(selected_options, [
            {'provisional': False},
            {'provisional': 'True'},
        ])

    def test_fewer_than_30_results_are_supported(self):
        self.results = FakeResults(self.results.results[:4])
        context = self.run_view()

        self.assertEqual(len(context['chart_results']), 4)
