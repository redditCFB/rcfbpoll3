from django import template
from django.conf import settings


register = template.Library()


@register.simple_tag
def team_logo_url(handle):
    return settings.TEAM_LOGO_URL_TEMPLATE.format(handle=handle)
