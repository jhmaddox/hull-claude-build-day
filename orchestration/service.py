"""Orchestration dispatcher.  [OWNER: Slice C agent]

Single entry point the rest of Hull calls to run durable, observable
workflows. Backed by Temporal when HELM_USE_TEMPORAL=1 and the server is
reachable; otherwise falls back to a threaded in-process runner so the product
always works. Keep these top-level functions stable — UI/services call them.

Each top-level function returns fast: it creates a WorkflowRun and dispatches
the real work to the background via ``_run``.
"""

from __future__ import annotations

import os
import threading
import traceback as _tb

from django.utils import timezone


# --------------------------------------------------------------------------- #
# Background runner
# --------------------------------------------------------------------------- #
def _temporal_available() -> bool:
    """True only if Temporal is requested AND the server is reachable."""
    from django.conf import settings

    if not getattr(settings, "HELM_USE_TEMPORAL", False):
        return False
    try:
        import socket

        host, _, port = settings.HELM_TEMPORAL_HOST.partition(":")
        with socket.create_connection((host, int(port or 7233)), timeout=1.0):
            return True
    except Exception:
        return False


def _run(name, fn, *, project=None, ref_type="", ref_id=None, temporal=None):
    """Create a WorkflowRun, run ``fn`` in the background, record the outcome.

    ``fn`` is a zero-arg callable that performs the actual work (thread path).
    ``temporal`` (optional) = (workflow_class_name, args_list): when Temporal is
    enabled and reachable, the workflow is started on the cluster and its result
    is awaited (the work runs in the worker, NOT here) — so it's durable and
    visible in Temporal Cloud. If Temporal is unavailable or the start fails, we
    fall back to running ``fn`` on a daemon thread. The WorkflowRun + a
    core.Event are updated on completion / failure.

    Returns the WorkflowRun immediately.
    """
    from core.models import Event

    from .models import WorkflowRun

    use_temporal = _temporal_available()

    # Org stamping (additive, fallback-safe). Resolve the org best-effort so a
    # request-less autonomous run still records org=None and never raises.
    org = None
    try:
        org = getattr(project, "org", None)
        if org is None:
            from accounts.models import get_current_org

            org = get_current_org()
    except Exception:  # noqa: BLE001
        org = None

    wf = WorkflowRun.objects.create(
        name=name,
        status=WorkflowRun.Status.RUNNING,
        org=org,
        project=project,
        ref_type=ref_type,
        ref_id=ref_id,
        backend="temporal" if use_temporal else "thread",
    )
    Event.log(
        f"started workflow {name}",
        project=project,
        actor="orchestrator",
        level="info",
        icon="deploy",
    )

    def _save_wf(fields):
        """Persist WorkflowRun bookkeeping, tolerating transient DB locks.

        On sqlite (tests + the demo) a background thread's commit can race the
        main connection and raise ``database is locked``. Under the full test
        suite many daemon threads contend at once, so we retry with backoff +
        jitter for several seconds. Retrying keeps a successful run from being
        mis-recorded as FAILED (or stuck RUNNING) — loop-safe.
        """
        import random
        import time

        from django.db import OperationalError

        attempts = 60  # ~ up to a few seconds of backoff, well under callers' waits
        for attempt in range(attempts):
            try:
                wf.save(update_fields=fields)
                return
            except OperationalError:
                if attempt == attempts - 1:
                    raise
                # Capped backoff with jitter so contending threads de-sync.
                time.sleep(min(0.05 * (attempt + 1), 0.25) + random.uniform(0, 0.03))

    def _body():
        # Each thread needs its own DB connection lifecycle.
        try:
            result = fn()
            wf.status = WorkflowRun.Status.DONE
            wf.ended_at = timezone.now()
            if result is not None and not wf.detail:
                wf.detail = str(result)[:10000]
            _save_wf(["status", "ended_at", "detail"])
            Event.log(
                f"workflow {name} completed",
                project=project,
                actor="orchestrator",
                level="success",
                icon="check",
            )
        except Exception as exc:  # noqa: BLE001
            err = "".join(_tb.format_exc())
            wf.status = WorkflowRun.Status.FAILED
            wf.ended_at = timezone.now()
            wf.detail = (wf.detail + "\n" + err)[:10000]
            try:
                _save_wf(["status", "ended_at", "detail"])
            except Exception:  # noqa: BLE001
                pass
            Event.log(
                f"workflow {name} failed: {exc}",
                project=project,
                actor="orchestrator",
                level="error",
                icon="x",
            )
        finally:
            from django.db import connection

            connection.close()

    def _temporal_body():
        """Start the workflow on the Temporal cluster and await its result.

        The actual work runs in the worker process (the activity), making the
        run durable + visible in Temporal Cloud. Falls back to the thread body
        if the cluster/worker can't be reached.
        """
        import asyncio

        from .temporal_client import connect, connection_label

        wf_cls_name, wf_args = temporal

        async def _go():
            client = await connect()
            from . import temporal_workflows as tw

            wf_cls = getattr(tw, wf_cls_name)
            handle = await client.start_workflow(
                wf_cls.run,
                args=wf_args,
                id=f"hull-{name.replace(' ', '-')}-{wf.pk}",
                task_queue=settings.HELM_TEMPORAL_TASK_QUEUE,
            )
            return await handle.result()

        try:
            result = asyncio.run(_go())
            wf.status = WorkflowRun.Status.DONE
            wf.ended_at = timezone.now()
            wf.detail = (f"[temporal:{connection_label()}] {result}")[:10000]
            _save_wf(["status", "ended_at", "detail"])
            Event.log(f"workflow {name} completed (Temporal)", project=project,
                      actor="orchestrator", level="success", icon="check")
        except Exception as exc:  # noqa: BLE001 — fall back to local thread
            Event.log(f"Temporal dispatch unavailable ({exc}); running locally",
                      project=project, actor="orchestrator", level="warning", icon="deploy")
            WorkflowRun.objects.filter(pk=wf.pk).update(backend="thread")
            _body()
        finally:
            from django.db import connection as _c
            _c.close()

    if use_temporal and temporal is not None:
        t = threading.Thread(target=_temporal_body, name=f"wf-{wf.pk}", daemon=True)
    else:
        t = threading.Thread(target=_body, name=f"wf-{wf.pk}", daemon=True)
    t.start()
    return wf


# --------------------------------------------------------------------------- #
# Public workflow entry points
# --------------------------------------------------------------------------- #
def import_project(name: str, repo_url: str, *, description: str = ""):
    """Background: projects.services.import_project then auto-deploy each env."""

    def _do():
        from deploys import services as deploy_svc
        from projects import services as proj_svc

        project = proj_svc.import_project(name, repo_url, description=description)
        if project is None:
            return "import returned no project"
        from projects.models import Project

        if project.status == Project.Status.FAILED:
            return f"import failed: {project.import_log[-500:]}"
        deployed = []
        for env in project.environments.all():
            try:
                deploy_svc.deploy(env)
                deployed.append(env.name)
            except Exception as exc:  # noqa: BLE001
                deployed.append(f"{env.name}=ERR({exc})")
        return f"imported {project.slug}; deployed: {', '.join(deployed)}"

    return _run(f"import {name}", _do)


def deploy(environment_id: int, *, commit_sha: str | None = None):
    """Background: deploys.services.deploy for the environment."""

    def _do():
        from deploys.models import Environment
        from deploys import services as deploy_svc

        env = Environment.objects.select_related("project").get(pk=environment_id)
        dep = deploy_svc.deploy(env, commit_sha=commit_sha)
        return f"deployed {env} -> {getattr(dep, 'status', '?')}"

    from deploys.models import Environment

    project = None
    try:
        project = Environment.objects.select_related("project").get(
            pk=environment_id
        ).project
    except Environment.DoesNotExist:
        pass
    return _run(
        f"deploy env#{environment_id}",
        _do,
        project=project,
        ref_type="environment",
        ref_id=environment_id,
        temporal=("DeployWorkflow", [environment_id, commit_sha]),
    )


def run_feature_agent(agent_run_id: int):
    """Background: agents.services.run_agent (creates worktree+PR as needed)."""

    def _do():
        from agents.models import AgentRun
        from agents import services as agent_svc

        run = AgentRun.objects.select_related("project").get(pk=agent_run_id)
        agent_svc.run_agent(run)
        run.refresh_from_db()
        return f"agent run #{run.pk} -> {run.status}"

    from agents.models import AgentRun

    project = None
    try:
        project = AgentRun.objects.select_related("project").get(
            pk=agent_run_id
        ).project
    except AgentRun.DoesNotExist:
        pass
    return _run(
        f"feature agent #{agent_run_id}",
        _do,
        project=project,
        ref_type="agent_run",
        ref_id=agent_run_id,
        temporal=("RunAgentWorkflow", [agent_run_id]),
    )


# --------------------------------------------------------------------------- #
# CI
# --------------------------------------------------------------------------- #
def _project_python(project) -> str:
    """Best-effort path to the project's interpreter.

    Prefers the per-project venv Hull's deploys layer provisions (which has the
    project's installed deps), then an in-repo venv, then the current
    interpreter.
    """
    import sys

    # The deploy layer installs the project's deps into this venv.
    try:
        from deploys.services import _venv_python

        cand = _venv_python(project)
        if os.path.isfile(cand):
            return cand
    except Exception:  # noqa: BLE001
        pass

    if project and project.local_path:
        for cand in (
            os.path.join(project.local_path, ".venv", "bin", "python"),
            os.path.join(project.local_path, "venv", "bin", "python"),
        ):
            if os.path.isfile(cand):
                return cand
    return sys.executable


def _clean_subprocess_env() -> dict:
    """A child-process env with Hull's own Django/venv vars removed, so the
    managed project loads ITS settings/interpreter, not Hull's."""
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    for key in ("DJANGO_SETTINGS_MODULE", "PYTHONPATH", "VIRTUAL_ENV"):
        env.pop(key, None)
    return env


def _ci_command(project, cwd) -> list[str]:
    py = _project_python(project)
    framework = (getattr(project, "framework", "") or "").lower()
    if framework == "django" or os.path.isfile(os.path.join(cwd, "manage.py")):
        return [py, "manage.py", "test", "--noinput"]
    return [py, "-m", "pytest", "-q"]


def run_ci(pull_request_id: int):
    """Run the project's tests in the PR worktree. Returns the WorkflowRun.

    The actual pass/fail is recorded on the PR (ci_status) and the WorkflowRun
    detail. ``_run_ci_inline`` is the blocking variant used by remediate.
    """

    def _do():
        ok = _run_ci_inline(pull_request_id)
        return f"ci {'PASSED' if ok else 'FAILED'}"

    from vcs.models import PullRequest

    project = None
    try:
        project = PullRequest.objects.select_related("project").get(
            pk=pull_request_id
        ).project
    except PullRequest.DoesNotExist:
        pass
    return _run(
        f"ci pr#{pull_request_id}",
        _do,
        project=project,
        ref_type="pull_request",
        ref_id=pull_request_id,
        temporal=("RunCIWorkflow", [pull_request_id]),
    )


def _run_ci_inline(pull_request_id: int) -> bool:
    """Blocking CI: run tests, set ci_status, log events. Returns pass/fail."""
    import subprocess

    from core.models import Event
    from vcs.models import PullRequest

    pr = PullRequest.objects.select_related("project", "worktree").get(
        pk=pull_request_id
    )
    project = pr.project
    cwd = None
    if pr.worktree and pr.worktree.path:
        cwd = pr.worktree.path
    elif project and project.local_path:
        cwd = project.local_path
    if cwd and project and getattr(project, "app_subdir", ""):
        candidate = os.path.join(cwd, project.app_subdir)
        if os.path.isdir(candidate):
            cwd = candidate

    pr.ci_status = PullRequest.CIStatus.RUNNING
    pr.save(update_fields=["ci_status"])
    Event.log(
        f"running CI for PR #{pr.number}",
        project=project,
        actor="ci",
        level="info",
        icon="test",
        url=pr.get_absolute_url(),
    )

    if not cwd or not os.path.isdir(cwd):
        pr.ci_status = PullRequest.CIStatus.FAILED
        pr.save(update_fields=["ci_status"])
        Event.log(
            f"CI for PR #{pr.number} could not locate worktree",
            project=project,
            actor="ci",
            level="error",
            icon="x",
            url=pr.get_absolute_url(),
        )
        return False

    cmd = _ci_command(project, cwd)
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=600,
            env=_clean_subprocess_env(),
        )
        output = proc.stdout
        passed = proc.returncode == 0
    except Exception as exc:  # noqa: BLE001
        output = f"CI runner error: {exc}"
        passed = False

    pr.ci_status = (
        PullRequest.CIStatus.PASSED if passed else PullRequest.CIStatus.FAILED
    )
    pr.save(update_fields=["ci_status"])
    Event.log(
        f"CI {'passed ✓' if passed else 'failed ✕'} for PR #{pr.number}",
        project=project,
        actor="ci",
        level="success" if passed else "error",
        icon="test",
        url=pr.get_absolute_url(),
    )
    # Stash output where the orchestration UI can find it.
    print(f"[helm-ci] PR#{pr.number} {'PASS' if passed else 'FAIL'}\n{output[-4000:]}")
    return passed


# --------------------------------------------------------------------------- #
# THE STAR: autonomous incident -> fix loop
# --------------------------------------------------------------------------- #
_REMEDIATING_INCIDENTS: set[int] = set()
_REMEDIATE_LOCK = threading.Lock()


def is_remediating(incident_id: int) -> bool:
    with _REMEDIATE_LOCK:
        return incident_id in _REMEDIATING_INCIDENTS


def remediate(incident_id: int):
    """THE STAR. Background incident->fix pipeline. Returns the WorkflowRun
    (or None if a remediation is already running for this incident)."""
    with _REMEDIATE_LOCK:
        if incident_id in _REMEDIATING_INCIDENTS:
            return None
        _REMEDIATING_INCIDENTS.add(incident_id)

    from observability.models import Incident

    project = None
    try:
        project = Incident.objects.select_related("project").get(
            pk=incident_id
        ).project
    except Incident.DoesNotExist:
        with _REMEDIATE_LOCK:
            _REMEDIATING_INCIDENTS.discard(incident_id)
        return None

    def _do():
        try:
            return _remediate_pipeline(incident_id)
        finally:
            with _REMEDIATE_LOCK:
                _REMEDIATING_INCIDENTS.discard(incident_id)

    return _run(
        f"remediate incident #{incident_id}",
        _do,
        project=project,
        ref_type="incident",
        ref_id=incident_id,
    )


def _remediate_pipeline(incident_id: int) -> str:
    from agents import services as agent_svc
    from core.models import Event
    from deploys.models import Environment
    from deploys import services as deploy_svc
    from observability.models import Incident
    from vcs import services as vcs_svc

    inc = Incident.objects.select_related("project", "deployment").get(pk=incident_id)
    project = inc.project

    def _issue_hook(**kwargs):
        """Best-effort bridge into the Issues agent backlog. NEVER raises.

        Files-or-updates the single Ticket linked to this incident. Wrapped so
        any Issues failure leaves the remediation loop + terminal resolution
        completely unchanged.
        """
        try:
            from issues import services as issue_svc

            return issue_svc.ticket_for_incident(inc, **kwargs)
        except Exception as _exc:  # noqa: BLE001 — Issues must never break the loop
            print(f"[helm-orch] issues hook failed: {_exc}")
            return None

    def ev(verb, level="info", icon="fix", url="", oncall_kind=None):
        Event.log(
            verb,
            project=project,
            actor="claude-sre",
            level=level,
            icon=icon,
            url=url or inc.get_absolute_url(),
        )
        # oncall (Incidents v2): mirror each pipeline step into the first-class
        # timeline. Best-effort, lazy import, NEVER blocks remediation.
        try:
            from oncall.services import timeline as _oncall_tl

            _oncall_tl.record(inc, oncall_kind or "agent", verb, actor="claude-sre")
        except Exception as _exc:  # noqa: BLE001
            print(f"[helm-orch] oncall timeline hook failed: {_exc}")

    # 1. acknowledge -> remediating ----------------------------------------
    inc.status = Incident.Status.ACKNOWLEDGED
    inc.acknowledged_at = timezone.now()
    inc.save(update_fields=["status", "acknowledged_at"])
    ev(f"acknowledged INC-{inc.number}, triaging incident", icon="incident")

    inc.status = Incident.Status.REMEDIATING
    inc.save(update_fields=["status"])
    ev(f"INC-{inc.number}: dispatching remediation agent", icon="agent")

    # (a) incident detected -> file ticket + link incident (additive, idempotent)
    _issue_hook(status="todo")

    # 2. worktree off the prod branch --------------------------------------
    prod_env = (
        project.environments.filter(kind=Environment.Kind.PROD).first()
        or project.environments.filter(kind=Environment.Kind.STAGING).first()
        or project.environments.first()
    )
    base_branch = prod_env.branch if prod_env else project.default_branch
    ev(
        f"INC-{inc.number}: creating isolated worktree off {base_branch}",
        icon="git",
    )
    worktree = agent_svc.create_worktree(
        project, f"fix-inc-{inc.number}", base_branch=base_branch
    )

    # 3. strict remediation prompt -----------------------------------------
    suspect = inc.suspect_file or "(unknown file)"
    if inc.suspect_line:
        suspect += f":{inc.suspect_line}"
    prompt = (
        f"A production error is firing in this project (incident INC-{inc.number}).\n\n"
        f"Error type: {inc.error_type}\n"
        f"Error message: {inc.error_message}\n"
        f"Suspect location: {suspect}\n\n"
        f"Full traceback:\n```\n{inc.traceback}\n```\n\n"
        "Your task: Reproduce and fix the ROOT CAUSE of this production error. "
        "Make the smallest correct change. Add a regression test that fails "
        "before your fix and passes after. Do not change unrelated code. "
        "When done, ensure the project's test suite passes."
    )

    # 4. launch + run the agent INLINE (this thread waits for the fix) ------
    ev(f"INC-{inc.number}: agent writing the fix + regression test", icon="agent")
    agent_run = agent_svc.launch_agent(
        project,
        kind="remediation",
        title=f"Fix INC-{inc.number}: {inc.error_type}",
        prompt=prompt,
        worktree=worktree,
        incident=inc,
        base_branch=base_branch,
        open_pr=True,
        dispatch=False,
    )
    agent_svc.run_agent(agent_run)
    agent_run.refresh_from_db()

    # 5. CI on the resulting PR --------------------------------------------
    pr = agent_run.pull_request
    if not pr:
        ev(
            f"INC-{inc.number}: agent produced no PR — left for human review",
            level="warning",
            icon="x",
        )
        return f"INC-{inc.number}: no PR produced"

    ev(
        f"INC-{inc.number}: opened {('PR #%d' % pr.number)} — running CI",
        icon="pr",
        url=pr.get_absolute_url(),
    )

    # (b) agent spawned / PR opened -> link pull_request + agent_run, in_progress
    _issue_hook(status="in_progress", pull_request=pr, agent_run=agent_run)

    ci_passed = _run_ci_inline(pr.id)

    # 6. merge + redeploy on green -----------------------------------------
    if not ci_passed:
        ev(
            f"INC-{inc.number}: CI failed — PR #{pr.number} left open for review",
            level="warning",
            icon="x",
            url=pr.get_absolute_url(),
        )
        return f"INC-{inc.number}: CI failed, PR #{pr.number} open"

    if os.environ.get("HELM_AUTO_MERGE", "1") != "1":
        ev(
            f"INC-{inc.number}: CI green — PR #{pr.number} ready for human merge",
            level="success",
            icon="check",
            url=pr.get_absolute_url(),
        )
        return f"INC-{inc.number}: CI green, auto-merge disabled"

    ev(f"INC-{inc.number}: CI green ✓ — merging PR #{pr.number}", icon="merge",
       url=pr.get_absolute_url())
    vcs_svc.merge_pull_request(pr)

    if prod_env:
        ev(f"INC-{inc.number}: shipping the fix — redeploying {prod_env.name}",
           icon="rocket")
        deploy_svc.deploy(prod_env)

    inc.refresh_from_db()
    inc.status = Incident.Status.RESOLVED
    inc.resolved_at = timezone.now()
    inc.remediation_pr = pr
    inc.save(update_fields=["status", "resolved_at", "remediation_pr"])
    ev(
        f"INC-{inc.number} RESOLVED autonomously — fix shipped to production 🎉",
        level="success",
        icon="check",
        oncall_kind="resolved",
    )

    # (c) incident resolved -> set the linked ticket to done (best-effort).
    _issue_hook(status="done", pull_request=pr, agent_run=agent_run)
    # oncall (Incidents v2): best-effort auto-stub postmortem for sev1/sev2.
    try:
        from oncall.services import loop as _oncall_loop

        _oncall_loop.maybe_create_stub_postmortem(inc)
    except Exception as _exc:  # noqa: BLE001 - never block remediation
        print(f"[helm-orch] oncall postmortem hook failed: {_exc}")
    return f"INC-{inc.number}: resolved via PR #{pr.number}"
