from datetime import datetime, timezone
from types import SimpleNamespace

from django.template.loader import get_template
from django.test import SimpleTestCase


class PollIndexTemplateTests(SimpleTestCase):
    def test_mobile_week_links_to_poll_results(self):
        poll = SimpleNamespace(
            id=123,
            week='Week 1',
            year=2026,
            publish_date=datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc),
            top_team=SimpleNamespace(handle='test-team', short_name='Test Team'),
        )
        user = SimpleNamespace(is_anonymous=False, is_staff=False, username='test-user')

        rendered = get_template('poll_index.html').render({
            'polls': [poll],
            'years': [2026],
            'user': user,
        })
        mobile_card = rendered.split('<article class="poll-index-mobile-card">', 1)[1].split('</article>', 1)[0]

        self.assertIn(
            '<h4 class="poll-index-mobile-week"><a class="text-reset text-decoration-none" '
            'href="/poll/view/123/">Week 1</a></h4>',
            mobile_card,
        )
