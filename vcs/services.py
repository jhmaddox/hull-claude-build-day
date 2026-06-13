"""Git-backed pull requests.  [OWNER: Slice B agent]

PRs are real branches in the project repo. Diffs are computed with git.
Keep these signatures stable.
"""

from __future__ import annotations

import subprocess

from django.db.models import Max
from django.utils import timezone

from core.models import Event

from .models import PullRequest


def _git(repo: str, *args, check=False):
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
        check=check,
    )


def next_pr_number(project) -> int:
    """Next per-project PR number (max existing + 1, starting at 1)."""
    current = project.pull_requests.aggregate(m=Max("number"))["m"] or 0
    return current + 1


def _compute_diff(repo: str, base: str, head: str):
    """Return (diff_text, files_changed, additions, deletions)."""
    diff = _git(repo, "diff", f"{base}...{head}").stdout
    numstat = _git(repo, "diff", "--numstat", f"{base}...{head}").stdout
    files = additions = deletions = 0
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        add, dele, _path = parts
        files += 1
        if add.isdigit():
            additions += int(add)
        if dele.isdigit():
            deletions += int(dele)
    return diff, files, additions, deletions


def open_pull_request(
    worktree,
    *,
    title: str,
    description: str = "",
    base_branch: str | None = None,
    agent_run=None,
):
    """Record the worktree branch as a PullRequest against base_branch.

    Returns the PullRequest, or None if there is no diff.
    """
    project = worktree.project
    repo = project.local_path
    base = base_branch or worktree.base_branch
    head = worktree.branch

    diff, files, additions, deletions = _compute_diff(repo, base, head)
    if not diff.strip():
        Event.log(
            f"no diff for {head} — PR not opened",
            project=project,
            actor="helm",
            level="warning",
            icon="pr",
        )
        return None

    head_commit = _git(repo, "rev-parse", head).stdout.strip()

    pr = PullRequest.objects.create(
        project=project,
        worktree=worktree,
        number=next_pr_number(project),
        title=title,
        description=description,
        base_branch=base,
        head_branch=head,
        head_commit=head_commit,
        status=PullRequest.Status.OPEN,
        ci_status=PullRequest.CIStatus.NONE,
        author="claude-agent",
        diff=diff,
        files_changed=files,
        additions=additions,
        deletions=deletions,
    )

    Event.log(
        f"opened PR #{pr.number}: {title} (+{additions} −{deletions} · {files} files)",
        project=project,
        actor="claude-agent",
        level="success",
        icon="pr",
        url=pr.get_absolute_url(),
    )
    return pr


def refresh_diff(pr) -> None:
    """Recompute pr.diff and stats from git for the current branch heads."""
    repo = pr.project.local_path
    diff, files, additions, deletions = _compute_diff(repo, pr.base_branch, pr.head_branch)
    pr.diff = diff
    pr.files_changed = files
    pr.additions = additions
    pr.deletions = deletions
    head_commit = _git(repo, "rev-parse", pr.head_branch).stdout.strip()
    if head_commit:
        pr.head_commit = head_commit
    pr.save(
        update_fields=[
            "diff",
            "files_changed",
            "additions",
            "deletions",
            "head_commit",
        ]
    )


def merge_pull_request(pr) -> bool:
    """Merge pr.head_branch into pr.base_branch (no-ff) in the project repo.

    Sets status=MERGED + merged_at, marks the worktree MERGED, logs an Event.
    Returns True on success.
    """
    if pr.status == PullRequest.Status.MERGED:
        return True

    repo = pr.project.local_path

    co = _git(repo, "checkout", pr.base_branch)
    if co.returncode != 0:
        Event.log(
            f"merge of PR #{pr.number} failed: cannot checkout {pr.base_branch} — {co.stderr.strip()}",
            project=pr.project,
            actor="helm",
            level="error",
            icon="merge",
            url=pr.get_absolute_url(),
        )
        return False

    merge = _git(
        repo,
        "-c",
        "user.name=Helm",
        "-c",
        "user.email=helm@helm.dev",
        "merge",
        "--no-ff",
        pr.head_branch,
        "-m",
        f"Merge PR #{pr.number}: {pr.title}",
    )
    if merge.returncode != 0:
        # Abort a half-done merge so the repo stays clean.
        _git(repo, "merge", "--abort")
        Event.log(
            f"merge of PR #{pr.number} failed: {merge.stderr.strip() or merge.stdout.strip()}",
            project=pr.project,
            actor="helm",
            level="error",
            icon="merge",
            url=pr.get_absolute_url(),
        )
        return False

    pr.status = PullRequest.Status.MERGED
    pr.merged_at = timezone.now()
    pr.save(update_fields=["status", "merged_at"])

    if pr.worktree_id:
        wt = pr.worktree
        wt.status = wt.Status.MERGED
        wt.save(update_fields=["status"])

    Event.log(
        f"merged PR #{pr.number}: {pr.title} → {pr.base_branch}",
        project=pr.project,
        actor="helm",
        level="success",
        icon="merge",
        url=pr.get_absolute_url(),
    )
    return True
