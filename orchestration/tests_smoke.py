"""Render smoke tests for the observability + orchestration UI pages."""

from django.test import TestCase
from django.urls import reverse

from deploys.models import Deployment, Environment
from observability import services
from observability.models import Incident
from orchestration.models import WorkflowRun
from projects.models import Project


class UISmokeTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name="Shop", slug="shop")
        self.env = Environment.objects.create(project=self.project, name="prod")
        self.dep = Deployment.objects.create(
            environment=self.env,
            source_path="/srv/app",
            status=Deployment.Status.LIVE,
            commit_sha="abc1234567",
            port=9101,
        )
        services.record_metric(self.dep, "requests", 10)
        services.record_metric(self.dep, "errors", 2)
        self.inc = Incident.objects.create(
            project=self.project,
            deployment=self.dep,
            number=1,
            title="ZeroDivisionError in shop/cart.py",
            error_type="ZeroDivisionError",
            error_message="division by zero",
            traceback="Traceback...\nZeroDivisionError: division by zero",
            suspect_file="shop/cart.py",
            suspect_line=88,
        )
        self.wf = WorkflowRun.objects.create(
            name="remediate incident #1", project=self.project
        )

    def test_pages_render(self):
        urls = [
            reverse("observability:overview"),
            reverse("observability:incident_list"),
            reverse("observability:incident_detail", args=[self.inc.pk]),
            reverse("observability:incident_status", args=[self.inc.pk]),
            reverse("observability:deployment_logs", args=[self.dep.pk]),
            reverse("orchestration:workflow_list"),
            reverse("orchestration:workflow_table"),
            reverse("orchestration:workflow_detail", args=[self.wf.pk]),
        ]
        for u in urls:
            resp = self.client.get(u)
            self.assertEqual(resp.status_code, 200, f"{u} -> {resp.status_code}")

    def test_manual_remediate_post_redirects(self):
        from unittest import mock

        with mock.patch("orchestration.service.remediate") as m:
            resp = self.client.post(
                reverse("observability:incident_remediate", args=[self.inc.pk])
            )
        self.assertEqual(resp.status_code, 302)
        m.assert_called_once_with(self.inc.id)
