"""Worktrees & headless Claude agents.  [OWNER: Slice B agent]

Spawns `claude -p` headless sessions inside isolated git worktrees, streams
their output into AgentRun.output, and (for feature/remediation work) opens a
PullRequest from the resulting commits. Keep these signatures stable.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import uuid
from pathlib import Path

from django.conf import settings
from django.db.models import F, Value
from django.db.models.functions import Concat
from django.utils import timezone
from django.utils.text import slugify

from core.models import Event

from .models import AgentRun, Worktree

GIT_USER_NAME = "Hull Agent"
GIT_USER_EMAIL = "agent@helm.dev"


# ---------------------------------------------------------------------------
# Worktrees
# ---------------------------------------------------------------------------


def _git(repo: str, *args, check=True, **kw):
    """Run a git command inside ``repo`` and return CompletedProcess."""
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
        check=check,
        **kw,
    )


def create_worktree(project, name: str, *, base_branch: str | None = None):
    """Create a git worktree off ``base_branch`` (default project.default_branch).

    The worktree lives at HELM_WORKTREES_DIR/<project.slug>/<name> on a fresh
    branch ``agent/<slug(name)>-<short-rand>``. Returns the Worktree.
    """
    repo = project.local_path
    base = base_branch or project.default_branch or "main"
    short = uuid.uuid4().hex[:6]
    name_slug = slugify(name) or "task"
    branch = f"agent/{name_slug}-{short}"

    wt_dir = Path(settings.HELM_WORKTREES_DIR) / project.slug / f"{name_slug}-{short}"
    wt_dir.parent.mkdir(parents=True, exist_ok=True)

    worktree = Worktree.objects.create(
        project=project,
        name=name,
        branch=branch,
        base_branch=base,
        path=str(wt_dir),
        status=Worktree.Status.CREATING,
    )

    try:
        _git(repo, "worktree", "add", "-b", branch, str(wt_dir), base)
        base_commit = _git(repo, "rev-parse", base).stdout.strip()
        worktree.base_commit = base_commit
        worktree.status = Worktree.Status.ACTIVE
        worktree.save(update_fields=["base_commit", "status"])
    except subprocess.CalledProcessError as e:
        worktree.status = Worktree.Status.ARCHIVED
        worktree.save(update_fields=["status"])
        Event.log(
            f"failed to create worktree {branch}: {e.stderr or e}",
            project=project,
            actor="helm",
            level="error",
            icon="git",
        )
        raise

    Event.log(
        f"created worktree on branch {branch} (off {base})",
        project=project,
        actor="helm",
        level="info",
        icon="git",
    )
    return worktree


# ---------------------------------------------------------------------------
# stream-json parsing helpers
# ---------------------------------------------------------------------------


def _summarize_assistant(msg: dict) -> list[str]:
    """Turn an assistant message into concise human-readable lines."""
    out = []
    content = msg.get("content") or []
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            text = (block.get("text") or "").strip()
            if text:
                out.append(text)
        elif btype == "tool_use":
            name = block.get("name", "tool")
            inp = block.get("input") or {}
            label = _tool_label(name, inp)
            out.append(f"⚙ {label}")
    return out


def _tool_label(name: str, inp: dict) -> str:
    if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        target = inp.get("file_path") or inp.get("path") or ""
        return f"{name} {os.path.basename(target) or target}".strip()
    if name == "Read":
        target = inp.get("file_path") or ""
        return f"Read {os.path.basename(target) or target}".strip()
    if name == "Bash":
        cmd = (inp.get("command") or "").strip().replace("\n", " ")
        if len(cmd) > 80:
            cmd = cmd[:80] + "…"
        return f"Bash: {cmd}"
    if name in ("Grep", "Glob"):
        pat = inp.get("pattern") or inp.get("query") or ""
        return f"{name} {pat}"
    return name


def _summarize_tool_result(msg: dict) -> list[str]:
    out = []
    content = msg.get("content") or []
    if isinstance(content, str):
        content = [{"type": "tool_result", "content": content}]
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_result":
            raw = block.get("content")
            if isinstance(raw, list):
                parts = [b.get("text", "") for b in raw if isinstance(b, dict)]
                raw = " ".join(parts)
            raw = (raw or "").strip().replace("\n", " ")
            if len(raw) > 120:
                raw = raw[:120] + "…"
            if raw:
                out.append(f"  ↳ {raw}")
    return out


def _handle_event(event: dict, agent_run: AgentRun) -> tuple[list[str], dict | None]:
    """Return (lines_to_append, result_dict_or_None)."""
    etype = event.get("type")
    lines: list[str] = []
    result = None

    if etype == "system":
        sub = event.get("subtype", "")
        if sub == "init":
            model = event.get("model", "")
            lines.append(f"● session started{f' · {model}' if model else ''}")
    elif etype == "assistant":
        lines.extend(_summarize_assistant(event.get("message") or event))
    elif etype == "user":
        lines.extend(_summarize_tool_result(event.get("message") or event))
    elif etype == "result":
        result = event
    return lines, result


# ---------------------------------------------------------------------------
# Agent execution
# ---------------------------------------------------------------------------


def run_agent(agent_run) -> None:
    """Blocking execution of an AgentRun via the headless claude CLI."""
    worktree = agent_run.worktree
    project = agent_run.project
    open_pr = getattr(agent_run, "_open_pr", True)

    AgentRun.objects.filter(pk=agent_run.pk).update(
        status=AgentRun.Status.RUNNING, started_at=timezone.now()
    )
    agent_run.status = AgentRun.Status.RUNNING
    Event.log(
        f"agent started: {agent_run.title}",
        project=project,
        actor="claude-agent",
        level="info",
        icon="agent",
        url=f"/agents/{agent_run.pk}/",
    )

    cmd = [
        settings.HELM_CLAUDE_BIN,
        "-p",
        agent_run.prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "acceptEdits",
        "--dangerously-skip-permissions",
        "--model",
        settings.HELM_AGENT_MODEL,
    ]

    result_event: dict | None = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=worktree.path,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for raw_line in proc.stdout:
            raw_line = raw_line.rstrip("\n")
            if not raw_line.strip():
                continue
            try:
                event = json.loads(raw_line)
            except (json.JSONDecodeError, ValueError):
                # Non-JSON line — surface it raw but keep going.
                _append(agent_run, raw_line)
                continue
            if not isinstance(event, dict):
                continue
            lines, res = _handle_event(event, agent_run)
            for ln in lines:
                _append(agent_run, ln)
            if res is not None:
                result_event = res
        proc.wait()

        # Capture result metadata.
        result_summary = ""
        num_turns = 0
        cost = None
        if result_event:
            result_summary = (
                result_event.get("result")
                or result_event.get("subtype")
                or ""
            )
            num_turns = result_event.get("num_turns", 0) or 0
            cost = (
                result_event.get("total_cost_usd")
                if result_event.get("total_cost_usd") is not None
                else result_event.get("cost_usd")
            )

        # Commit any changes the agent made.
        commit_sha = _commit_changes(worktree, agent_run.title)
        if commit_sha:
            _append(agent_run, f"✓ committed {commit_sha[:8]}")
            Event.log(
                f"agent committed changes ({commit_sha[:8]})",
                project=project,
                actor="claude-agent",
                level="info",
                icon="git",
            )

        # Open a PR for feature/remediation runs that produced a commit.
        pr = None
        if (
            commit_sha
            and open_pr
            and agent_run.kind
            in (AgentRun.Kind.FEATURE, AgentRun.Kind.REMEDIATION)
        ):
            try:
                from vcs.services import open_pull_request

                pr = open_pull_request(
                    worktree,
                    title=agent_run.title,
                    description=result_summary or agent_run.prompt[:500],
                    base_branch=worktree.base_branch,
                    agent_run=agent_run,
                )
            except NotImplementedError:
                pr = None
            except Exception as e:  # noqa: BLE001
                _append(agent_run, f"⚠ PR creation failed: {e}")

        # Persist final state.
        agent_run.refresh_from_db(fields=["output"])
        agent_run.status = AgentRun.Status.DONE
        agent_run.ended_at = timezone.now()
        agent_run.result_summary = result_summary
        agent_run.num_turns = num_turns
        agent_run.cost_usd = cost
        if pr:
            agent_run.pull_request = pr
        agent_run.save(
            update_fields=[
                "status",
                "ended_at",
                "result_summary",
                "num_turns",
                "cost_usd",
                "pull_request",
            ]
        )

        if pr and agent_run.incident_id:
            try:
                inc = agent_run.incident
                inc.remediation_pr = pr
                inc.save(update_fields=["remediation_pr"])
            except Exception:  # noqa: BLE001
                pass

        Event.log(
            f"agent finished: {agent_run.title}"
            + (f" · {num_turns} turns" if num_turns else "")
            + (f" · ${cost:.4f}" if cost else ""),
            project=project,
            actor="claude-agent",
            level="success",
            icon="check",
            url=f"/agents/{agent_run.pk}/",
        )
    except Exception as e:  # noqa: BLE001
        _append(agent_run, f"✗ error: {e}")
        AgentRun.objects.filter(pk=agent_run.pk).update(
            status=AgentRun.Status.FAILED,
            ended_at=timezone.now(),
            error=str(e),
        )
        agent_run.status = AgentRun.Status.FAILED
        Event.log(
            f"agent failed: {agent_run.title} — {e}",
            project=project,
            actor="claude-agent",
            level="error",
            icon="x",
            url=f"/agents/{agent_run.pk}/",
        )


def _append(agent_run, text: str) -> None:
    """Append a line to AgentRun.output, persisting just that field for live tail."""
    chunk = text.rstrip("\n") + "\n"
    # NB: use Concat (not F + str) — SQLite's `+` coerces to numbers, turning
    # an empty TextField into 0 instead of concatenating.
    AgentRun.objects.filter(pk=agent_run.pk).update(
        output=Concat(F("output"), Value(chunk))
    )


def _commit_changes(worktree, title: str) -> str | None:
    """git add -A; commit if there are changes. Returns the commit sha or None."""
    repo = worktree.path
    _git(repo, "add", "-A", check=False)
    status = _git(repo, "status", "--porcelain", check=False).stdout.strip()
    if not status:
        return None
    _git(
        repo,
        "-c",
        f"user.name={GIT_USER_NAME}",
        "-c",
        f"user.email={GIT_USER_EMAIL}",
        "commit",
        "-m",
        title or "agent changes",
        check=False,
    )
    return _git(repo, "rev-parse", "HEAD", check=False).stdout.strip() or None


# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------


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
    """Create an AgentRun (QUEUED). Create a worktree if needed. Optionally
    dispatch execution in the background. Returns the AgentRun.
    """
    if worktree is None:
        worktree = create_worktree(project, slugify(title) or "task", base_branch=base_branch)

    agent_run = AgentRun.objects.create(
        project=project,
        worktree=worktree,
        kind=kind,
        title=title,
        prompt=prompt,
        incident=incident,
        status=AgentRun.Status.QUEUED,
    )
    # Transient intent — whether to open a PR after the run.
    agent_run._open_pr = open_pr

    Event.log(
        f"queued {kind} agent: {title}",
        project=project,
        actor="helm",
        level="info",
        icon="agent",
        url=f"/agents/{agent_run.pk}/",
    )

    if dispatch:
        try:
            from orchestration.service import run_feature_agent

            run_feature_agent(agent_run.id)
        except NotImplementedError:
            _dispatch_thread(agent_run)
        except ImportError:
            _dispatch_thread(agent_run)

    return agent_run


def _dispatch_thread(agent_run) -> None:
    """Fallback: run the agent on a daemon thread."""
    t = threading.Thread(target=run_agent, args=(agent_run,), daemon=True)
    t.start()
