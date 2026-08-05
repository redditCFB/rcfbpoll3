
from django.dispatch import receiver
from django.contrib.auth.signals import user_logged_in
from django.db import transaction

from .models import User


@receiver(user_logged_in)
def ensure_poll_user_exists(sender, request, user, **kwargs):
    with transaction.atomic():
        if not User.objects.filter(username=user.username).exists():
            User.objects.create(username=user.username)
