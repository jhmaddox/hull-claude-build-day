"""Enterprise sprint-delta tests — rubric §7b R1-R8.

Covers: audit_actions import/constants (R1); a cross-workstream flow producing an
audit row with the correct org (R2); fail-soft audit hook (R3); members view RBAC
+ org isolation (R4); role change audit + last-owner guard + viewer 403 (R5);
audit pagination (R6); CSV export headers/org-scoping/RBAC (R7); and a delta gate
re-asserting the four service modules still import with unchanged signatures (R8).

Uses the dedicated ``tests.enterprise_urls`` urlconf so these run regardless of
whether the integrator has wired enterprise into helm/urls.py yet. Does NOT run
migrate; no model changes are introduced by this delta.
"""

from __future__ import annotations

import inspect

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from accounts.models import Membership, Org


def _fake_pr(org, number=7):
    """Build a minimal PR-like object whose merge exercises ONLY the audit hook."""

    class FakeProject:
        local_path = "/tmp/does-not-matter"

    FakeProject.org = org

    class FakePR:
        title = "Fix"
        base_branch = "main"
        head_branch = "feature"
        status = "open"
        merged_at = None
        worktree_id = None

        def __init__(self):
            self.number = number
            self.project = FakeProject()

        def get_absolute_url(self):
            return "/vcs/pr/x/"

        def save(self, *a, **kw):
            pass

    return FakePR()


class _OkGit:
    returncode = 0
    stdout = ""
    stderr = ""


class _SilentEvent:
    @staticmethod
    def log(*a, **kw):
        pass


def _merge_with_stubs(pr):
    """Run vcs.merge_pull_request with git/Event stubbed so no disk I/O happens."""
    import vcs.services as vcs_services

    orig_git = vcs_services._git
    orig_event = vcs_services.Event
    try:
        vcs_services._git = lambda *a, **kw: _OkGit()
        vcs_services.Event = _SilentEvent
        return vcs_services.merge_pull_request(pr)
    finally:
        vcs_services._git = orig_git
        vcs_services.Event = orig_event


# --------------------------------------------------------------------------- #
# R1 — audit_actions constants
# --------------------------------------------------------------------------- #
class AuditActionsTests(TestCase):
    def test_module_imports_and_exposes_constants(self):
        from enterprise import audit_actions as A

        self.assertEqual(A.PR_MERGED, "pr.merged")
        self.assertEqual(A.DEPLOY_SHIPPED, "deploy.shipped")
        self.assertEqual(A.INCIDENT_OPENED, "incident.opened")
        self.assertEqual(A.INCIDENT_RESOLVED, "incident.resolved")
        self.assertEqual(A.MEMBER_ROLE_CHANGED, "member.role_changed")
        self.assertEqual(A.MEMBER_ADDED, "member.added")
        self.assertEqual(A.MEMBER_REMOVED, "member.removed")
        self.assertEqual(A.INVITE_SENT, "invite.sent")
        for a in A.ALL_ACTIONS:
            self.assertIsInstance(a, str)
            self.assertIn(".", a)

    def test_import_safe(self):
        import importlib

        mod = importlib.import_module("enterprise.audit_actions")
        self.assertTrue(hasattr(mod, "PR_MERGED"))


# --------------------------------------------------------------------------- #
# R2 — cross-workstream flow produces an audit row with the right org
# --------------------------------------------------------------------------- #
class CrossWorkstreamAuditTests(TestCase):
    def test_merge_emits_pr_merged_audit_with_project_org(self):
        from enterprise.audit_actions import PR_MERGED
        from enterprise.models import AuditLog

        org = Org.objects.create(name="A", slug="cw-a")
        ok = _merge_with_stubs(_fake_pr(org, number=7))
        self.assertTrue(ok)

        row = AuditLog.objects.filter(action=PR_MERGED).order_by("-pk").first()
        self.assertIsNotNone(row)
        self.assertEqual(row.org_id, org.id)
        self.assertNotIn(
            row.action, ("apikey.created", "apikey.revoked", "org.updated")
        )

    def test_grep_proves_a_non_enterprise_producer_exists(self):
        import vcs.services as vcs_services

        src = inspect.getsource(vcs_services.merge_pull_request)
        self.assertIn("record_audit", src)


# --------------------------------------------------------------------------- #
# R3 — fail-soft
# --------------------------------------------------------------------------- #
class FailSoftTests(TestCase):
    def test_record_audit_never_raises_when_create_raises(self):
        from enterprise import services as ent_services
        from enterprise.models import AuditLog

        orig = AuditLog.objects.create

        def boom(*a, **kw):
            raise RuntimeError("db on fire")

        try:
            AuditLog.objects.create = boom
            self.assertIsNone(ent_services.record_audit("x.y"))
        finally:
            AuditLog.objects.create = orig

    def test_merge_completes_even_if_audit_create_raises(self):
        from enterprise.models import AuditLog

        org = Org.objects.create(name="B", slug="cw-b")
        orig_create = AuditLog.objects.create

        def boom(*a, **kw):
            raise RuntimeError("audit down")

        try:
            AuditLog.objects.create = boom
            ok = _merge_with_stubs(_fake_pr(org, number=9))
        finally:
            AuditLog.objects.create = orig_create

        self.assertTrue(ok)  # producing path still completes


# --------------------------------------------------------------------------- #
# R4 + R5 — members view RBAC, org isolation, role change, last-owner guard
# --------------------------------------------------------------------------- #
@override_settings(ROOT_URLCONF="tests.enterprise_urls")
class MembersViewTests(TestCase):
    def setUp(self):
        self.orgA = Org.objects.create(name="OrgA", slug="ma-a")
        self.orgB = Org.objects.create(name="OrgB", slug="ma-b")
        self.owner = User.objects.create_user("owner", password="pw")
        self.admin = User.objects.create_user("admin", password="pw")
        self.viewer = User.objects.create_user("viewer", password="pw")
        self.other = User.objects.create_user("other", password="pw")
        self.bmember = User.objects.create_user("bmember", password="pw")
        Membership.objects.create(org=self.orgA, user=self.owner, role=Membership.Role.OWNER)
        Membership.objects.create(org=self.orgA, user=self.admin, role=Membership.Role.ADMIN)
        Membership.objects.create(org=self.orgA, user=self.viewer, role=Membership.Role.VIEWER)
        Membership.objects.create(org=self.orgA, user=self.other, role=Membership.Role.MEMBER)
        Membership.objects.create(org=self.orgB, user=self.bmember, role=Membership.Role.OWNER)

    def test_members_rbac_and_org_isolation(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get("/enterprise/members/").status_code, 403)

        self.client.force_login(self.owner)
        r = self.client.get("/enterprise/members/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "owner")
        self.assertContains(r, "viewer")
        self.assertNotContains(r, "bmember")

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/enterprise/members/").status_code, 200)

    def test_role_change_audited(self):
        from enterprise.audit_actions import MEMBER_ROLE_CHANGED
        from enterprise.models import AuditLog

        m = Membership.objects.get(org=self.orgA, user=self.other)
        self.client.force_login(self.owner)
        r = self.client.post(
            f"/enterprise/members/{m.pk}/role/",
            {"role": Membership.Role.ADMIN},
            follow=True,
        )
        self.assertEqual(r.status_code, 200)
        m.refresh_from_db()
        self.assertEqual(m.role, Membership.Role.ADMIN)
        self.assertTrue(
            AuditLog.objects.filter(org=self.orgA, action=MEMBER_ROLE_CHANGED).exists()
        )

    def test_viewer_cannot_change_role(self):
        m = Membership.objects.get(org=self.orgA, user=self.other)
        self.client.force_login(self.viewer)
        r = self.client.post(
            f"/enterprise/members/{m.pk}/role/", {"role": Membership.Role.ADMIN}
        )
        self.assertEqual(r.status_code, 403)
        m.refresh_from_db()
        self.assertEqual(m.role, Membership.Role.MEMBER)

    def test_last_owner_cannot_be_demoted(self):
        owner_m = Membership.objects.get(org=self.orgA, user=self.owner)
        self.client.force_login(self.owner)
        self.client.post(
            f"/enterprise/members/{owner_m.pk}/role/", {"role": Membership.Role.ADMIN}
        )
        owner_m.refresh_from_db()
        self.assertEqual(owner_m.role, Membership.Role.OWNER)

    def test_last_owner_cannot_be_removed(self):
        owner_m = Membership.objects.get(org=self.orgA, user=self.owner)
        self.client.force_login(self.owner)
        self.client.post(f"/enterprise/members/{owner_m.pk}/remove/")
        self.assertTrue(
            Membership.objects.filter(org=self.orgA, user=self.owner).exists()
        )

    def test_cannot_mutate_other_orgs_member(self):
        bm = Membership.objects.get(org=self.orgB, user=self.bmember)
        self.client.force_login(self.owner)
        r = self.client.post(
            f"/enterprise/members/{bm.pk}/role/", {"role": Membership.Role.VIEWER}
        )
        self.assertEqual(r.status_code, 404)
        bm.refresh_from_db()
        self.assertEqual(bm.role, Membership.Role.OWNER)


# --------------------------------------------------------------------------- #
# R6 — audit pagination
# --------------------------------------------------------------------------- #
@override_settings(ROOT_URLCONF="tests.enterprise_urls")
class AuditPaginationTests(TestCase):
    def setUp(self):
        self.org = Org.objects.create(name="P", slug="pag")
        self.owner = User.objects.create_user("powner", password="pw")
        Membership.objects.create(org=self.org, user=self.owner, role=Membership.Role.OWNER)

    def test_page_two_is_distinct(self):
        from enterprise.services import record_audit

        for i in range(120):
            record_audit("loop.test", org=self.org, metadata={"i": i})

        self.client.force_login(self.owner)
        r1 = self.client.get("/enterprise/audit/")
        self.assertEqual(r1.status_code, 200)
        self.assertIn("page_obj", r1.context)
        r2 = self.client.get("/enterprise/audit/?page=2")
        self.assertEqual(r2.status_code, 200)
        ids1 = {row.pk for row in r1.context["page_obj"].object_list}
        ids2 = {row.pk for row in r2.context["page_obj"].object_list}
        self.assertTrue(ids1)
        self.assertTrue(ids2)
        self.assertTrue(ids1.isdisjoint(ids2))


# --------------------------------------------------------------------------- #
# R7 — CSV export
# --------------------------------------------------------------------------- #
@override_settings(ROOT_URLCONF="tests.enterprise_urls")
class AuditExportTests(TestCase):
    def setUp(self):
        from enterprise.services import record_audit

        self.orgA = Org.objects.create(name="EA", slug="exp-a")
        self.orgB = Org.objects.create(name="EB", slug="exp-b")
        self.owner = User.objects.create_user("eowner", password="pw")
        self.viewer = User.objects.create_user("eviewer", password="pw")
        self.bowner = User.objects.create_user("ebowner", password="pw")
        Membership.objects.create(org=self.orgA, user=self.owner, role=Membership.Role.OWNER)
        Membership.objects.create(org=self.orgA, user=self.viewer, role=Membership.Role.VIEWER)
        Membership.objects.create(org=self.orgB, user=self.bowner, role=Membership.Role.OWNER)

        record_audit("pr.merged", org=self.orgA, actor="alice")
        record_audit("deploy.shipped", org=self.orgA, actor="bob")
        record_audit("pr.merged", org=self.orgB, actor="zzzotherorg")

    def test_admin_gets_csv_with_attachment(self):
        self.client.force_login(self.owner)
        r = self.client.get("/enterprise/audit/export.csv")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "text/csv")
        self.assertIn("attachment", r["Content-Disposition"])
        body = r.content.decode()
        self.assertIn("created_at,actor,action", body)
        self.assertIn("alice", body)
        self.assertNotIn("zzzotherorg", body)

    def test_action_filter_applied(self):
        self.client.force_login(self.owner)
        r = self.client.get("/enterprise/audit/export.csv?action=pr.merged")
        body = r.content.decode()
        self.assertIn("pr.merged", body)
        self.assertNotIn("deploy.shipped", body)

    def test_actor_filter_applied(self):
        self.client.force_login(self.owner)
        r = self.client.get("/enterprise/audit/export.csv?actor=alice")
        body = r.content.decode()
        self.assertIn("alice", body)
        self.assertNotIn("bob", body)

    def test_viewer_rejected(self):
        self.client.force_login(self.viewer)
        r = self.client.get("/enterprise/audit/export.csv")
        self.assertEqual(r.status_code, 403)

    def test_anon_rejected(self):
        r = self.client.get("/enterprise/audit/export.csv")
        self.assertIn(r.status_code, (302, 403))


# --------------------------------------------------------------------------- #
# R8 — delta gate
# --------------------------------------------------------------------------- #
class ServiceContractDeltaTests(TestCase):
    def test_four_service_modules_import_and_signatures_unchanged(self):
        import agents.services as a
        import deploys.services as d
        import observability.services as o
        import orchestration.service as orch

        self.assertEqual(
            list(inspect.signature(d.deploy).parameters),
            ["environment", "commit_sha", "source_path"],
        )
        self.assertEqual(list(inspect.signature(d.allocate_port).parameters), [])
        self.assertEqual(
            list(inspect.signature(a.create_worktree).parameters),
            ["project", "name", "base_branch"],
        )
        self.assertEqual(
            list(inspect.signature(o.open_or_update_incident).parameters),
            [
                "deployment",
                "error_type",
                "error_message",
                "traceback",
                "suspect_file",
                "suspect_line",
                "severity",
            ],
        )
        self.assertEqual(
            list(inspect.signature(orch.remediate).parameters), ["incident_id"]
        )
