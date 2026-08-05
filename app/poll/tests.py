from django.test import SimpleTestCase
from django.test.utils import override_settings
from django.template import Context, Template


class TeamLogoUrlTagTests(SimpleTestCase):
    def test_renders_the_configured_url(self):
        rendered = Template('{% load team_logo %}{% team_logo_url "notredame" %}').render(Context())

        self.assertEqual(rendered, 'https://cdn.redditcfb.com/60x40/cfb/notredame.png')

    @override_settings(TEAM_LOGO_URL_TEMPLATE='https://logos.example/{handle}.svg')
    def test_uses_the_configured_url_template(self):
        rendered = Template('{% load team_logo %}{% team_logo_url "notredame" %}').render(Context())

        self.assertEqual(rendered, 'https://logos.example/notredame.svg')
