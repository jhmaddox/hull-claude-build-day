from django.contrib import messages
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render

from accounts.scoping import org_required, visible
from projects.models import Project

from . import services
from .models import AgentRun


@org_required
def agent_list(request):
    runs = (
        visible(AgentRun, request)
        .select_related("project", "worktree", "pull_request")
    )

    # Org-scoped filters (?status= ?kind= ?project=).
    status = request.GET.get("status") or ""
    kind = request.GET.get("kind") or ""
    project = request.GET.get("project") or ""

    valid_statuses = {c for c, _ in AgentRun.Status.choices}
    valid_kinds = {c for c, _ in AgentRun.Kind.choices}

    if status in valid_statuses:
        runs = runs.filter(status=status)
    else:
        status = ""
    if kind in valid_kinds:
        runs = runs.filter(kind=kind)
    else:
        kind = ""
    if project.isdigit():
        runs = runs.filter(project_id=int(project))
    else:
        project = ""

    ctx = {
        "runs": runs[:100],
        "running": visible(AgentRun, request)
        .filter(status=AgentRun.Status.RUNNING)
        .count(),
        "status_choices": AgentRun.Status.choices,
        "kind_choices": AgentRun.Kind.choices,
        "projects": visible(Project, request).order_by("name"),
        "f_status": status,
        "f_kind": kind,
        "f_project": project,
        "has_filters": bool(status or kind or project),
    }
    return render(request, "agents/list.html", ctx)


@org_required
def agent_new(request):
    projects = visible(Project, request).order_by("name")
    if request.method == "POST":
        # Reject launching against a project outside the current org.
        project = get_object_or_404(
            visible(Project, request), pk=request.POST.get("project")
        )
        kind = request.POST.get("kind") or AgentRun.Kind.FEATURE
        title = (request.POST.get("title") or "").strip()
        prompt = (request.POST.get("prompt") or "").strip()
        if not title or not prompt:
            messages.error(request, "Title and prompt are required.")
        else:
            run = services.launch_agent(
                project,
                kind=kind,
                title=title,
                prompt=prompt,
                open_pr=True,
                dispatch=True,
            )
            messages.success(request, f"Agent launched: {title}")
            return redirect("agents:detail", pk=run.pk)
    ctx = {
        "projects": projects,
        "kinds": AgentRun.Kind.choices,
    }
    return render(request, "agents/new.html", ctx)


@org_required
def agent_detail(request, pk):
    run = get_object_or_404(
        visible(AgentRun, request).select_related(
            "project", "worktree", "pull_request", "incident"
        ),
        pk=pk,
    )
    return render(request, "agents/detail.html", {"run": run})


@org_required
def agent_stream(request, pk):
    """HTMX fragment: just the live-tailing logs block."""
    run = get_object_or_404(visible(AgentRun, request), pk=pk)

    # Support incremental append: client tells us how many bytes it already has.
    try:
        since = int(request.GET.get("since") or 0)
    except (TypeError, ValueError):
        since = 0
    full = run.output or ""
    delta = full[since:] if 0 <= since <= len(full) else full
    ctx = {"run": run, "delta": delta, "since": len(full), "oob": True}
    return render(request, "agents/_stream.html", ctx)


@org_required
def agent_roster(request):
    """Per-kind roster of agent activity for the current org."""
    runs = visible(AgentRun, request)

    agg = {
        row["kind"]: row
        for row in runs.values("kind").annotate(
            total=Count("id"),
            running=Count(
                "id",
                filter=Q(
                    status__in=[
                        AgentRun.Status.QUEUED,
                        AgentRun.Status.RUNNING,
                    ]
                ),
            ),
            done=Count("id", filter=Q(status=AgentRun.Status.DONE)),
            failed=Count("id", filter=Q(status=AgentRun.Status.FAILED)),
            spend=Sum("cost_usd"),
        )
    }

    roster = []
    for value, label in AgentRun.Kind.choices:
        row = agg.get(value, {})
        roster.append(
            {
                "kind": value,
                "label": label,
                "total": row.get("total", 0) or 0,
                "running": row.get("running", 0) or 0,
                "done": row.get("done", 0) or 0,
                "failed": row.get("failed", 0) or 0,
                "spend": row.get("spend") or 0,
            }
        )

    totals = runs.aggregate(
        total=Count("id"),
        running=Count(
            "id",
            filter=Q(
                status__in=[AgentRun.Status.QUEUED, AgentRun.Status.RUNNING]
            ),
        ),
        spend=Sum("cost_usd"),
    )
    ctx = {
        "roster": roster,
        "total": totals.get("total") or 0,
        "running": totals.get("running") or 0,
        "spend": totals.get("spend") or 0,
    }
    return render(request, "agents/roster.html", ctx)
