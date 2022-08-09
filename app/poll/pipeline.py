from .models import User


def check_for_user(backend, user, response, *args, **kwargs):
    if not User.objects.filter(username=user.username).exists():
        new_user = User(username=user.username)
        new_user.save()
