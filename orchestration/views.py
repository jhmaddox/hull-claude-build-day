import re

from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.scoping import org_required, scoped

from . import refs
from .models import WorkflowRun

# Kinds the list/table filter understands (derived from ref_type/name).
_KIND_CHOICES = ("import", "deploy", "agent_run", "ci", "incident")
_STATUS_CHOICES = ("running", "done", "failed")


def _apply_filters(runs, request):
    """Apply optional ?status= and ?kind= AFTER org scoping. [ORC-6]

    * ``status`` maps to WorkflowRun.Status (running|done|failed).
    * ``kind``  filters by the coarse WorkflowRun.kind (derived from
      ref_type/name) - in Python so it works regardless of how kind is
      computed. Absent/unknown params -> unfiltered. Returns
      (queryset_or_list, active_filters dict).
    """
    active = {}

    status = (request.GET.get("status") or "").strip().lower()
    if status in _STATUS_CHOICES:
        runs = runs.filter(status=status)
        active["status"] = status

    kind = (request.GET.get("kind") or "").strip().lower()
    if kind in _KIND_CHOICES:
        runs = [r for r in runs if r.kind == kind]
        active["kind"] = kind

    return runs, active


def _limit(runs, n=100):
    """Cap a queryset or list to ``n`` rows (slice happens AFTER filtering)."""
    return runs[:n]


def _decorate(runs, request):
    """Attach a resolved cross-link to each row for the templates. [ORC-7]

    Org-scoped via request.org; rows without a resolvable ref get ``link=None``
    and keep working.
    """
    out = []
    for r in runs:
        try:
            r.link = refs.resolve(r, request)
        except Exception:  # noqa: BLE001 - decoration must never break the list
            r.link = None
        out.append(r)
    return out


def _loop_health(org):
    """Crown-jewel autonomous-loop KPIs for ``org``. [ORCHESTRATION-20]

    Returns a dict with four metrics computed from org-scoped Incident +
    in-process remediation state:

    * ``auto_resolved``   — incidents the loop drove to RESOLVED.
    * ``mttr_label``      — mean time-to-resolve (acknowledged→resolved), human
      string ("—" when none).
    * ``success_rate``    — % of attempted remediations that resolved (resolved
      vs. attempts that did not), 0–100.
    * ``remediating_now`` — incidents currently remediating per ``is_remediating``.

    Degrades to zeros/"—" if a table is missing or a query fails. Never raises.
    """
    health = {
        "auto_resolved": 0,
        "mttr_label": "—",
        "mttr_seconds": 0,
        "success_rate": 0,
        "attempts": 0,
        "remediating_now": 0,
    }
    try:
        from observability.models import Incident

        incs = Incident.objects.filter(org=org)

        resolved = list(
            incs.filter(status=Incident.Status.RESOLVED)
            .exclude(acknowledged_at__isnull=True)
            .exclude(resolved_at__isnull=True)
        )
        health["auto_resolved"] = incs.filter(
            status=Incident.Status.RESOLVED
        ).count()

        # MTTR over resolved incidents that carry both timestamps.
        if resolved:
            total = sum(
                (i.resolved_at - i.acknowledged_at).total_seconds()
                for i in resolved
            )
            mttr = total / len(resolved)
            health["mttr_seconds"] = mttr
            health["mttr_label"] = _humanize_seconds(mttr)

        # Success rate: resolved vs. all incidents that have been picked up by
        # the loop (acknowledged at least once). An acknowledged incident that
        # is not resolved is a failed/incomplete remediation attempt.
        attempts = incs.exclude(acknowledged_at__isnull=True).count()
        health["attempts"] = attempts
        if attempts:
            health["success_rate"] = round(
                100.0 * health["auto_resolved"] / attempts
            )

        # Currently remediating (in-process guard ∪ REMEDIATING status).
        remediating = 0
        try:
            from . import service

            for inc_id in incs.filter(
                status=Incident.Status.REMEDIATING
            ).values_list("pk", flat=True):
                remediating += 1
            # Also count any guarded-but-not-yet-status-flipped runs in-org.
            for inc_id in incs.exclude(
                status=Incident.Status.REMEDIATING
            ).values_list("pk", flat=True):
                if service.is_remediating(inc_id):
                    remediating += 1
        except Exception:  # noqa: BLE001
            remediating = incs.filter(
                status=Incident.Status.REMEDIATING
            ).count()
        health["remediating_now"] = remediating
    except Exception:  # noqa: BLE001 - degrade to zeros if anything is missing
        pass
    return health


def _humanize_seconds(secs):
    """Compact human duration ("42s", "7m", "2h 13m")."""
    try:
        secs = int(secs)
    except Exception:  # noqa: BLE001
        return "—"
    if secs < 60:
        return f"{secs}s"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m"
    hrs = mins // 60
    rem = mins % 60
    return f"{hrs}h {rem}m" if rem else f"{hrs}h"


# A run's name may carry a sprint/batch tag like "[sprint:auth-v2] feature ...".
# We derive the grouping from name (no schema change) so a sprint of N feature
# agents collapses under one header. [ORCHESTRATION-23]
_SPRINT_RE = re.compile(r"\[(?:sprint|batch)[:=]\s*([^\]]+)\]", re.IGNORECASE)


def _sprint_tag(run):
    """Return a sprint/batch tag for ``run`` or None (ungrouped). Never raises."""
    try:
        m = _SPRINT_RE.search(run.name or "")
        if m:
            return m.group(1).strip()
    except Exception:  # noqa: BLE001
        return None
    return None


def _group_runs(runs):
    """Group decorated runs into sprint batches, preserving order. [ORCHESTRATION-23]

    Returns a list of dicts: ungrouped rows render as ``{"group": False,
    "run": <run>}``; runs sharing a sprint tag collapse into one
    ``{"group": True, "tag": <tag>, "runs": [...], "counts": {...}}`` header
    placed at the position of the batch's first run. Ungrouped runs are
    unaffected. Never raises — falls back to all-ungrouped on error.
    """
    try:
        out = []
        by_tag = {}  # tag -> its group entry (placed at first occurrence)
        for r in runs:
            tag = _sprint_tag(r)
            if not tag:
                out.append({"group": False, "run": r})
                continue
            entry = by_tag.get(tag)
            if entry is None:
                entry = {
                    "group": True,
                    "tag": tag,
                    "runs": [],
                    "counts": {"running": 0, "done": 0, "failed": 0, "total": 0},
                }
                by_tag[tag] = entry
                out.append(entry)  # header sits at the batch's first run
            entry["runs"].append(r)
            c = entry["counts"]
            c["total"] += 1
            if r.status == WorkflowRun.Status.RUNNING:
                c["running"] += 1
            elif r.status == WorkflowRun.Status.DONE:
                c["done"] += 1
            elif r.status == WorkflowRun.Status.FAILED:
                c["failed"] += 1
        return out
    except Exception:  # noqa: BLE001
        return [{"group": False, "run": r} for r in runs]


@org_required
def workflow_list(request):
    """Org-scoped autonomous-build overview + workflow run table."""
    org_runs = WorkflowRun.objects.for_org(request.org)

    base = org_runs.select_related("project")
    filtered, active = _apply_filters(base, request)
    runs = _decorate(_limit(filtered), request)
    groups = _group_runs(runs)

    stats = {
        "total": org_runs.count(),
        "running": org_runs.filter(status=WorkflowRun.Status.RUNNING).count(),
        "succeeded": org_runs.filter(status=WorkflowRun.Status.DONE).count(),
        "failed": org_runs.filter(status=WorkflowRun.Status.FAILED).count(),
        "resolved_incidents": 0,
    }
    # Auto-resolved incidents tell the autonomous-build story (best-effort).
    try:
        from observability.models import Incident

        stats["resolved_incidents"] = Incident.objects.filter(
            status="resolved", project__org=request.org
        ).count()
    except Exception:  # noqa: BLE001
        pass

    ctx = {
        "runs": runs,
        "groups": groups,
        "stats": stats,
        "health": _loop_health(request.org),
        "running_count": stats["running"],
        "active": active,
        "kind_choices": _KIND_CHOICES,
        "status_choices": _STATUS_CHOICES,
    }
    return render(request, "orchestration/workflow_list.html", ctx)


@org_required
def workflow_table(request):
    """HTMX-polled fragment of the org-scoped workflow run table.

    Honors the same ?status=/?kind= params as workflow_list so live polling
    keeps the active filter. [ORC-6]
    """
    base = WorkflowRun.objects.for_org(request.org).select_related("project")
    filtered, active = _apply_filters(base, request)
    runs = _decorate(_limit(filtered), request)
    return render(
        request,
        "orchestration/_workflow_table.html",
        {"runs": runs, "groups": _group_runs(runs), "active": active},
    )


def _parse_steps(detail):
    """Parse run.detail text into timeline steps. Tolerant of empty input. [ORC-3]

    Each non-blank line becomes a step. We classify a coarse level from common
    markers so the feed icon/colour matches, defaulting to info.
    """
    steps = []
    for raw in (detail or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        low = line.lower()
        if any(m in low for m in ("error", "failed", "traceback", "exception")):
            level, icon = "error", "x"
        elif any(m in low for m in ("resolved", "passed", "completed", "merged", "green")):
            level, icon = "success", "check"
        elif any(m in low for m in ("warning", "warn", "skipped")):
            level, icon = "warning", "alert"
        else:
            level, icon = "info", "log"
        steps.append({"text": line.strip(), "level": level, "icon": icon})
    return steps


def _inline_agent(run, request):
    """Most-recent in-org AgentRun for this workflow's entity/project. [ORC-5]

    Returns an AgentRun (read-only) whose output we can tail inline, or None.
    Strictly org-scoped (AgentRun subclasses OrgScopedModel) so another org's
    output is never shown. Never raises.
    """
    org = getattr(request, "org", None)
    if org is None:
        return None
    try:
        from agents.models import AgentRun

        qs = AgentRun.objects.for_org(org)

        # Prefer the directly-linked agent run when the workflow points at one.
        if (run.ref_type or "") == "agent_run" and run.ref_id:
            ar = qs.filter(pk=run.ref_id).first()
            if ar is not None:
                return ar

        # If the linked entity is an incident, prefer that incident's agent run.
        link = refs.resolve(run, request)
        if link and getattr(link, "kind", "") == "Incident":
            ar = qs.filter(incident=link.object).order_by("-created_at").first()
            if ar is not None:
                return ar

        # Else the most-recent agent run on the run's project.
        if run.project_id:
            return (
                qs.filter(project_id=run.project_id)
                .order_by("-created_at")
                .first()
            )
    except Exception:  # noqa: BLE001 - inline output is best-effort
        return None
    return None


def _detail_context(request, pk):
    run = get_object_or_404(
        scoped(WorkflowRun, request).select_related("project"), pk=pk
    )
    return {
        "run": run,
        "link": refs.resolve(run, request),
        "steps": _parse_steps(run.detail),
        "agent": _inline_agent(run, request),
    }


@org_required
def workflow_detail(request, pk):
    # Look up within the org-scoped queryset so a foreign-org pk -> 404.
    return render(
        request, "orchestration/workflow_detail.html", _detail_context(request, pk)
    )


@org_required
def workflow_detail_panel(request, pk):
    """HTMX fragment: live timeline + inline agent output while running. [ORC-4]"""
    return render(
        request,
        "orchestration/_workflow_detail_panel.html",
        _detail_context(request, pk),
    )


@org_required
def activity(request):
    """Live agent-org activity surface (org-scoped)."""
    return render(request, "orchestration/activity.html", _activity_context(request))


@org_required
def activity_panel(request):
    """HTMX fragment of the live activity panel (org-scoped)."""
    return render(
        request, "orchestration/_activity_panel.html", _activity_context(request)
    )


def _activity_context(request):
    """Build the running-now context scoped to request.org."""
    workflows = list(
        WorkflowRun.objects.for_org(request.org)
        .filter(status=WorkflowRun.Status.RUNNING)
        .select_related("project")[:50]
    )
    workflows = _decorate(workflows, request)
    agents = []
    try:
        from agents.models import AgentRun

        # AgentRun is org-scoped (OrgScopedModel); use for_org for tenancy.
        agents = list(
            AgentRun.objects.for_org(request.org)
            .filter(status=AgentRun.Status.RUNNING)
            .select_related("project", "worktree")[:50]
        )
    except Exception:  # noqa: BLE001
        agents = []

    return {
        "workflows": workflows,
        "agents": agents,
        "live_count": len(workflows) + len(agents),
    }


# --------------------------------------------------------------------------- #
# Agent-org dashboard [ORCHESTRATION-19]
# --------------------------------------------------------------------------- #
def _agents_context(request):
    """Org-scoped snapshot of the autonomous crew for the dashboard.

    Lists recent + running AgentRuns (org-scoped via for_org) with swarm summary
    tiles (running/queued/done counts + total cost_usd). Best-effort: if the
    agents app/table is missing, returns empty tiles and never raises.
    """
    agents = []
    tiles = {"running": 0, "queued": 0, "done": 0, "failed": 0, "total_cost": 0.0}
    try:
        from agents.models import AgentRun

        qs = AgentRun.objects.for_org(request.org).select_related(
            "project", "worktree"
        )
        # Summary counts over the whole org (not just the shown page).
        tiles["running"] = qs.filter(status=AgentRun.Status.RUNNING).count()
        tiles["queued"] = qs.filter(status=AgentRun.Status.QUEUED).count()
        tiles["done"] = qs.filter(status=AgentRun.Status.DONE).count()
        tiles["failed"] = qs.filter(status=AgentRun.Status.FAILED).count()
        total = 0.0
        for c in qs.values_list("cost_usd", flat=True):
            if c:
                total += c
        tiles["total_cost"] = round(total, 2)

        # Show running first, then most-recent, capped for the live view.
        running = list(qs.filter(status=AgentRun.Status.RUNNING)[:50])
        running_ids = {a.pk for a in running}
        recent = [
            a for a in qs.order_by("-created_at")[:60] if a.pk not in running_ids
        ]
        agents = running + recent
    except Exception:  # noqa: BLE001 - dashboard degrades, never 500s
        agents = []
    return {"agents": agents, "tiles": tiles, "agent_count": len(agents)}


@org_required
def agents_dashboard(request):
    """Live, org-scoped view of the autonomous crew. [ORCHESTRATION-19]"""
    return render(
        request, "orchestration/agents.html", _agents_context(request)
    )


@org_required
def agents_panel(request):
    """HTMX fragment of the agent-org dashboard (org-scoped). [ORCHESTRATION-19]"""
    return render(
        request, "orchestration/_agents_panel.html", _agents_context(request)
    )


# --------------------------------------------------------------------------- #
# Manual remediation trigger [ORCHESTRATION-21]
# --------------------------------------------------------------------------- #
@org_required
@require_POST
def remediate_incident(request, incident_id):
    """Kick the autonomous loop for an in-org incident, then redirect to the run.

    Org-scoped + CSRF-protected (POST). Honors the per-incident re-entrancy
    guard: a double-click yields a single run (``service.remediate`` returns
    None for the second call, so we redirect to the most-recent run for that
    incident instead of starting another). A cross-org incident -> 404.
    [ORCHESTRATION-21]
    """
    from observability.models import Incident

    # Scope strictly to request.org so a foreign-org incident is a 404.
    inc = get_object_or_404(
        Incident.objects.filter(org=request.org), pk=incident_id
    )

    from . import service

    run = service.remediate(inc.pk)
    if run is not None:
        return redirect("orchestration:workflow_detail", pk=run.pk)

    # Already remediating (guard) or no project — land on the live run if any.
    existing = (
        WorkflowRun.objects.for_org(request.org)
        .filter(ref_type="incident", ref_id=inc.pk)
        .order_by("-created_at")
        .first()
    )
    if existing is not None:
        return redirect("orchestration:workflow_detail", pk=existing.pk)
    # Nothing to show (e.g. incident vanished) — back to the index.
    return redirect("orchestration:workflow_list")
