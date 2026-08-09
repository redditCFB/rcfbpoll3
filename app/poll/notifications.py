import logging

from .models import ProvisionalUserApplication
from .reddit_integration import reddit_client_for_role


logger = logging.getLogger(__name__)


def _decision_message(application):
    username = application.user.username
    if application.status == ProvisionalUserApplication.Status.ACCEPTED:
        return (
            'Your r/CFB Poll provisional voter application was approved',
            'Hi u/%s,\n\n'
            'Your application to be a provisional voter in the r/CFB Poll has been approved. You can '
            'submit provisional ballots at https://poll.redditcfb.com/ whenever a poll is open; they '
            'will be included in the poll\'s provisional results.\n\n'
            '— r/CFB Poll' % username,
        )
    if application.status == ProvisionalUserApplication.Status.REJECTED:
        return (
            'Your r/CFB Poll provisional voter application was not approved',
            'Hi u/%s,\n\n'
            'Your application to be a provisional voter in the r/CFB Poll was not approved at this time. '
            'Thank you for your interest in participating. If you would like more information about the '
            'decision, you can message u/sirgippy or the r/CFB moderators.\n\n'
            '— r/CFB Poll' % username,
        )
    raise ValueError('Application must be accepted or rejected before it can be messaged.')


def send_provisional_application_decision_message(application):
    """Send the applicant a Reddit message and return whether delivery succeeded."""
    subject, body = _decision_message(application)
    try:
        reddit = reddit_client_for_role('NOTIFICATIONS')
        reddit.redditor(application.user.username).message(subject, body)
    except Exception:
        logger.exception('Could not send Reddit decision notification to u/%s.', application.user.username)
        return False
    return True
