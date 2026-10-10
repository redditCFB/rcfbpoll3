from types import SimpleNamespace

from django.template.loader import get_template
from django.test import SimpleTestCase


class PollSectionNavTemplateTests(SimpleTestCase):
    def test_navigation_keeps_all_links_in_a_single_responsive_grid(self):
        rendered = get_template('poll_section_nav.html').render({
            'this_poll': SimpleNamespace(id=252),
            'active_section': 'analysis',
        })

        self.assertIn('class="nav py-3 poll-section-nav"', rendered)
        self.assertIn('aria-label="Poll sections"', rendered)
        self.assertEqual(rendered.count('<a class="nav-link'), 4)
        self.assertEqual(rendered.count('aria-current="page"'), 1)
        self.assertIn('href="/poll/view/252/">Results</a>', rendered)
        self.assertIn('href="/poll/voters/252/">Voters</a>', rendered)
        self.assertIn('href="/poll/ballots/252/1/">Ballots</a>', rendered)
        self.assertIn(
            'class="nav-link disabled" href="/poll/analysis/252/" '
            'aria-current="page">Analysis</a>',
            rendered,
        )
        self.assertNotIn('class="vr"', rendered)
