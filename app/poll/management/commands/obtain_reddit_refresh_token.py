import secrets
from urllib.parse import parse_qs, urlparse

import praw
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Obtain a Reddit refresh token for provisional-application notifications.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--redirect-uri',
            default='http://localhost:8080',
            help='OAuth redirect URI configured for the Reddit web app (default: http://localhost:8080).',
        )

    def handle(self, *args, **options):
        if not settings.REDDIT_MESSAGE_CLIENT_ID or not settings.REDDIT_MESSAGE_CLIENT_SECRET:
            raise CommandError(
                'Set REDDIT_MESSAGE_CLIENT_ID and REDDIT_MESSAGE_CLIENT_SECRET before running this command.'
            )

        redirect_uri = options['redirect_uri']
        state = secrets.token_urlsafe(32)
        reddit = praw.Reddit(
            client_id=settings.REDDIT_MESSAGE_CLIENT_ID,
            client_secret=settings.REDDIT_MESSAGE_CLIENT_SECRET,
            redirect_uri=redirect_uri,
            user_agent=settings.REDDIT_MESSAGE_USER_AGENT,
        )
        authorization_url = reddit.auth.url(
            scopes=['identity', 'privatemessages'],
            state=state,
            duration='permanent',
        )

        self.stdout.write('Open this URL in a browser, sign in as u/CFB_Referee, and approve access:')
        self.stdout.write(authorization_url)
        self.stdout.write(
            'After Reddit redirects your browser, copy the complete URL from the address bar and paste it below.'
        )
        callback_url = input('Redirect URL: ').strip()
        callback_parameters = parse_qs(urlparse(callback_url).query)

        if 'error' in callback_parameters:
            raise CommandError('Reddit authorization failed: %s.' % callback_parameters['error'][0])
        if callback_parameters.get('state', [None])[0] != state:
            raise CommandError('The callback state did not match; refusing to exchange the authorization code.')
        if not callback_parameters.get('code'):
            raise CommandError('The callback URL did not contain an authorization code.')

        refresh_token = reddit.auth.authorize(callback_parameters['code'][0])
        self.stdout.write(self.style.SUCCESS('Authorization succeeded. Store this as a production secret:'))
        self.stdout.write('REDDIT_MESSAGE_REFRESH_TOKEN=%s' % refresh_token)
