import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from poll.models import ProvisionalUserApplication
from poll.provisional_screening import screen_provisional_application
from poll.provisional_services import accept_provisional_application

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Screen OPEN provisional applications and automatically accept all-pass applications.'

    def handle(self, *args, **options):
        evaluated = accepted = open_for_review = errors = notification_failures = 0
        ids = list(ProvisionalUserApplication.objects.filter(
            status=ProvisionalUserApplication.Status.OPEN).values_list('pk', flat=True))
        for application_id in ids:
            try:
                application = ProvisionalUserApplication.objects.get(pk=application_id)
                result = screen_provisional_application(application)
                application.screened_at = timezone.now()
                application.screening_flags = list(result.flags)
                application.save(update_fields=['screened_at', 'screening_flags'])
                evaluated += 1
                if result.all_pass:
                    changed, notified = accept_provisional_application(
                        application, ProvisionalUserApplication.DecisionSource.AUTOMATIC)
                    accepted += int(changed)
                    notification_failures += int(changed and not notified)
                else:
                    open_for_review += 1
            except Exception:
                errors += 1
                open_for_review += 1
                logger.exception('Could not screen provisional application %s.', application_id)
                ProvisionalUserApplication.objects.filter(
                    pk=application_id, status=ProvisionalUserApplication.Status.OPEN).update(
                    screened_at=timezone.now(), screening_flags=['screening_error'])
        self.stdout.write(
            'Evaluated: %d; automatically accepted: %d; left open: %d; screening errors: %d; notification failures: %d'
            % (evaluated, accepted, open_for_review, errors, notification_failures))
