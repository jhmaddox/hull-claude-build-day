from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render

from agents.models import AgentRun
from core.models import Event
from deploys.models import Deployment, Environment
from observability.models import Incident
from projects.models import Project
from vcs.models import PullRequest


def _adopt_deployments():
    """Ensure the long-lived server is tailing every live deployment's logs.

    Idempotent and cheap; called from the dashboard + polled feed so the server
    reliably ingests logs from deployments regardless of which process started
    them (e.g. the helm_demo management command)."""
    try:
        from deploys.tailer import ensure_tailers

        ensure_tailers()
    except Exception:  # noqa: BLE001
        pass


def _org_field(qs):
    """Return the field path used to org-scope ``qs``.

    Most models subclass ``OrgScopedModel`` and carry an ``org`` FK directly.
    A few (notably ``Event``) have no ``org`` column but reach an org through a
    nullable ``project`` FK, so we scope those via ``project__org``.
    """
    field_names = {f.name for f in qs.model._meta.get_fields()}
    if "org" in field_names:
        return "org"
    if "project" in field_names:
        return "project__org"
    return None


def _org_scope(qs, request):
    """Org-scope ``qs`` to the request's org PLUS shared (org=None) rows.

    This is deliberately an OR policy (current org *or* unscoped) rather than
    ``accounts.scoping.scoped()`` which strict-filters and returns ``.none()``
    when org is None. The org=None rows are the autonomous-loop / demo data that
    must stay visible — hiding them would break the crown-jewel demo. When there
    is no active org (anon / brand-new user) we leave the queryset unchanged so
    the dashboard still renders (HTTP 200, never 500).
    """
    org = getattr(request, "org", None)
    if org is None:
        return qs
    field = _org_field(qs)
    if field is None:
        return qs
    return qs.filter(Q(**{field: org}) | Q(**{f"{field}__isnull": True}))


@login_required
def dashboard(request):
    """The Hull mission-control home: everything at a glance."""
    _adopt_deployments()

    projects = _org_scope(Project.objects.all(), request)
    live_deployments = _org_scope(
        Deployment.objects.filter(status=Deployment.Status.LIVE), request
    ).select_related("environment__project")
    open_incidents = _org_scope(
        Incident.objects.exclude(status=Incident.Status.RESOLVED), request
    ).select_related("project")
    running_agents = _org_scope(
        AgentRun.objects.filter(status=AgentRun.Status.RUNNING), request
    ).select_related("project")
    open_prs = _org_scope(
        PullRequest.objects.filter(status=PullRequest.Status.OPEN), request
    ).select_related("project")
    environments = _org_scope(Environment.objects.all(), request)
    events = _org_scope(Event.objects.all(), request).select_related("project")

    ctx = {
        "projects": projects[:12],
        "live_deployments": live_deployments[:12],
        "open_incidents": open_incidents[:12],
        "running_agents": running_agents[:12],
        "open_prs": open_prs[:12],
        "events": events[:40],
        "stats": {
            "projects": projects.count(),
            "environments": environments.count(),
            "live": live_deployments.count(),
            "incidents": open_incidents.count(),
            "agents": running_agents.count(),
        },
    }
    return render(request, "core/dashboard.html", ctx)


@login_required
def feed(request):
    """HTMX-polled activity feed fragment."""
    _adopt_deployments()
    events = _org_scope(Event.objects.all(), request).select_related("project")[:40]
    return render(request, "core/_feed.html", {"events": events})
