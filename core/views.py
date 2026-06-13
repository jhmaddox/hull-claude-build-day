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


def dashboard(request):
    """The Helm mission-control home: everything at a glance."""
    _adopt_deployments()
    ctx = {
        "projects": Project.objects.all()[:12],
        "live_deployments": Deployment.objects.filter(
            status=Deployment.Status.LIVE
        ).select_related("environment__project")[:12],
        "open_incidents": Incident.objects.exclude(
            status=Incident.Status.RESOLVED
        ).select_related("project")[:12],
        "running_agents": AgentRun.objects.filter(
            status=AgentRun.Status.RUNNING
        ).select_related("project")[:12],
        "open_prs": PullRequest.objects.filter(
            status=PullRequest.Status.OPEN
        ).select_related("project")[:12],
        "events": Event.objects.select_related("project")[:40],
        "stats": {
            "projects": Project.objects.count(),
            "environments": Environment.objects.count(),
            "live": Deployment.objects.filter(status=Deployment.Status.LIVE).count(),
            "incidents": Incident.objects.exclude(
                status=Incident.Status.RESOLVED
            ).count(),
            "agents": AgentRun.objects.filter(
                status=AgentRun.Status.RUNNING
            ).count(),
        },
    }
    return render(request, "core/dashboard.html", ctx)


def feed(request):
    """HTMX-polled activity feed fragment."""
    _adopt_deployments()
    events = Event.objects.select_related("project")[:40]
    return render(request, "core/_feed.html", {"events": events})
