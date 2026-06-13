"""Render smoke tests for the observability + orchestration UI pages.

These pages are now org-scoped (``@org_required`` redirects an
unauthenticated/orgless client to onboarding), so the test client logs in a
user, gives them a Membership in an Org, and sets ``session['org_id']`` — the
same path the ``CurrentOrgMiddleware`` resolves into ``request.org``. All test
records are stamped with that org so the org-scoped views return them.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Membership, Org
from deploys.models import Deployment, Environment
from observability import services
from observability.models import Incident
from orchestration.models import WorkflowRun
from projects.models import Project


class UISmokeTests(TestCase):
    def setUp(self):
        self.org = Org.objects.create(name="Acme", slug="acme")
        User = get_user_model()
        self.user = User.objects.create_user(
            username="smoke", email="smoke@example.com", password="pw"
        )
        Membership.objects.create(
            org=self.org, user=self.user, role=Membership.Role.OWNER
        )
        # Authenticate the client and make the org active (mirrors middleware).
        self.client.force_login(self.user)
        session = self.client.session
        session["org_id"] = self.org.id
        session.save()

        self.project = Project.objects.create(name="Shop", slug="shop", org=self.org)
        self.env = Environment.objects.create(
            project=self.project, name="prod", org=self.org
        )
        self.dep = Deployment.objects.create(
            environment=self.env,
            source_path="/srv/app",
            status=Deployment.Status.LIVE,
            commit_sha="abc1234567",
            port=9101,
            org=self.org,
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
            org=self.org,
        )
        self.wf = WorkflowRun.objects.create(
            name="remediate incident #1", project=self.project, org=self.org
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
            reverse("orchestration:activity"),
            reverse("orchestration:activity_panel"),
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
