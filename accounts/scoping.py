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


def visible(model_or_qs, request):
    """Org-scoped read policy used across all list/detail views: the current
    org's rows PLUS shared rows (``org IS NULL``).

    The autonomous loop (and imports) create records with ``org=None`` because
    they run without a request. Those must stay visible to operators, so reads
    use this OR policy — and it's the SAME policy the dashboard uses, so the
    dashboard and the section tabs always agree. Other orgs' rows stay hidden.

    Handles models with a direct ``org`` field or a related ``project__org``
    (e.g. core.Event). With no active org the queryset is returned unchanged so
    pages still render.
    """
    from django.db.models import Q

    qs = model_or_qs if hasattr(model_or_qs, "filter") else model_or_qs.objects.all()
    org = getattr(request, "org", None)
    if org is None:
        return qs
    field_names = {f.name for f in qs.model._meta.get_fields()}
    if "org" in field_names:
        field = "org"
    elif "project" in field_names:
        field = "project__org"
    else:
        return qs
    return qs.filter(Q(**{field: org}) | Q(**{f"{field}__isnull": True}))


def current_org(request):
    return getattr(request, "org", None)
