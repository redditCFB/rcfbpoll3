from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from playwright.sync_api import sync_playwright

from poll.models import AboutPage


class AboutLayoutBrowserTests(StaticLiveServerTestCase):
    def setUp(self):
        for page in ('about', 'faq', 'contribute'):
            AboutPage.objects.create(page=page, text=f'{page.title()} content')

    def test_about_tabs_do_not_overlap_content_at_phone_widths(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={'width': 320, 'height': 900})
            try:
                page.route('**/*.js', lambda route: route.abort())
                for width in (320, 390, 430, 768):
                    page.set_viewport_size({'width': width, 'height': 900})
                    for tab in ('about', 'faq', 'contribute', 'voters'):
                        response = page.goto(
                            f'{self.live_server_url}/about/?p={tab}',
                            wait_until='domcontentloaded',
                        )
                        self.assertEqual(response.status, 200)

                        layout = page.evaluate(
                            """() => {
                                const nav = document.querySelector('.about-tab-nav');
                                const content = document.querySelector('.about-tab-content');
                                const navBounds = nav.getBoundingClientRect();
                                const contentBounds = content.getBoundingClientRect();
                                return {
                                    documentWidth: document.documentElement.scrollWidth,
                                    viewportWidth: window.innerWidth,
                                    nav: {
                                        left: navBounds.left,
                                        right: navBounds.right,
                                        bottom: navBounds.bottom,
                                    },
                                    content: {
                                        left: contentBounds.left,
                                        top: contentBounds.top,
                                        right: contentBounds.right,
                                    },
                                };
                            }"""
                        )
                        with self.subTest(width=width, tab=tab):
                            self.assertLessEqual(
                                layout['documentWidth'], layout['viewportWidth'] + 1,
                                msg='About page introduces horizontal page overflow',
                            )
                            self.assertLessEqual(
                                layout['content']['right'], width + 1,
                                msg='About content extends beyond the viewport',
                            )
                            if width < 768:
                                self.assertGreaterEqual(
                                    layout['content']['top'], layout['nav']['bottom'],
                                    msg='About content overlaps the tab navigation',
                                )
                            else:
                                self.assertGreaterEqual(
                                    layout['content']['left'], layout['nav']['right'],
                                    msg='About content overlaps the tab navigation',
                                )
            finally:
                browser.close()
