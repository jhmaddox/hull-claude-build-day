"""Helpers builders use to enforce org scoping in views.  [stable contract]

Usage in a view::

    from accounts.scoping import org_required, scoped

    @org_required
    def my_list(request):
        items = scoped(MyModel, request)          # filtered to request.org
        ...

For models that subclass ``OrgScopedModel`` you can also use
``MyModel.objects.for_org(request.org)``.
"""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def org_required(view):
    """login_required + ensures the user has an active org (else onboarding)."""

    @wraps(view)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if getattr(request, "org", None) is None:
            return redirect("accounts:onboarding")
        return view(request, *args, **kwargs)

    return _wrapped


def scoped(model_or_qs, request):
    """Return ``model_or_qs`` filtered to the request's org.

    Accepts a model class or a queryset. Filters by the ``org`` field.
    """
    qs = model_or_qs if hasattr(model_or_qs, "filter") else model_or_qs.objects.all()
    org = getattr(request, "org", None)
    return qs.filter(org=org) if org is not None else qs.none()


def current_org(request):
    return getattr(request, "org", None)
