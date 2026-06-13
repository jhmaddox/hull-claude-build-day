"""Account context processor — exposes the user's memberships + current org
to every template so the org switcher and account nav can render anywhere.

Register in settings.py TEMPLATES['OPTIONS']['context_processors'] as
``accounts.context_processors.account_nav`` (a one-line integrator change).
Even without registration the org switcher partial works (it reads
``request`` directly), but registering this makes ``account_memberships`` /
``current_org`` available by name in any template.

Safe for anonymous requests: returns empty/default values, never raises.
"""

from __future__ import annotations


def account_nav(request):
    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return {"account_memberships": [], "current_org": None}
    try:
        memberships = list(
            user.memberships.select_related("org").all()
        )
    except Exception:
        memberships = []
    return {
        "account_memberships": memberships,
        "current_org": getattr(request, "org", None),
    }
