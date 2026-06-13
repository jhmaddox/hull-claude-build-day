from django.shortcuts import get_object_or_404, render

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


@org_required
def workflow_list(request):
    """Org-scoped autonomous-build overview + workflow run table."""
    org_runs = WorkflowRun.objects.for_org(request.org)

    base = org_runs.select_related("project")
    filtered, active = _apply_filters(base, request)
    runs = _decorate(_limit(filtered), request)

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
        "stats": stats,
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
        {"runs": runs, "active": active},
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
