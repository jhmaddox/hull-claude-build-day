from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from core.models import Event
from deploys.models import Deployment

from .models import Incident, LogLine, MetricPoint


def _deployment_metric_series(deployment, name, limit=30):
    """Most-recent ``limit`` metric values for a deployment+name, oldest-first."""
    pts = list(
        MetricPoint.objects.filter(deployment=deployment, name=name)
        .order_by("-ts")[:limit]
        .values_list("value", flat=True)
    )
    return list(reversed(pts))


_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _spark(series):
    if not series:
        return ""
    lo, hi = min(series), max(series)
    span = (hi - lo) or 1
    out = []
    for v in series:
        idx = int((v - lo) / span * (len(_SPARK_CHARS) - 1))
        out.append(_SPARK_CHARS[idx])
    return "".join(out)


def overview(request):
    """/obs/ — per-live-deployment cards with request/error sparkline data."""
    live = (
        Deployment.objects.filter(status=Deployment.Status.LIVE)
        .select_related("environment__project")
        .order_by("-created_at")
    )
    cards = []
    for dep in live:
        req_series = _deployment_metric_series(dep, "requests")
        err_series = _deployment_metric_series(dep, "errors")
        recent_errors = list(
            dep.logs.filter(level=LogLine.Level.ERROR).order_by("-ts")[:6]
        )
        cards.append(
            {
                "dep": dep,
                "requests": int(sum(req_series)),
                "errors": int(sum(err_series)),
                "req_spark": _spark(req_series),
                "err_spark": _spark(err_series),
                "recent_errors": recent_errors,
            }
        )
    ctx = {
        "cards": cards,
        "open_incidents": Incident.objects.exclude(
            status=Incident.Status.RESOLVED
        ).select_related("project")[:8],
    }
    return render(request, "observability/overview.html", ctx)


def incident_list(request):
    incidents = Incident.objects.select_related("project", "remediation_pr").all()
    ctx = {
        "incidents": incidents,
        "open_count": incidents.exclude(status=Incident.Status.RESOLVED).count(),
    }
    return render(request, "observability/incident_list.html", ctx)


def _incident_ctx(incident):
    from orchestration.service import is_remediating

    agent_runs = list(
        incident.agent_runs.select_related("pull_request").order_by("created_at")
    )
    events = (
        Event.objects.filter(project=incident.project)
        .filter(verb__icontains=f"INC-{incident.number}")
        .order_by("ts")[:60]
    )
    return {
        "incident": incident,
        "agent_runs": agent_runs,
        "remediation_run": agent_runs[-1] if agent_runs else None,
        "events": events,
        "is_remediating": is_remediating(incident.pk),
    }


def incident_detail(request, pk):
    incident = get_object_or_404(
        Incident.objects.select_related("project", "deployment", "remediation_pr"),
        pk=pk,
    )
    return render(
        request, "observability/incident_detail.html", _incident_ctx(incident)
    )


def incident_status(request, pk):
    """HTMX fragment polled every 2s on the incident detail page."""
    incident = get_object_or_404(
        Incident.objects.select_related("project", "remediation_pr"), pk=pk
    )
    return render(
        request, "observability/_incident_status.html", _incident_ctx(incident)
    )


def incident_remediate(request, pk):
    """Manual 'Remediate now' button -> orchestration.service.remediate."""
    incident = get_object_or_404(Incident, pk=pk)
    from orchestration.service import is_remediating, remediate

    if incident.status == Incident.Status.RESOLVED:
        messages.error(request, f"INC-{incident.number} is already resolved.")
    elif is_remediating(incident.pk):
        messages.error(
            request, f"INC-{incident.number} is already being remediated."
        )
    else:
        remediate(incident.id)
        messages.success(
            request, f"Remediation dispatched for INC-{incident.number}."
        )
    return redirect(incident.get_absolute_url())


def deployment_logs(request, pk):
    """HTMX-poll fragment: recent log lines for a deployment, styled."""
    deployment = get_object_or_404(Deployment, pk=pk)
    logs = list(deployment.logs.order_by("-ts")[:120])
    logs.reverse()
    return render(
        request,
        "observability/_logs.html",
        {"logs": logs, "deployment": deployment},
    )
