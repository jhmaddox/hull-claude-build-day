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


_ALLOWED_WINDOWS = (1, 5, 15, 60)


def _clamp_window(params, default=5):
    """Read ``window`` from GET params and clamp to a valid choice.

    Bogus values (``abc``, ``9999``, negatives) never 500 — they fall back to a
    value in ``{1,5,15,60}`` (the requested default, or the nearest allowed).
    """
    raw = params.get("window")
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return default
    if val in _ALLOWED_WINDOWS:
        return val
    # Out-of-set but numeric: snap to the nearest allowed window.
    return min(_ALLOWED_WINDOWS, key=lambda w: abs(w - val))


# OBS-14: soft default thresholds for the presentational health banner. Used
# only when no enabled monitor supplies a tighter bound. Purely cosmetic — opens
# no incidents and does not touch services.
_SOFT_ERROR_RATE = 5.0   # percent
_SOFT_P95_MS = 1000.0    # milliseconds


def _health_banner(deployment, rolled):
    """Compute a presentational health banner for a deployment dashboard.

    Returns a dict ``{level, message}`` where level is 'ok'|'warn'|'danger'.
    A breach is when current error_rate/p95 exceeds the matching enabled
    monitor's threshold (if any) or the soft default. Never opens incidents.
    """
    error_rate = rolled.get("error_rate") or 0.0
    p95 = rolled.get("p95")

    err_threshold = _SOFT_ERROR_RATE
    p95_threshold = _SOFT_P95_MS
    try:
        for mon in Monitor.objects.filter(deployment=deployment, enabled=True):
            if mon.metric == Monitor.Metric.ERROR_RATE:
                err_threshold = min(err_threshold, mon.threshold)
            elif mon.metric == Monitor.Metric.P95:
                p95_threshold = min(p95_threshold, mon.threshold)
    except Exception:
        pass

    problems = []
    if error_rate > err_threshold:
        problems.append(f"error rate {error_rate}% > {err_threshold}%")
    if p95 is not None and p95 > p95_threshold:
        problems.append(f"p95 {p95}ms > {p95_threshold}ms")

    if problems:
        return {"level": "danger", "message": "Degraded — " + "; ".join(problems)}
    return {"level": "ok", "message": "Healthy — golden signals within thresholds."}


def _dep_dashboard_ctx(deployment, window_minutes=5):
    rolled = services.rollups(deployment, window_minutes=window_minutes)
    req_series = _deployment_metric_series(deployment, "requests")
    err_series = _deployment_metric_series(deployment, "errors")
    lat_series = _deployment_metric_series(deployment, "latency_ms")
    return {
        "deployment": deployment,
        "window_minutes": window_minutes,
        "rollups": rolled,
        "health_banner": _health_banner(deployment, rolled),
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
    # Aggregate golden-signal fleet summary (request.org-scoped, empty -> zeros).
    total_req_rate = 0.0
    total_throughput = 0
    total_errors = 0
    worst_p95 = None
    for dep in live:
        req_series = _deployment_metric_series(dep, "requests")
        err_series = _deployment_metric_series(dep, "errors")
        recent_errors = list(
            dep.logs.filter(level=LogLine.Level.ERROR).order_by("-ts")[:6]
        )
        try:
            rolled = services.rollups(dep)
        except Exception:
            rolled = {"req_rate": 0.0, "throughput": 0, "p95": None}
        total_req_rate += rolled.get("req_rate") or 0.0
        total_throughput += int(rolled.get("throughput") or 0)
        total_errors += int(sum(err_series))
        p95 = rolled.get("p95")
        if p95 is not None and (worst_p95 is None or p95 > worst_p95):
            worst_p95 = p95
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

    open_incidents = (
        _org_incidents(request)
        .exclude(status=Incident.Status.RESOLVED)
        .select_related("project")
    )
    # Firing monitors = org monitors whose derived live status is 'alerting'.
    firing_monitors = sum(
        1
        for m in Monitor.objects.for_org(request.org)
        if m.live_status() == "alerting"
    )
    summary = {
        "total_req_rate": round(total_req_rate, 2),
        "total_throughput": total_throughput,
        "total_errors": total_errors,
        "worst_p95": worst_p95,
        "firing_monitors": firing_monitors,
        "open_incidents": open_incidents.count(),
        "live_deployments": len(cards),
    }

    ctx = {
        "cards": cards,
        "summary": summary,
        "open_incidents": open_incidents[:8],
    }
    return render(request, "observability/overview.html", ctx)


@org_required
def incident_list(request):
    incidents = _org_incidents(request).select_related("project", "remediation_pr")
    ctx = {
        "incidents": incidents,
        "open_count": incidents.exclude(status=Incident.Status.RESOLVED).count(),
        "severity_choices": Incident.Severity.choices,
        "projects": _org_projects(request),
    }
    return render(request, "observability/incident_list.html", ctx)


def _org_projects(request):
    """Projects belonging to the request's org (for the declare form)."""
    from projects.models import Project

    return Project.objects.for_org(request.org).order_by("name")


@org_required
def incident_declare(request):
    """OBS-1: manually declare an incident via create_manual_incident.

    POST fields: project, severity, title, message. The project must belong to
    request.org (else 404). Delegates to the NEW service entry point so the
    declared incident gets a timeline + (if auto-remediate is on) can kick the
    loop — identical to auto-detected incidents.
    """
    if request.method != "POST":
        return redirect("observability:incident_list")

    project = get_object_or_404(
        _org_projects(request), pk=request.POST.get("project") or 0
    )
    severity = request.POST.get("severity") or "sev2"
    title = (request.POST.get("title") or "").strip()
    message = (request.POST.get("message") or "").strip()

    if not title:
        messages.error(request, "A title is required to declare an incident.")
        return redirect("observability:incident_list")

    incident = services.create_manual_incident(
        project,
        severity=severity,
        title=title,
        message=message,
        declared_by=request.user.get_username(),
    )
    messages.success(
        request, f"Declared INC-{incident.number}: {incident.title}."
    )
    return redirect(incident.get_absolute_url())


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


def _next_url(request, incident):
    """Where to redirect after an inline/detail incident action.

    Honours an explicit ?next= (e.g. inline on the list) else the detail page.
    """
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and nxt.startswith("/"):
        return nxt
    return incident.get_absolute_url()


@org_required
def incident_ack(request, pk):
    """OBS-10: acknowledge an incident from the UI (status=acknowledged).

    Sets ``acknowledged_at`` and emits a timeline ``core.Event`` (matched by the
    detail view's ``INC-<number>`` filter). Org-scoped; never auto-resolves.
    """
    incident = get_object_or_404(_org_incidents(request), pk=pk)
    if request.method != "POST":
        return redirect(_next_url(request, incident))

    if incident.status in (
        Incident.Status.RESOLVED,
        Incident.Status.ACKNOWLEDGED,
    ):
        messages.error(
            request, f"INC-{incident.number} is already {incident.get_status_display()}."
        )
    else:
        from django.utils import timezone

        incident.status = Incident.Status.ACKNOWLEDGED
        incident.acknowledged_at = timezone.now()
        incident.save(update_fields=["status", "acknowledged_at"])
        Event.log(
            f"INC-{incident.number} acknowledged",
            project=incident.project,
            actor=request.user.get_username(),
            level="warning",
            icon="incident",
            url=incident.get_absolute_url(),
        )
        messages.success(request, f"INC-{incident.number} acknowledged.")
    return redirect(_next_url(request, incident))


@org_required
def incident_resolve(request, pk):
    """OBS-10: manually resolve an incident from the UI (status=resolved).

    Sets ``resolved_at`` + emits a timeline ``core.Event``. This is the manual
    path only — it must NOT go through the monitor recovery code, so it never
    touches any other incident.
    """
    incident = get_object_or_404(_org_incidents(request), pk=pk)
    if request.method != "POST":
        return redirect(_next_url(request, incident))

    if incident.status == Incident.Status.RESOLVED:
        messages.error(request, f"INC-{incident.number} is already resolved.")
    else:
        from django.utils import timezone

        incident.status = Incident.Status.RESOLVED
        incident.resolved_at = timezone.now()
        incident.save(update_fields=["status", "resolved_at"])
        Event.log(
            f"INC-{incident.number} resolved manually",
            project=incident.project,
            actor=request.user.get_username(),
            level="success",
            icon="check",
            url=incident.get_absolute_url(),
        )
        # Best-effort oncall timeline/postmortem hook (never blocks).
        try:
            from oncall.services import loop as _oncall_loop

            _oncall_loop.on_incident_resolved(incident)
        except Exception as exc:  # noqa: BLE001
            print(f"[helm-obs] oncall on_incident_resolved hook failed: {exc}")
        messages.success(request, f"INC-{incident.number} resolved.")
    return redirect(_next_url(request, incident))


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


# Cap export size so a pathological deployment can't stream an unbounded file.
_LOG_EXPORT_CAP = 10000


@org_required
def deployment_logs_export(request, pk):
    """OBS-13: stream the currently-filtered logs as CSV.

    Honours the same q/level/status/method/path params as ``deployment_logs``
    (reusing ``_filter_logs``), org-scoped (cross-org 404), capped at
    ``_LOG_EXPORT_CAP`` rows. Columns: ts, level, method, path, status_code,
    latency_ms, message.
    """
    import csv

    from django.http import StreamingHttpResponse

    deployment = _get_org_deployment(request, pk)
    qs = _filter_logs(deployment, request.GET).values_list(
        "ts", "level", "method", "path", "status_code", "latency_ms", "message"
    )[:_LOG_EXPORT_CAP]

    class _Echo:
        def write(self, value):
            return value

    writer = csv.writer(_Echo())
    header = (
        "ts", "level", "method", "path", "status_code", "latency_ms", "message",
    )

    def _rows():
        yield writer.writerow(header)
        for ts, level, method, path, status_code, latency_ms, message in qs:
            yield writer.writerow(
                [
                    ts.isoformat() if ts else "",
                    level,
                    method,
                    path,
                    status_code if status_code is not None else "",
                    latency_ms if latency_ms is not None else "",
                    (message or "").replace("\n", " ").replace("\r", " "),
                ]
            )

    resp = StreamingHttpResponse(_rows(), content_type="text/csv")
    resp["Content-Disposition"] = (
        f'attachment; filename="helm-logs-deployment-{deployment.pk}.csv"'
    )
    return resp


# --------------------------------------------------------------------------- #
# Live golden-signals dashboard (OBS-5)
# --------------------------------------------------------------------------- #
@org_required
def deployment_dashboard(request, pk):
    deployment = _get_org_deployment(request, pk)
    window = _clamp_window(request.GET)
    ctx = _dep_dashboard_ctx(deployment, window_minutes=window)
    ctx["window_choices"] = _ALLOWED_WINDOWS
    return render(request, "observability/dashboard.html", ctx)


@org_required
def deployment_metrics(request, pk):
    """HTMX poll fragment: golden-signal stat tiles + sparklines (no full page)."""
    deployment = _get_org_deployment(request, pk)
    window = _clamp_window(request.GET)
    ctx = _dep_dashboard_ctx(deployment, window_minutes=window)
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
def monitor_mute(request, pk):
    """POST mute/snooze (e.g. ?minutes=30). minutes=0 clears the mute.

    Scoped to ``Monitor.objects.for_org(request.org)`` so muting another org's
    monitor 404s. Sets ``muted_until = now + minutes`` (time-based, auto-expires)
    and narrates via ``core.Event``.
    """
    from django.utils import timezone

    monitor = get_object_or_404(Monitor.objects.for_org(request.org), pk=pk)
    if request.method != "POST":
        return redirect("observability:monitor_list")

    raw = request.POST.get("minutes") or request.GET.get("minutes") or "30"
    try:
        minutes = int(raw)
    except (TypeError, ValueError):
        minutes = 30
    minutes = max(0, min(minutes, 60 * 24 * 7))  # clamp to <= 1 week

    if minutes == 0:
        monitor.muted_until = None
        monitor.save(update_fields=["muted_until"])
        Event.log(
            f"Monitor unmuted: {monitor}",
            actor=request.user.get_username(),
            level="info",
            icon="alert",
        )
        messages.success(request, "Monitor unmuted.")
    else:
        monitor.muted_until = timezone.now() + timezone.timedelta(minutes=minutes)
        monitor.save(update_fields=["muted_until"])
        Event.log(
            f"Monitor muted {minutes}m: {monitor}",
            actor=request.user.get_username(),
            level="info",
            icon="alert",
        )
        messages.success(request, f"Monitor muted for {minutes} minutes.")
    return redirect("observability:monitor_list")


@org_required
def monitor_toggle(request, pk):
    """OBS-9: POST flip a monitor's ``enabled`` without opening the edit form.

    Org-scoped (cross-org 404), narrated via ``core.Event``. Does NOT touch
    ``evaluate_monitors`` — a disabled monitor is simply excluded by its
    ``enabled=True`` filter, and ``live_status()`` reflects the new state.
    """
    monitor = get_object_or_404(Monitor.objects.for_org(request.org), pk=pk)
    if request.method != "POST":
        return redirect("observability:monitor_list")

    monitor.enabled = not monitor.enabled
    monitor.save(update_fields=["enabled"])
    Event.log(
        f"Monitor {'enabled' if monitor.enabled else 'disabled'}: {monitor}",
        actor=request.user.get_username(),
        level="info",
        icon="alert",
    )
    messages.success(
        request,
        f"Monitor {'enabled' if monitor.enabled else 'disabled'}.",
    )
    return redirect("observability:monitor_list")


@org_required
def monitor_detail(request, pk):
    """OBS-12: per-monitor detail showing THIS monitor's breach history.

    Lists only MonitorBreach incidents matching this monitor's
    ``breach_signature`` (open + resolved) so an operator can see flap history.
    Never shows traceback/suspect_file incidents. Org-scoped via for_org.
    """
    monitor = get_object_or_404(
        Monitor.objects.for_org(request.org).select_related(
            "deployment__environment__project"
        ),
        pk=pk,
    )
    breaches = []
    try:
        sig = monitor.breach_signature()
        breaches = list(
            Incident.objects.filter(
                error_type="MonitorBreach", signature=sig
            ).order_by("-created_at")[:25]
        )
    except Exception:
        breaches = []
    ctx = {
        "monitor": monitor,
        "breaches": breaches,
        "open_breaches": sum(
            1 for b in breaches if b.status != Incident.Status.RESOLVED
        ),
    }
    return render(request, "observability/monitor_detail.html", ctx)


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
