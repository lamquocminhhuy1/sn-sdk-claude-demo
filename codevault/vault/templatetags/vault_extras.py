from django import template
from django.utils.timesince import timesince

register = template.Library()


@register.filter
def ago(value):
    """Compact relative time: '2 hours ago' instead of '2 hours, 44 minutes ago'."""
    if not value:
        return ""
    return timesince(value).split(",")[0] + " ago"
