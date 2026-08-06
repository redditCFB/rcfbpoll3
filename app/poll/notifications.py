import logging

import praw
from django.conf import settings

from .models import ProvisionalUserApplication


logger = logging.getLogger(__name__)


def _decision_message(application):
    username = application.user.username
    if application.status == ProvisionalUserApplication.Status.ACCEPTED:
        return (
            'Your r/CFB Poll provisional voter application was approved',
            'Hi u/%s,\n\n'
            'Your application to be a provisional voter in the r/CFB Poll has been approved. '
            'You can submit ballots at https://poll.redditcfb.com/ whenever a poll is open.\n\n'
            '— r/CFB Poll' % username,
        )
    if application.status == ProvisionalUserApplication.Status.REJECTED:
        return (
            'Your r/CFB Poll provisional voter application was not approved',
            'Hi u/%s,\n\n'
            'Your application to be a provisional voter in the r/CFB Poll was not approved at this time.\n\n'
            '— r/CFB Poll' % username,
        )
    raise ValueError('Application must be accepted or rejected before it can be messaged.')


def send_provisional_application_decision_message(application):
    """Send the applicant a Reddit message and return whether delivery succeeded."""
    required_settings = (
        settings.REDDIT_MESSAGE_CLIENT_ID,
        settings.REDDIT_MESSAGE_CLIENT_SECRET,
        settings.REDDIT_MESSAGE_PASSWORD,
    )
    if not all(required_settings):
        logger.warning('Reddit decision notification skipped because bot credentials are not configured.')
        return False

    subject, body = _decision_message(application)
    try:
        reddit = praw.Reddit(
            client_id=settings.REDDIT_MESSAGE_CLIENT_ID,
            client_secret=settings.REDDIT_MESSAGE_CLIENT_SECRET,
            username=settings.REDDIT_MESSAGE_USERNAME,
            password=settings.REDDIT_MESSAGE_PASSWORD,
            user_agent=settings.REDDIT_MESSAGE_USER_AGENT,
        )
        reddit.redditor(application.user.username).message(subject, body)
    except Exception:
        logger.exception('Could not send Reddit decision notification to u/%s.', application.user.username)
        return False
    return True
