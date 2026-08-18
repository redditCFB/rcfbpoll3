"""Transactional voter-role promotion workflows."""
from dataclasses import dataclass
from enum import Enum
import logging

from django.db import transaction
from django.utils import timezone

from .models import Ballot, ResultSet, User, UserRole

logger = logging.getLogger(__name__)


class PromotionStatus(Enum):
    READY = 'READY'
    PROMOTED = 'PROMOTED'
    FAIL = 'FAIL'


@dataclass(frozen=True)
class PromotionOutcome:
    supplied_username: str
    status: PromotionStatus
    canonical_username: str = ''
    reason: str = ''
    open_ballots: int = 0


def _resolve_user(username, lock=False):
    users = User.objects.filter(username__iexact=username)
    if lock:
        users = users.select_for_update()
    matches = list(users)
    if not matches:
        return None, 'User not found'
    if len(matches) > 1:
        return None, 'Ambiguous username'
    return matches[0], ''


def _state_outcome(username, user, status=PromotionStatus.READY, lock=False):
    active_main_roles = UserRole.objects.filter(user=user, role=UserRole.Role.VOTER, end_date__isnull=True)
    if lock:
        active_main_roles = active_main_roles.select_for_update()
    if active_main_roles.exists():
        return PromotionOutcome(username, PromotionStatus.FAIL, user.username, 'Already an active main voter')
    provisional_roles = UserRole.objects.filter(
        user=user, role=UserRole.Role.PROVISIONAL, end_date__isnull=True,
    )
    if lock:
        provisional_roles = provisional_roles.select_for_update()
    provisional_roles = list(provisional_roles)
    if len(provisional_roles) == 0:
        return PromotionOutcome(username, PromotionStatus.FAIL, user.username, 'No active provisional voter role')
    if len(provisional_roles) > 1:
        return PromotionOutcome(username, PromotionStatus.FAIL, user.username, 'Multiple active provisional voter roles')
    now = timezone.now()
    open_ballots = Ballot.objects.filter(
        user=user, user_type=UserRole.Role.PROVISIONAL,
        poll__open_date__lt=now, poll__close_date__gt=now,
    ).count()
    return PromotionOutcome(username, status, user.username, open_ballots=open_ballots)


def preview_provisional_voter_promotion(username):
    user, reason = _resolve_user(username)
    if reason:
        return PromotionOutcome(username, PromotionStatus.FAIL, reason=reason)
    return _state_outcome(username, user)


def promote_provisional_voter(username):
    """Revalidate and promote one username, isolating its transaction from the batch."""
    try:
        with transaction.atomic():
            user, reason = _resolve_user(username, lock=True)
            if reason:
                return PromotionOutcome(username, PromotionStatus.FAIL, reason=reason)
            outcome = _state_outcome(username, user, lock=True)
            if outcome.status is PromotionStatus.FAIL:
                return outcome

            transition_time = timezone.now()
            provisional_role = UserRole.objects.select_for_update().get(
                user=user, role=UserRole.Role.PROVISIONAL, end_date__isnull=True,
            )
            provisional_role.end_date = transition_time
            provisional_role.save(update_fields=['end_date'])
            UserRole.objects.create(
                user=user, role=UserRole.Role.VOTER,
                start_date=transition_time, end_date=None,
            )
            affected_ballots = Ballot.objects.filter(
                user=user, user_type=UserRole.Role.PROVISIONAL,
                poll__open_date__lt=transition_time, poll__close_date__gt=transition_time,
            )
            affected_poll_ids = list(affected_ballots.values_list('poll_id', flat=True).distinct())
            reclassified = affected_ballots.update(user_type=UserRole.Role.VOTER)
            if affected_poll_ids:
                ResultSet.objects.filter(poll_id__in=affected_poll_ids).delete()
            return PromotionOutcome(
                username, PromotionStatus.PROMOTED, user.username, open_ballots=reclassified,
            )
    except Exception:
        logger.exception('Unexpected error while promoting provisional voter %r', username)
        return PromotionOutcome(
            username, PromotionStatus.FAIL, reason='Unexpected error while promoting user',
        )
