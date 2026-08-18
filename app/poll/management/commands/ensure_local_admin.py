import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Ensure the documented local development administrator exists.'

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('ensure_local_admin is only available when DEBUG=True.')

        username = os.environ.get('LOCAL_ADMIN_USERNAME', 'localadmin')
        password = os.environ.get('LOCAL_ADMIN_PASSWORD', 'RcfbPollLocal2026!')
        if not username or not password:
            raise CommandError('LOCAL_ADMIN_USERNAME and LOCAL_ADMIN_PASSWORD must be non-empty.')

        user_model = get_user_model()
        user, created = user_model.objects.get_or_create(
            username=username,
            defaults={'is_active': True, 'is_staff': True, 'is_superuser': True},
        )
        changed_fields = []
        for field in ('is_active', 'is_staff', 'is_superuser'):
            if not getattr(user, field):
                setattr(user, field, True)
                changed_fields.append(field)
        if created or not user.has_usable_password():
            user.set_password(password)
            changed_fields.append('password')
        if changed_fields:
            user.save(update_fields=changed_fields)

        action = 'Created' if created else 'Ensured'
        self.stdout.write(self.style.SUCCESS(f'{action} local admin {username!r}.'))
