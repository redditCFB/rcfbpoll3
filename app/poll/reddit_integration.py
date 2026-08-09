import praw
from django.conf import settings

from .models import RedditAccount, RedditRoleAssignment
from .reddit_crypto import TokenEncryptionError, decrypt_refresh_token


ROLE_SCOPES = {
    RedditRoleAssignment.Role.NOTIFICATIONS: frozenset(('identity', 'privatemessages')),
    RedditRoleAssignment.Role.APPLICATION_REVIEW: frozenset(('identity', 'read')),
    RedditRoleAssignment.Role.RESULTS_PUBLISHER: frozenset(('identity', 'submit')),
}


class RedditIntegrationError(Exception):
    """Base exception for configured Reddit automation failures."""


class RedditAutomationNotConfigured(RedditIntegrationError):
    pass


class RedditRoleNotAssigned(RedditIntegrationError):
    pass


class RedditAccountNotAuthorized(RedditIntegrationError):
    pass


class RedditScopesMissing(RedditIntegrationError):
    pass


class RedditCredentialInvalid(RedditIntegrationError):
    pass


def required_scopes_for_roles(roles):
    scopes = set()
    for role in roles:
        try:
            scopes.update(ROLE_SCOPES[role])
        except KeyError as exc:
            raise ValueError('Unsupported Reddit automation role: %s' % role) from exc
    return frozenset(scopes)


def required_scopes_for_role(role):
    return required_scopes_for_roles((role,))


def _automation_client(**kwargs):
    required = (
        settings.REDDIT_AUTOMATION_CLIENT_ID,
        settings.REDDIT_AUTOMATION_CLIENT_SECRET,
        settings.REDDIT_AUTOMATION_USER_AGENT,
    )
    if not all(required):
        raise RedditAutomationNotConfigured('Reddit automation OAuth application is not configured.')
    return praw.Reddit(
        client_id=settings.REDDIT_AUTOMATION_CLIENT_ID,
        client_secret=settings.REDDIT_AUTOMATION_CLIENT_SECRET,
        user_agent=settings.REDDIT_AUTOMATION_USER_AGENT,
        **kwargs,
    )


def oauth_client():
    if not settings.REDDIT_AUTOMATION_REDIRECT_URI:
        raise RedditAutomationNotConfigured('REDDIT_AUTOMATION_REDIRECT_URI is not configured.')
    return _automation_client(redirect_uri=settings.REDDIT_AUTOMATION_REDIRECT_URI)


def reddit_client_for_role(role):
    try:
        assignment = RedditRoleAssignment.objects.select_related('account').get(role=role)
    except RedditRoleAssignment.DoesNotExist as exc:
        raise RedditRoleNotAssigned('No Reddit account is assigned to role %s.' % role) from exc

    account = assignment.account
    if not account.encrypted_refresh_token:
        raise RedditAccountNotAuthorized('Reddit account u/%s has not been authorized.' % account.username)
    required = required_scopes_for_role(role)
    missing = required - set(account.granted_scopes or [])
    if missing:
        raise RedditScopesMissing(
            'Reddit account u/%s is missing required scope(s): %s.' % (account.username, ', '.join(sorted(missing)))
        )
    try:
        refresh_token = decrypt_refresh_token(account.encrypted_refresh_token)
    except TokenEncryptionError as exc:
        raise RedditCredentialInvalid('Reddit account u/%s has an unusable credential.' % account.username) from exc
    return _automation_client(refresh_token=refresh_token)
