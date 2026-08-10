"""Domain workflows for provisional application decisions."""
import logging
from django.db import transaction
from django.utils import timezone
from .models import ProvisionalUserApplication, UserRole
from .notifications import send_provisional_application_decision_message

logger = logging.getLogger(__name__)


def _notify(application, source):
    sent = send_provisional_application_decision_message(application)
    if not sent and source == ProvisionalUserApplication.DecisionSource.AUTOMATIC:
        logger.warning('Automatic provisional acceptance was saved, but notification failed for application %s.', application.pk)
    return sent


def accept_provisional_application(application, decision_source, notify=True):
    with transaction.atomic():
        locked = ProvisionalUserApplication.objects.select_for_update().get(pk=application.pk)
        if locked.status != ProvisionalUserApplication.Status.OPEN:
            return False, application, True
        locked.status = ProvisionalUserApplication.Status.ACCEPTED
        locked.decision_source = decision_source
        locked.save(update_fields=['status', 'decision_source'])
        UserRole.objects.get_or_create(user=locked.user, role=UserRole.Role.PROVISIONAL,
                                       end_date__isnull=True, defaults={'start_date': timezone.now()})
        application = locked
    return True, application, _notify(application, decision_source) if notify else True


def reject_provisional_application(application, notify=True):
    with transaction.atomic():
        locked = ProvisionalUserApplication.objects.select_for_update().get(pk=application.pk)
        if locked.status != ProvisionalUserApplication.Status.OPEN:
            return False, application, True
        locked.status = ProvisionalUserApplication.Status.REJECTED
        locked.decision_source = ProvisionalUserApplication.DecisionSource.MANUAL
        locked.save(update_fields=['status', 'decision_source'])
        application = locked
    return True, application, _notify(application, ProvisionalUserApplication.DecisionSource.MANUAL) if notify else True
