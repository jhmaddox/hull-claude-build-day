from django.shortcuts import get_object_or_404, render

from accounts.scoping import org_required, scoped

from .models import WorkflowRun


@org_required
def workflow_list(request):
    """Org-scoped autonomous-build overview + workflow run table."""
    org_runs = WorkflowRun.objects.for_org(request.org)
    runs = org_runs.select_related("project")[:100]

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
    }
    return render(request, "orchestration/workflow_list.html", ctx)


@org_required
def workflow_table(request):
    """HTMX-polled fragment of the org-scoped workflow run table."""
    runs = (
        WorkflowRun.objects.for_org(request.org)
        .select_related("project")[:100]
    )
    return render(request, "orchestration/_workflow_table.html", {"runs": runs})


@org_required
def workflow_detail(request, pk):
    # Look up within the org-scoped queryset so a foreign-org pk -> 404.
    run = get_object_or_404(
        scoped(WorkflowRun, request).select_related("project"), pk=pk
    )
    return render(request, "orchestration/workflow_detail.html", {"run": run})


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
    workflows = (
        WorkflowRun.objects.for_org(request.org)
        .filter(status=WorkflowRun.Status.RUNNING)
        .select_related("project")[:50]
    )
    agents = []
    try:
        from agents.models import AgentRun

        # AgentRun has no org of its own; derive org via project (read-only).
        agents = list(
            AgentRun.objects.filter(
                status=AgentRun.Status.RUNNING, project__org=request.org
            ).select_related("project", "worktree")[:50]
        )
    except Exception:  # noqa: BLE001
        agents = []

    return {
        "workflows": workflows,
        "agents": agents,
        "live_count": workflows.count() + len(agents),
    }
