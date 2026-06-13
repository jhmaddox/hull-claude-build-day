import os
from unittest import mock

from django.test import TestCase, TransactionTestCase

from agents.models import AgentRun, Worktree
from deploys.models import Deployment, Environment
from observability.models import Incident
from orchestration import service
from orchestration.models import WorkflowRun
from projects.models import Project
from vcs.models import PullRequest


class RemediatePipelineTests(TestCase):
    """Exercise the incident->fix state machine with stubbed cross-slice calls."""

    def setUp(self):
        os.environ["HELM_AUTO_MERGE"] = "1"
        self.project = Project.objects.create(
            name="Shop", slug="shop", default_branch="main", framework="django"
        )
        self.prod = Environment.objects.create(
            project=self.project,
            name="prod",
            kind=Environment.Kind.PROD,
            branch="main",
        )
        self.incident = Incident.objects.create(
            project=self.project,
            number=1,
            title="ZeroDivisionError in shop/cart.py",
            error_type="ZeroDivisionError",
            error_message="division by zero",
            traceback="Traceback...\nZeroDivisionError: division by zero",
            suspect_file="shop/cart.py",
            suspect_line=88,
        )

    def _stub_agents_vcs_deploys(self, ci_passes=True, produce_pr=True):
        worktree = Worktree.objects.create(
            project=self.project, name="fix-inc-1", branch="agent/fix-inc-1",
            base_branch="main", path="/tmp/wt", status=Worktree.Status.ACTIVE,
        )
        pr = None
        if produce_pr:
            pr = PullRequest.objects.create(
                project=self.project, number=1, title="Fix INC-1",
                head_branch="agent/fix-inc-1", base_branch="main",
            )

        agent_run = AgentRun.objects.create(
            project=self.project, kind=AgentRun.Kind.REMEDIATION,
            title="Fix INC-1", prompt="x", worktree=worktree,
            incident=self.incident, pull_request=pr,
            status=AgentRun.Status.DONE,
        )

        patches = {
            "create_worktree": mock.patch(
                "agents.services.create_worktree", return_value=worktree
            ),
            "launch_agent": mock.patch(
                "agents.services.launch_agent", return_value=agent_run
            ),
            "run_agent": mock.patch("agents.services.run_agent", return_value=None),
            "merge_pull_request": mock.patch(
                "vcs.services.merge_pull_request", return_value=True
            ),
            "deploy": mock.patch("deploys.services.deploy", return_value=None),
            "_run_ci_inline": mock.patch.object(
                service, "_run_ci_inline", return_value=ci_passes
            ),
        }
        return patches, agent_run, pr

    def test_happy_path_resolves_incident(self):
        patches, agent_run, pr = self._stub_agents_vcs_deploys(ci_passes=True)
        with patches["create_worktree"], patches["launch_agent"], patches[
            "run_agent"
        ], patches["merge_pull_request"] as merge, patches["deploy"] as deploy, patches[
            "_run_ci_inline"
        ]:
            result = service._remediate_pipeline(self.incident.id)

        self.incident.refresh_from_db()
        self.assertEqual(self.incident.status, Incident.Status.RESOLVED)
        self.assertIsNotNone(self.incident.resolved_at)
        self.assertEqual(self.incident.remediation_pr_id, pr.id)
        merge.assert_called_once()
        deploy.assert_called_once()
        self.assertIn("resolved", result)

    def test_ci_failure_leaves_incident_remediating(self):
        patches, agent_run, pr = self._stub_agents_vcs_deploys(ci_passes=False)
        with patches["create_worktree"], patches["launch_agent"], patches[
            "run_agent"
        ], patches["merge_pull_request"] as merge, patches["deploy"], patches[
            "_run_ci_inline"
        ]:
            service._remediate_pipeline(self.incident.id)

        self.incident.refresh_from_db()
        self.assertEqual(self.incident.status, Incident.Status.REMEDIATING)
        merge.assert_not_called()

    def test_no_pr_leaves_incident_remediating(self):
        patches, agent_run, pr = self._stub_agents_vcs_deploys(produce_pr=False)
        with patches["create_worktree"], patches["launch_agent"], patches[
            "run_agent"
        ], patches["merge_pull_request"], patches["deploy"], patches[
            "_run_ci_inline"
        ]:
            service._remediate_pipeline(self.incident.id)

        self.incident.refresh_from_db()
        self.assertEqual(self.incident.status, Incident.Status.REMEDIATING)

    def test_auto_merge_disabled_keeps_pr_open(self):
        os.environ["HELM_AUTO_MERGE"] = "0"
        patches, agent_run, pr = self._stub_agents_vcs_deploys(ci_passes=True)
        try:
            with patches["create_worktree"], patches["launch_agent"], patches[
                "run_agent"
            ], patches["merge_pull_request"] as merge, patches["deploy"], patches[
                "_run_ci_inline"
            ]:
                service._remediate_pipeline(self.incident.id)
        finally:
            os.environ["HELM_AUTO_MERGE"] = "1"

        self.incident.refresh_from_db()
        self.assertEqual(self.incident.status, Incident.Status.REMEDIATING)
        merge.assert_not_called()


class WorkflowRunTests(TransactionTestCase):
    """TransactionTestCase so the daemon thread's committed writes are visible."""

    def _wait(self, wf, timeout=20.0):
        import time

        deadline = time.time() + timeout
        while time.time() < deadline:
            wf.refresh_from_db()
            if wf.status != WorkflowRun.Status.RUNNING:
                return
            time.sleep(0.05)

    def test_run_creates_and_completes_workflow(self):
        wf = service._run("test wf", lambda: "ok")
        self.assertIsInstance(wf, WorkflowRun)
        self._wait(wf)
        self.assertEqual(wf.status, WorkflowRun.Status.DONE)
        self.assertEqual(wf.detail, "ok")

    def test_run_records_failure(self):
        def boom():
            raise RuntimeError("nope")

        wf = service._run("bad wf", boom)
        self._wait(wf)
        self.assertEqual(wf.status, WorkflowRun.Status.FAILED)
        self.assertIn("nope", wf.detail)
