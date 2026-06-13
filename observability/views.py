from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render

from accounts.scoping import org_required
from core.models import Event
from deploys.models import Deployment

from . import services
from .models import Incident, LogLine, MetricPoint, Monitor


# --------------------------------------------------------------------------- #
# Org-scoping helpers
# --------------------------------------------------------------------------- #
def _org_deployments(request):
    """Deployments whose owning project belongs to the request's org."""
    return Deployment.objects.filter(
        environment__project__org=request.org
    ).select_related("environment__project")


def _get_org_deployment(request, pk):
    """404 unless the deployment belongs to the request's org."""
    return get_object_or_404(_org_deployments(request), pk=pk)


def _org_incidents(request):
    return Incident.objects.filter(project__org=request.org)


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


def _svg_sparkline(series, width=160, height=36, color="var(--accent)"):
    """Render a lightweight inline SVG polyline sparkline (no JS)."""
    if not series:
        return ""
    if len(series) == 1:
        series = [series[0], series[0]]
    lo, hi = min(series), max(series)
    span = (hi - lo) or 1
    n = len(series)
    pts = []
    for i, v in enumerate(series):
        x = (i / (n - 1)) * (width - 2) + 1
        y = height - 1 - ((v - lo) / span) * (height - 2)
        pts.append(f"{x:.1f},{y:.1f}")
    points = " ".join(pts)
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'preserveAspectRatio="none" style="display:block">'
        f'<polyline fill="none" stroke="{color}" stroke-width="1.5" '
        f'points="{points}" /></svg>'
    )


def _dep_dashboard_ctx(deployment, window_minutes=5):
    rolled = services.rollups(deployment, window_minutes=window_minutes)
    req_series = _deployment_metric_series(deployment, "requests")
    err_series = _deployment_metric_series(deployment, "errors")
    lat_series = _deployment_metric_series(deployment, "latency_ms")
    return {
        "deployment": deployment,
        "window_minutes": window_minutes,
        "rollups": rolled,
        "req_spark": _svg_sparkline(req_series, color="var(--accent)"),
        "err_spark": _svg_sparkline(err_series, color="var(--danger)"),
        "lat_spark": _svg_sparkline(lat_series, color="var(--accent)"),
    }


# --------------------------------------------------------------------------- #
# Overview + incidents (org-scoped — OBS-8)
# --------------------------------------------------------------------------- #
@org_required
def overview(request):
    """/obs/ — per-live-deployment cards with request/error sparkline data."""
    live = (
        _org_deployments(request)
        .filter(status=Deployment.Status.LIVE)
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
        "open_incidents": _org_incidents(request)
        .exclude(status=Incident.Status.RESOLVED)
        .select_related("project")[:8],
    }
    return render(request, "observability/overview.html", ctx)


@org_required
def incident_list(request):
    incidents = _org_incidents(request).select_related("project", "remediation_pr")
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


@org_required
def incident_detail(request, pk):
    incident = get_object_or_404(
        _org_incidents(request).select_related(
            "project", "deployment", "remediation_pr"
        ),
        pk=pk,
    )
    return render(
        request, "observability/incident_detail.html", _incident_ctx(incident)
    )


@org_required
def incident_status(request, pk):
    """HTMX fragment polled every 2s on the incident detail page."""
    incident = get_object_or_404(
        _org_incidents(request).select_related("project", "remediation_pr"), pk=pk
    )
    return render(
        request, "observability/_incident_status.html", _incident_ctx(incident)
    )


@org_required
def incident_remediate(request, pk):
    """Manual 'Remediate now' button -> orchestration.service.remediate."""
    incident = get_object_or_404(_org_incidents(request), pk=pk)
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


# --------------------------------------------------------------------------- #
# Structured log search/filter (OBS-4)
# --------------------------------------------------------------------------- #
def _filter_logs(deployment, params):
    """Apply server-side query params to a deployment's logs queryset."""
    from django.db.models import Q

    qs = deployment.logs.all()

    level = (params.get("level") or "").strip().lower()
    if level in dict(LogLine.Level.choices):
        qs = qs.filter(level=level)

    method = (params.get("method") or "").strip().upper()
    if method:
        qs = qs.filter(method=method)

    path = (params.get("path") or "").strip()
    if path:
        qs = qs.filter(path__icontains=path)

    status = (params.get("status") or "").strip().lower()
    if status:
        if status in ("5xx", "4xx", "3xx", "2xx", "1xx"):
            lo = int(status[0]) * 100
            qs = qs.filter(status_code__gte=lo, status_code__lt=lo + 100)
        else:
            try:
                qs = qs.filter(status_code=int(status))
            except ValueError:
                pass

    q = (params.get("q") or "").strip()
    if q:
        qs = qs.filter(Q(message__icontains=q) | Q(path__icontains=q))

    return qs.order_by("-ts")


@org_required
def deployment_logs(request, pk):
    """Structured, org-scoped log search/filter. HTMX-pollable fragment.

    Full page on a normal GET; if requested via HTMX (HX-Request header) returns
    just the table fragment so it can poll/refresh in place.
    """
    deployment = _get_org_deployment(request, pk)
    qs = _filter_logs(deployment, request.GET)

    paginator = Paginator(qs, 100)
    page = paginator.get_page(request.GET.get("page") or 1)

    # Preserve current filters on the polling fragment + pagination links.
    filters = {
        k: request.GET.get(k, "")
        for k in ("q", "level", "status", "method", "path")
    }
    querystring = "&".join(f"{k}={v}" for k, v in filters.items() if v)

    ctx = {
        "deployment": deployment,
        "page": page,
        "logs": page.object_list,
        "filters": filters,
        "querystring": querystring,
    }
    if request.headers.get("HX-Request"):
        return render(request, "observability/_logs.html", ctx)
    return render(request, "observability/logs.html", ctx)


# --------------------------------------------------------------------------- #
# Live golden-signals dashboard (OBS-5)
# --------------------------------------------------------------------------- #
@org_required
def deployment_dashboard(request, pk):
    deployment = _get_org_deployment(request, pk)
    ctx = _dep_dashboard_ctx(deployment)
    return render(request, "observability/dashboard.html", ctx)


@org_required
def deployment_metrics(request, pk):
    """HTMX poll fragment: golden-signal stat tiles + sparklines (no full page)."""
    deployment = _get_org_deployment(request, pk)
    ctx = _dep_dashboard_ctx(deployment)
    return render(request, "observability/_metrics.html", ctx)


# --------------------------------------------------------------------------- #
# Monitors CRUD (OBS-6)
# --------------------------------------------------------------------------- #
def _monitor_form_ctx(request, monitor=None):
    return {
        "monitor": monitor,
        "metric_choices": Monitor.Metric.choices,
        "comparator_choices": Monitor.Comparator.choices,
        "severity_choices": Monitor.Severity.choices,
        "deployments": _org_deployments(request).order_by(
            "environment__project__name"
        ),
    }


def _apply_monitor_form(request, monitor):
    """Populate a Monitor from POST data, scoped to request.org. Returns errors."""
    errors = []
    data = request.POST

    monitor.name = (data.get("name") or "").strip()[:200]

    metric = data.get("metric")
    if metric in dict(Monitor.Metric.choices):
        monitor.metric = metric
    else:
        errors.append("Invalid metric.")

    comparator = data.get("comparator")
    if comparator in dict(Monitor.Comparator.choices):
        monitor.comparator = comparator
    else:
        errors.append("Invalid comparator.")

    severity = data.get("severity")
    if severity in dict(Monitor.Severity.choices):
        monitor.severity = severity
    else:
        errors.append("Invalid severity.")

    try:
        monitor.threshold = float(data.get("threshold"))
    except (TypeError, ValueError):
        errors.append("Threshold must be a number.")

    try:
        monitor.window_minutes = max(1, int(data.get("window_minutes") or 5))
    except (TypeError, ValueError):
        errors.append("Window must be an integer.")

    monitor.enabled = data.get("enabled") in ("on", "true", "1", "yes")

    dep_id = data.get("deployment")
    if dep_id:
        dep = _org_deployments(request).filter(pk=dep_id).first()
        if dep is None:
            errors.append("Unknown deployment.")
        else:
            monitor.deployment = dep
    else:
        monitor.deployment = None

    # Always scope to the current org.
    monitor.org = request.org
    return errors


@org_required
def monitor_list(request):
    monitors = (
        Monitor.objects.for_org(request.org)
        .select_related("deployment__environment__project")
    )
    return render(
        request, "observability/monitor_list.html", {"monitors": monitors}
    )


@org_required
def monitor_new(request):
    if request.method == "POST":
        monitor = Monitor()
        errors = _apply_monitor_form(request, monitor)
        if errors:
            for e in errors:
                messages.error(request, e)
            ctx = _monitor_form_ctx(request, monitor)
            ctx["errors"] = errors
            return render(request, "observability/monitor_form.html", ctx)
        monitor.save()
        Event.log(
            f"Monitor created: {monitor}",
            actor=request.user.get_username(),
            level="info",
            icon="alert",
        )
        messages.success(request, "Monitor created.")
        return redirect("observability:monitor_list")
    return render(
        request, "observability/monitor_form.html", _monitor_form_ctx(request)
    )


@org_required
def monitor_edit(request, pk):
    monitor = get_object_or_404(Monitor.objects.for_org(request.org), pk=pk)
    if request.method == "POST":
        errors = _apply_monitor_form(request, monitor)
        if errors:
            for e in errors:
                messages.error(request, e)
            ctx = _monitor_form_ctx(request, monitor)
            ctx["errors"] = errors
            return render(request, "observability/monitor_form.html", ctx)
        monitor.save()
        messages.success(request, "Monitor updated.")
        return redirect("observability:monitor_list")
    return render(
        request,
        "observability/monitor_form.html",
        _monitor_form_ctx(request, monitor),
    )


@org_required
def monitor_delete(request, pk):
    monitor = get_object_or_404(Monitor.objects.for_org(request.org), pk=pk)
    if request.method == "POST":
        monitor.delete()
        messages.success(request, "Monitor deleted.")
        return redirect("observability:monitor_list")
    return render(
        request, "observability/monitor_confirm_delete.html", {"monitor": monitor}
    )
