"""Git-backed pull requests.  [OWNER: Slice B agent]

PRs are real branches in the project repo. Diffs are computed with git.
Keep these signatures stable.
"""

from __future__ import annotations


def next_pr_number(project) -> int:
    """Return the next per-project PR number (max existing + 1, starting at 1)."""
    raise NotImplementedError


def open_pull_request(
    worktree,
    *,
    title: str,
    description: str = "",
    base_branch: str | None = None,
    agent_run=None,
):
    """Push/record the worktree branch as a PullRequest against base_branch
    (default = worktree.base_branch). Compute the diff via
    ``git diff base...head`` and populate diff/files_changed/additions/
    deletions/head_commit. ci_status starts as NONE. Returns the PullRequest
    (or None if there is no diff). Logs a core.Event.
    """
    raise NotImplementedError


def refresh_diff(pr) -> None:
    """Recompute pr.diff and stats from git for the current branch heads."""
    raise NotImplementedError


def merge_pull_request(pr) -> bool:
    """Merge pr.head_branch into pr.base_branch in the project repo (no-ff),
    set status=MERGED + merged_at, mark the worktree MERGED, log a core.Event.
    Returns True on success. Callers may then trigger a redeploy of the env
    tracking base_branch.
    """
    raise NotImplementedError
