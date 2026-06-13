"""Worktrees & headless Claude agents.  [OWNER: Slice B agent]

Spawns `claude -p` headless sessions inside isolated git worktrees, streams
their output into AgentRun.output, and (for feature/remediation work) opens a
PullRequest from the resulting commits. Keep these signatures stable.
"""

from __future__ import annotations


def create_worktree(project, name: str, *, base_branch: str | None = None):
    """Create a git worktree off ``base_branch`` (default project.default_branch)
    at settings.HELM_WORKTREES_DIR/<project.slug>/<name>, on a new branch
    ``agent/<name>``. Populate Worktree(path, branch, base_branch, base_commit,
    status=ACTIVE). Returns the Worktree.
    """
    raise NotImplementedError


def launch_agent(
    project,
    *,
    kind: str,
    title: str,
    prompt: str,
    worktree=None,
    incident=None,
    base_branch: str | None = None,
    open_pr: bool = True,
    dispatch: bool = True,
):
    """Create an AgentRun (status=QUEUED). If ``worktree`` is None, create one.
    If ``dispatch`` is True, run it via orchestration (Temporal or threaded
    fallback) in the background and return immediately. Returns the AgentRun.
    """
    raise NotImplementedError


def run_agent(agent_run) -> None:
    """Blocking execution of an AgentRun.

    Runs ``claude -p <prompt> --output-format stream-json --verbose
    --permission-mode acceptEdits --model <HELM_AGENT_MODEL>`` (and
    --dangerously-skip-permissions in this sandboxed env) with cwd =
    worktree.path. Parse the streamed JSON events, append human-readable lines
    to AgentRun.output as they arrive (so the UI can tail it), and capture
    result_summary, num_turns, cost_usd at the end. Then: git add -A &&
    git commit if there are changes. If kind in (feature, remediation) and
    open_pr, call vcs.services.open_pull_request(...) and link it on the run
    and on the incident. Set status=DONE/FAILED, started_at/ended_at, and log
    core.Event entries throughout.
    """
    raise NotImplementedError
