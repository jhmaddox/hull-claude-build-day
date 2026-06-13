"""Orchestration dispatcher.  [OWNER: Slice C agent]

Single entry point the rest of Helm calls to run durable, observable
workflows. Backed by Temporal when HELM_USE_TEMPORAL=1 and the server is
reachable; otherwise falls back to a threaded in-process runner so the product
always works. Keep these top-level functions stable — UI/services call them.

Each function should: be safe to call from a Django request (returns fast,
work happens in background), and emit core.Event entries so the dashboard
shows orchestration progress.
"""

from __future__ import annotations


def import_project(name: str, repo_url: str, *, description: str = ""):
    """Background: projects.services.import_project then auto-deploy staging+prod."""
    raise NotImplementedError


def deploy(environment_id: int, *, commit_sha: str | None = None):
    """Background: deploys.services.deploy for the environment."""
    raise NotImplementedError


def run_feature_agent(agent_run_id: int):
    """Background: agents.services.run_agent (creates worktree+PR as needed)."""
    raise NotImplementedError


def run_ci(pull_request_id: int):
    """Background: run the project's test suite inside the PR's worktree, set
    pr.ci_status RUNNING->PASSED/FAILED, log events. 'done' is verifiable: a
    green suite = mergeable."""
    raise NotImplementedError


def remediate(incident_id: int):
    """THE STAR. Background pipeline:
      1. ack incident -> status=REMEDIATING
      2. create a worktree off the prod branch at the deployed commit
      3. launch a remediation AgentRun with the incident traceback + a strict
         brief: reproduce, fix root cause, add a regression test, keep diff
         minimal
      4. agent opens a PR (vcs.services.open_pull_request)
      5. run_ci on the PR
      6. if CI passes: (optionally) merge + redeploy, mark incident RESOLVED;
         else leave PR open for human review
    Emits core.Event at every step so the demo narrates itself.
    """
    raise NotImplementedError
