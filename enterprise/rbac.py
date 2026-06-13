"""Role-based access control built on ``accounts.models.Membership``.

Roles are ranked: ``viewer < member < admin < owner``. ``has_role`` is
FAIL-OPEN: when there is no authenticated request user, no current org, or no
membership, it returns ``True``. This keeps internal / autonomous-loop code
(which has no request-bound user) working — RBAC only restricts real, in-org
human requests. ``role_required`` composes with ``accounts.scoping.org_required``
and renders a 403 page for in-org users below the required rank.
"""

from __future__ import annotations

from functools import wraps

from django.http import HttpResponseForbidden
from django.template.loader import render_to_string

from accounts.models import Membership
from accounts.scoping import org_required

ROLE_RANK = {"viewer": 0, "member": 1, "admin": 2, "owner": 3}


def role_rank(role) -> int:
    return ROLE_RANK.get((role or "").lower(), -1)


def current_membership(request):
    """Return the Membership for request.user in request.org, or None."""
    user = getattr(request, "user", None)
    org = getattr(request, "org", None)
    if user is None or not getattr(user, "is_authenticated", False) or org is None:
        return None
    membership = getattr(request, "membership", None)
    if membership is not None and getattr(membership, "org_id", None) == org.id:
        return membership
    try:
        return Membership.objects.filter(user=user, org=org).first()
    except Exception:
        return None


def has_role(request, minimum) -> bool:
    """True if the request's user meets ``minimum`` rank in the current org.

    FAIL-OPEN for non-request / internal contexts: no user, no org, or no
    membership all return True so the autonomous loop is never blocked.
    """
    user = getattr(request, "user", None)
    org = getattr(request, "org", None)
    if user is None or not getattr(user, "is_authenticated", False) or org is None:
        return True
    membership = current_membership(request)
    if membership is None:
        return True
    return role_rank(membership.role) >= role_rank(minimum)


def role_required(minimum):
    """Decorator: require ``minimum`` role in the current org.

    Composes ``org_required`` (login + active org), then renders a 403 for in-org
    users below ``minimum``. Pass-through (fail-open) when there is no
    request-bound authenticated user.
    """

    def decorator(view):
        @wraps(view)
        @org_required
        def _wrapped(request, *args, **kwargs):
            if not has_role(request, minimum):
                html = render_to_string(
                    "enterprise/403.html",
                    {"required_role": minimum},
                    request=request,
                )
                return HttpResponseForbidden(html)
            return view(request, *args, **kwargs)

        return _wrapped

    return decorator
