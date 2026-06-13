"""Temporal scaffold for Helm orchestration.

Default OFF (HELM_USE_TEMPORAL=0): the threaded fallback in ``service.py`` runs
instead, so the product works with no Temporal server. When enabled and a
worker is running (``python manage.py run_worker``), these workflows/activities
drive the SAME underlying logic via the ``_inline`` helpers in ``service``.

Activities call back into Django ORM code, so they must run in the worker
process (which boots Django via the management command).
"""

from __future__ import annotations

from datetime import timedelta

try:
    from temporalio import activity, workflow

    _HAVE_TEMPORAL = True
except Exception:  # temporalio not installed — keep module importable
    _HAVE_TEMPORAL = False

    class _Stub:
        def defn(self, *a, **k):
            def deco(cls):
                return cls

            return deco

        def __getattr__(self, _):
            def deco(fn=None, *a, **k):
                return fn if fn else (lambda f: f)

            return deco

    activity = _Stub()  # type: ignore
    workflow = _Stub()  # type: ignore


# --------------------------------------------------------------------------- #
# Activities — thin wrappers around the existing service logic.
# --------------------------------------------------------------------------- #
@activity.defn
async def deploy_activity(environment_id: int, commit_sha: str | None = None) -> str:
    from asgiref.sync import sync_to_async

    from deploys.models import Environment
    from deploys import services as deploy_svc

    @sync_to_async
    def _do():
        env = Environment.objects.get(pk=environment_id)
        dep = deploy_svc.deploy(env, commit_sha=commit_sha)
        return f"deployed {env} -> {getattr(dep, 'status', '?')}"

    return await _do()


@activity.defn
async def run_ci_activity(pull_request_id: int) -> bool:
    from asgiref.sync import sync_to_async

    from . import service

    return await sync_to_async(service._run_ci_inline)(pull_request_id)


@activity.defn
async def remediate_activity(incident_id: int) -> str:
    from asgiref.sync import sync_to_async

    from . import service

    return await sync_to_async(service._remediate_pipeline)(incident_id)


@activity.defn
async def run_agent_activity(agent_run_id: int) -> str:
    from asgiref.sync import sync_to_async

    from agents.models import AgentRun
    from agents import services as agent_svc

    @sync_to_async
    def _do():
        run = AgentRun.objects.get(pk=agent_run_id)
        agent_svc.run_agent(run)
        run.refresh_from_db()
        return f"agent #{run.pk} -> {run.status}"

    return await _do()


# --------------------------------------------------------------------------- #
# Workflows
# --------------------------------------------------------------------------- #
@workflow.defn
class DeployWorkflow:
    @workflow.run
    async def run(self, environment_id: int, commit_sha: str | None = None) -> str:
        return await workflow.execute_activity(
            deploy_activity,
            args=[environment_id, commit_sha],
            start_to_close_timeout=timedelta(minutes=20),
        )


@workflow.defn
class RunCIWorkflow:
    @workflow.run
    async def run(self, pull_request_id: int) -> bool:
        return await workflow.execute_activity(
            run_ci_activity,
            args=[pull_request_id],
            start_to_close_timeout=timedelta(minutes=20),
        )


@workflow.defn
class RemediateWorkflow:
    """The incident->fix loop as a durable Temporal workflow."""

    @workflow.run
    async def run(self, incident_id: int) -> str:
        return await workflow.execute_activity(
            remediate_activity,
            args=[incident_id],
            start_to_close_timeout=timedelta(hours=1),
        )


@workflow.defn
class RunAgentWorkflow:
    @workflow.run
    async def run(self, agent_run_id: int) -> str:
        return await workflow.execute_activity(
            run_agent_activity,
            args=[agent_run_id],
            start_to_close_timeout=timedelta(hours=1),
        )


WORKFLOWS = [DeployWorkflow, RunCIWorkflow, RemediateWorkflow, RunAgentWorkflow]
ACTIVITIES = [
    deploy_activity,
    run_ci_activity,
    remediate_activity,
    run_agent_activity,
]
