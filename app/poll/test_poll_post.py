from types import SimpleNamespace

from django.template.loader import get_template
from django.test import RequestFactory, SimpleTestCase


class PollPostTemplateTests(SimpleTestCase):
    def test_includes_the_peoples_poll_link(self):
        request = RequestFactory().get('/poll_post/')
        request.user = SimpleNamespace(is_anonymous=False, is_staff=False, username='test-user')
        top25 = [
            SimpleNamespace(
                rank_diff=0,
                rank=rank,
                rank_diff_str='--',
                team=SimpleNamespace(handle=f'team-{rank}', name=f'Team {rank}', short_name=f'Team {rank}'),
                first_place_votes=0,
                points=100,
            )
            for rank in range(1, 6)
        ]
        rendered = get_template('poll_post.html').render({
            'poll': '2025 Week 12',
            'top25': top25,
            'next_ten': [],
            'dropped': [],
            'links': {
                'results': 'https://poll.example/results',
                'provisional': 'https://poll.example/peoples-poll',
                'voters': 'https://poll.example/voters',
                'ballots': 'https://poll.example/ballots',
                'analysis': 'https://poll.example/analysis',
                'about': 'https://poll.example/about',
                'faq': 'https://poll.example/faq',
                'contribute': 'https://poll.example/contribute',
                'hall': 'https://poll.example/hall',
            },
        }, request)

        self.assertIn('* [THE PEOPLE\'S POLL](https://poll.example/peoples-poll)<br>', rendered)
