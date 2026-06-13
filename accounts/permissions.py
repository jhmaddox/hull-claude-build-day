"""RBAC helpers for the accounts workstream.

These build on the tenancy contract (request.org / request.membership set by
CurrentOrgMiddleware, Membership.can_admin) WITHOUT modifying it. Use
``require_org_admin`` to gate write views server-side, and ``is_org_admin`` in
views/templates for read-only checks.
"""

from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect

from .scoping import org_required


def is_org_admin(request):
    """True if the current request's membership can administer the org."""
    membership = getattr(request, "membership", None)
    return bool(membership is not None and getattr(membership, "can_admin", False))


def require_org_admin(view):
    """org_required + the current membership must be owner/admin.

    Non-admins get a messages.error and are redirected back (no 403 page, no
    500). This is enforced SERVER-SIDE even if the UI hides the controls.
    """

    @wraps(view)
    @org_required
    def _wrapped(request, *args, **kwargs):
        if not is_org_admin(request):
            messages.error(request, "You don't have permission to do that.")
            return redirect("accounts:members")
        return view(request, *args, **kwargs)

    return _wrapped
