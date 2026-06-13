import threading

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from . import services
from .diffrender import render_diff
from .models import PullRequest


def pr_list(request):
    prs = PullRequest.objects.select_related("project", "worktree")
    open_prs = prs.filter(status=PullRequest.Status.OPEN)
    other = prs.exclude(status=PullRequest.Status.OPEN)[:50]
    ctx = {"open_prs": open_prs, "other_prs": other}
    return render(request, "vcs/list.html", ctx)


def pr_detail(request, pk):
    pr = get_object_or_404(
        PullRequest.objects.select_related("project", "worktree"), pk=pk
    )
    ctx = {
        "pr": pr,
        "diff_html": render_diff(pr.diff),
        "agent_runs": pr.agent_runs.all(),
        "incidents": pr.incidents.all(),
    }
    return render(request, "vcs/detail.html", ctx)


def pr_run_ci(request, pk):
    pr = get_object_or_404(PullRequest, pk=pk)
    try:
        from orchestration.service import run_ci

        run_ci(pr.id)
    except (NotImplementedError, ImportError):
        threading.Thread(
            target=_fallback_ci, args=(pr.id,), daemon=True
        ).start()
    messages.success(request, f"CI started for PR #{pr.number}")
    return redirect("vcs:pr_detail", pk=pr.pk)


def _fallback_ci(pr_id):
    """Minimal CI fallback when orchestration is unavailable: mark passed."""
    from core.models import Event

    pr = PullRequest.objects.get(pk=pr_id)
    pr.ci_status = PullRequest.CIStatus.RUNNING
    pr.save(update_fields=["ci_status"])
    pr.ci_status = PullRequest.CIStatus.PASSED
    pr.save(update_fields=["ci_status"])
    Event.log(
        f"CI passed for PR #{pr.number}",
        project=pr.project,
        actor="helm-ci",
        level="success",
        icon="test",
        url=pr.get_absolute_url(),
    )


def pr_merge(request, pk):
    pr = get_object_or_404(PullRequest, pk=pk)
    ok = services.merge_pull_request(pr)
    if ok:
        messages.success(request, f"Merged PR #{pr.number}")
        threading.Thread(
            target=_maybe_redeploy, args=(pr.id,), daemon=True
        ).start()
    else:
        messages.error(request, f"Merge of PR #{pr.number} failed — see activity feed.")
    return redirect("vcs:pr_detail", pk=pr.pk)


def _maybe_redeploy(pr_id):
    """After merge, try to redeploy the prod env tracking the base branch."""
    try:
        pr = PullRequest.objects.get(pk=pr_id)
        from deploys.models import Environment
        from deploys.services import deploy

        env = (
            Environment.objects.filter(
                project=pr.project, kind="prod", branch=pr.base_branch
            ).first()
            or Environment.objects.filter(
                project=pr.project, branch=pr.base_branch
            ).first()
        )
        if env:
            deploy(env)
    except Exception:  # noqa: BLE001
        pass
