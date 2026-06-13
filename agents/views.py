from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from projects.models import Project

from . import services
from .models import AgentRun


def agent_list(request):
    runs = AgentRun.objects.select_related("project", "worktree", "pull_request")[:100]
    ctx = {
        "runs": runs,
        "running": AgentRun.objects.filter(status=AgentRun.Status.RUNNING).count(),
    }
    return render(request, "agents/list.html", ctx)


def agent_new(request):
    if request.method == "POST":
        project = get_object_or_404(Project, pk=request.POST.get("project"))
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
        "projects": Project.objects.all(),
        "kinds": AgentRun.Kind.choices,
    }
    return render(request, "agents/new.html", ctx)


def agent_detail(request, pk):
    run = get_object_or_404(
        AgentRun.objects.select_related(
            "project", "worktree", "pull_request", "incident"
        ),
        pk=pk,
    )
    return render(request, "agents/detail.html", {"run": run})


def agent_stream(request, pk):
    """HTMX fragment: just the live-tailing logs block."""
    run = get_object_or_404(AgentRun, pk=pk)
    return render(request, "agents/_stream.html", {"run": run})
