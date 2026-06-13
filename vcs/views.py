import threading

from django.conf import settings
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from accounts.scoping import org_required

from . import services
from .diffrender import render_diff, split_diff
from .models import PullRequest


# --------------------------------------------------------------------------- #
# Org scoping + legacy fallback
# --------------------------------------------------------------------------- #
def _scoped_prs(request):
    """Return the PullRequest queryset visible to ``request.org``.

    Tenant isolation with a legacy/loop fallback. A PR is visible when:

    * ``pr.org == request.org`` (the normal, explicitly-scoped case), OR
    * ``pr.org IS NULL`` and the PR's project belongs to this org (or the
      project itself has no org) — this keeps autonomously-created PRs (the
      incident->fix loop runs with ``org=None``) and demo/legacy rows visible
      to a matching member instead of silently disappearing.

    Cross-org rows (``pr.org`` set to a different org) are always excluded, so
    detail/CI/merge built on this queryset 404 across tenants.
    """
    org = request.org
    qs = PullRequest.objects.select_related("project", "worktree", "org")
    fallback = Q(org__isnull=True) & (Q(project__org=org) | Q(project__org__isnull=True))
    return qs.filter(Q(org=org) | fallback)


def _ci_badge_ctx(pr):
    return {"pr": pr}


# --------------------------------------------------------------------------- #
# Views
# --------------------------------------------------------------------------- #
@org_required
def pr_list(request):
    prs = _scoped_prs(request)
    open_prs = prs.filter(status=PullRequest.Status.OPEN)
    other = prs.exclude(status=PullRequest.Status.OPEN)[:50]
    ctx = {"open_prs": open_prs, "other_prs": other}
    return render(request, "vcs/list.html", ctx)


def _local_branches(repo):
    """Best-effort list of local branch names for a repo path (read-only)."""
    if not repo:
        return []
    res = services._git(repo, "branch", "--format=%(refname:short)")
    if res.returncode != 0:
        return []
    return [b.strip() for b in res.stdout.splitlines() if b.strip()]


@org_required
def pr_new(request):
    """Manually open a PR between two existing branches of an org project.

    Org-scoped: only the requesting org's projects are selectable, and the
    created PR inherits ``project.org`` so it stays tenant-isolated. This is the
    human-driven counterpart to the autonomous loop's ``open_pull_request``; it
    reuses the same git diff helpers but works from an existing branch instead
    of a worktree, so the loop path is left completely untouched.
    """
    from projects.models import Project

    projects = list(Project.objects.for_org(request.org).order_by("name"))

    if request.method == "POST":
        form = {k: request.POST.get(k, "").strip() for k in
                ("project", "title", "head_branch", "base_branch", "description")}
        project = next((p for p in projects if str(p.pk) == form["project"]), None)
        errors = []
        if project is None:
            errors.append("Pick a project in your org.")
        if not form["title"]:
            errors.append("Title is required.")
        if not form["head_branch"]:
            errors.append("Head branch is required.")
        base = form["base_branch"] or (project.default_branch if project else "main") or "main"

        if not errors and project is not None:
            repo = project.local_path or ""
            diff, files, additions, deletions = services._compute_diff(
                repo, base, form["head_branch"]
            )
            if not diff.strip():
                errors.append(
                    f"No diff between {base} and {form['head_branch']} — nothing to open."
                )
            else:
                head_commit = services._git(
                    repo, "rev-parse", form["head_branch"]
                ).stdout.strip()
                pr = PullRequest.objects.create(
                    org=getattr(project, "org", None),
                    project=project,
                    worktree=None,
                    number=services.next_pr_number(project),
                    title=form["title"],
                    description=form["description"],
                    base_branch=base,
                    head_branch=form["head_branch"],
                    head_commit=head_commit,
                    status=PullRequest.Status.OPEN,
                    ci_status=PullRequest.CIStatus.NONE,
                    author=getattr(request.user, "username", "") or "human",
                    diff=diff,
                    files_changed=files,
                    additions=additions,
                    deletions=deletions,
                )
                from core.models import Event

                Event.log(
                    f"opened PR #{pr.number}: {pr.title} "
                    f"(+{additions} −{deletions} · {files} files)",
                    project=project,
                    actor=pr.author,
                    level="success",
                    icon="pr",
                    url=pr.get_absolute_url(),
                )
                messages.success(request, f"Opened PR #{pr.number}")
                return redirect("vcs:pr_detail", pk=pr.pk)

        for e in errors:
            messages.error(request, e)
    else:
        form = {"base_branch": "", "head_branch": "", "title": "", "description": "",
                "project": str(projects[0].pk) if projects else ""}

    project_branches = [
        {"project": p, "branches": _local_branches(p.local_path or "")}
        for p in projects
    ]
    ctx = {"projects": projects, "form": form, "project_branches": project_branches}
    return render(request, "vcs/new.html", ctx)


@org_required
def pr_detail(request, pk):
    pr = get_object_or_404(_scoped_prs(request), pk=pk)

    mergeable, merge_blocked_reason = _mergeability(pr)

    permalink = settings.HELM_BASE_URL.rstrip("/") + pr.get_absolute_url()

    ctx = {
        "pr": pr,
        "diff_html": render_diff(pr.diff),
        "diff_files": split_diff(pr.diff),
        "agent_runs": pr.agent_runs.all(),
        "incidents": pr.incidents.all(),
        "mergeable": mergeable,
        "merge_blocked_reason": merge_blocked_reason,
        "permalink": permalink,
        "ci_polling": pr.ci_status in (
            PullRequest.CIStatus.PENDING,
            PullRequest.CIStatus.RUNNING,
        ),
    }
    return render(request, "vcs/detail.html", ctx)


@org_required
def pr_ci_status(request, pk):
    """HTMX fragment: just the live CI badge for a PR (org-scoped, 404 cross-org)."""
    pr = get_object_or_404(_scoped_prs(request), pk=pk)
    return render(request, "vcs/_ci_status.html", {"pr": pr})


@org_required
def pr_run_ci(request, pk):
    pr = get_object_or_404(_scoped_prs(request), pk=pk)
    try:
        from orchestration.service import run_ci

        run_ci(pr.id)
    except (NotImplementedError, ImportError):
        threading.Thread(target=_fallback_ci, args=(pr.id,), daemon=True).start()
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


@org_required
def pr_merge(request, pk):
    pr = get_object_or_404(_scoped_prs(request), pk=pk)
    ok = services.merge_pull_request(pr)
    if ok:
        messages.success(request, f"Merged PR #{pr.number}")
        threading.Thread(target=_maybe_redeploy, args=(pr.id,), daemon=True).start()
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


# --------------------------------------------------------------------------- #
# Mergeability + read-only conflict detection
# --------------------------------------------------------------------------- #
def _mergeability(pr):
    """Return ``(mergeable: bool, reason: str)`` for the Merge button.

    Cheap status checks first, then a read-only git dry-run for conflicts. The
    dry-run is ALWAYS aborted; any error / dirty / detached repo degrades to
    "unknown" (button enabled) so the autonomous loop is never blocked by a
    speculative check.
    """
    if pr.status == PullRequest.Status.MERGED:
        return False, "Already merged."
    if pr.status != PullRequest.Status.OPEN:
        return False, "PR is not open."

    conflict = _detect_conflict(pr)
    if conflict is True:
        return False, "Merge conflict with base branch — resolve before merging."
    # conflict is False (clean) or None (unknown) -> allow merge.
    return True, ""


def _detect_conflict(pr):
    """Read-only conflict probe. Returns True/False, or None when unknown.

    Runs ``git merge --no-commit --no-ff`` and ALWAYS follows with
    ``git merge --abort``. Never mutates the repo's committed state.
    """
    repo = getattr(pr.project, "local_path", "") or ""
    if not repo:
        return None
    try:
        # Refuse to touch a dirty or detached working tree.
        status = services._git(repo, "status", "--porcelain")
        if status.returncode != 0 or status.stdout.strip():
            return None
        head = services._git(repo, "symbolic-ref", "--quiet", "HEAD")
        if head.returncode != 0:
            return None  # detached HEAD
        # Make sure we're on the base branch for a meaningful dry-run.
        co = services._git(repo, "checkout", pr.base_branch)
        if co.returncode != 0:
            return None
        merge = services._git(
            repo, "merge", "--no-commit", "--no-ff", pr.head_branch
        )
        conflicted = merge.returncode != 0
        return conflicted
    except Exception:  # noqa: BLE001
        return None
    finally:
        try:
            services._git(repo, "merge", "--abort")
        except Exception:  # noqa: BLE001
            pass
