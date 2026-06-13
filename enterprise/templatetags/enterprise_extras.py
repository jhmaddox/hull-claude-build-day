"""App-local template tags for the enterprise UI.

Usage in a template::

    {% load enterprise_extras %}
    {% if request|can:"admin" %} ... {% endif %}

This is a simple, app-local filter — no global context processor is registered.
"""

from django import template

from enterprise.rbac import has_role

register = template.Library()


@register.filter(name="can")
def can(request, role):
    """True if the request's user has at least ``role`` in the current org."""
    try:
        return has_role(request, role)
    except Exception:
        return False
