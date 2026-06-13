"""Enterprise workstream tests — backs rubric items R6-R18 + R21.

Covers: record_audit loop-safety + request derivation + no-raise; ROLE_RANK;
has_role fail-open; role_required 403/200; API key create/verify/revoke; whoami
401/200 (session-less, org from key); RBAC-gated views by role; org isolation;
and the autonomous-loop regression gate (service contracts import + signatures).
"""

import inspect

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase, override_settings

from accounts.models import Membership, Org


def _add_enterprise(test_cls):
    """Skip enterprise view/url tests gracefully if the integrator hasn't wired
    'enterprise' into INSTALLED_APPS yet. Model/service tests still run because
    the app's models are import-safe; URL resolution needs it installed."""
    from django.conf import settings

    return "enterprise" in settings.INSTALLED_APPS


class RecordAuditTests(TestCase):
    def test_loop_call_no_context(self):
        from enterprise.models import AuditLog
        from enterprise.services import record_audit

        row = record_audit("loop.test")
        self.assertIsNotNone(row)
        self.assertEqual(row.actor, "system")
        self.assertIsNone(row.org)
        self.assertTrue(AuditLog.objects.filter(pk=row.pk).exists())

    def test_request_derivation(self):
        from enterprise.services import record_audit

        org = Org.objects.create(name="A", slug="a")
        user = User.objects.create_user("alice", password="x")
        req = RequestFactory().get("/")
        req.org = org
        req.user = user

        target = Org.objects.create(name="T", slug="t")
        row = record_audit("x.y", request=req, target=target)
        self.assertEqual(row.org_id, org.id)
        self.assertEqual(row.actor, "alice")
        self.assertEqual(row.actor_user_id, user.id)
        self.assertEqual(row.target_type, "Org")
        self.assertEqual(row.target_id, str(target.pk))

    def test_never_raises_on_bad_input(self):
        from enterprise.services import record_audit

        # None action.
        self.assertIsNotNone(record_audit(None))

        # Target whose __str__ / get_absolute_url blow up.
        class Bad:
            def __str__(self):
                raise RuntimeError("nope")

        # Should not raise even with a hostile target.
        record_audit("bad.target", target=Bad())


class RbacTests(TestCase):
    def test_role_rank_ordering(self):
        from enterprise.rbac import ROLE_RANK

        self.assertLess(ROLE_RANK["viewer"], ROLE_RANK["member"])
        self.assertLess(ROLE_RANK["member"], ROLE_RANK["admin"])
        self.assertLess(ROLE_RANK["admin"], ROLE_RANK["owner"])

    def test_has_role_fail_open_no_user(self):
        from enterprise.rbac import has_role

        req = RequestFactory().get("/")
        req.user = None
        req.org = None
        self.assertTrue(has_role(req, "admin"))

    def test_has_role_fail_open_no_org(self):
        from django.contrib.auth.models import AnonymousUser

        from enterprise.rbac import has_role

        req = RequestFactory().get("/")
        req.user = AnonymousUser()
        req.org = None
        self.assertTrue(has_role(req, "admin"))

    def test_has_role_in_org_below(self):
        from enterprise.rbac import has_role

        org = Org.objects.create(name="A", slug="a")
        user = User.objects.create_user("v", password="x")
        Membership.objects.create(org=org, user=user, role=Membership.Role.VIEWER)
        req = RequestFactory().get("/")
        req.user = user
        req.org = org
        self.assertFalse(has_role(req, "admin"))
        self.assertTrue(has_role(req, "viewer"))


class ApiKeyTests(TestCase):
    def test_create_returns_raw_and_hashes(self):
        import hashlib

        from enterprise.models import ApiKey
        from enterprise.services import create_api_key

        org = Org.objects.create(name="A", slug="a")
        key, raw = create_api_key(org, "ci")
        self.assertTrue(raw.startswith("hull_"))
        self.assertGreater(len(raw), 20)
        self.assertEqual(key.hashed_key, hashlib.sha256(raw.encode()).hexdigest())
        # raw must not be stored in any field.
        for f in key._meta.get_fields():
            if hasattr(f, "attname"):
                val = getattr(key, f.attname, None)
                if isinstance(val, str):
                    self.assertNotEqual(val, raw)
                    self.assertNotIn(raw, val)

    def test_verify_valid_garbage_revoked(self):
        from enterprise.services import (
            create_api_key,
            revoke_api_key,
            verify_api_key,
        )

        org = Org.objects.create(name="A", slug="a")
        key, raw = create_api_key(org, "ci")
        self.assertEqual(verify_api_key(raw).pk, key.pk)
        self.assertIsNone(verify_api_key("garbage"))
        self.assertIsNone(verify_api_key(None))
        revoke_api_key(key)
        self.assertIsNone(verify_api_key(raw))

    def test_revoke_emits_audit(self):
        from enterprise.models import AuditLog
        from enterprise.services import create_api_key, revoke_api_key

        org = Org.objects.create(name="A", slug="a")
        key, _ = create_api_key(org, "ci")
        revoke_api_key(key)
        self.assertTrue(
            AuditLog.objects.filter(org=org, action="apikey.created").exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(org=org, action="apikey.revoked").exists()
        )


@override_settings(ROOT_URLCONF="tests.enterprise_urls")
class WhoamiAndViewTests(TestCase):
    """Uses a dedicated urlconf that mounts enterprise + accounts so these run
    regardless of whether the integrator wired the root urls yet."""

    def setUp(self):
        from enterprise.services import create_api_key

        self.orgA = Org.objects.create(name="OrgA", slug="orga")
        self.orgB = Org.objects.create(name="OrgB", slug="orgb")
        self.owner = User.objects.create_user("owner", password="pw")
        self.viewer = User.objects.create_user("viewer", password="pw")
        self.outsider = User.objects.create_user("out", password="pw")
        Membership.objects.create(org=self.orgA, user=self.owner, role=Membership.Role.OWNER)
        Membership.objects.create(org=self.orgA, user=self.viewer, role=Membership.Role.VIEWER)
        Membership.objects.create(org=self.orgB, user=self.outsider, role=Membership.Role.OWNER)
        self.keyA, self.rawA = create_api_key(self.orgA, "ci")

    def test_whoami_401_no_cred(self):
        r = self.client.get("/enterprise/api/whoami/")
        self.assertEqual(r.status_code, 401)

    def test_whoami_200_bearer_sessionless(self):
        # No login / no session cookie — org derived purely from the key.
        r = self.client.get(
            "/enterprise/api/whoami/",
            HTTP_AUTHORIZATION=f"Bearer {self.rawA}",
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["org"], "OrgA")
        self.assertEqual(data["role"], "api")

    def test_settings_owner_200_anon_redirect(self):
        r = self.client.get("/enterprise/settings/")
        self.assertIn(r.status_code, (302, 403))
        self.client.force_login(self.owner)
        r = self.client.get("/enterprise/settings/")
        self.assertEqual(r.status_code, 200)

    def test_keys_viewer_403_owner_200(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get("/enterprise/keys/").status_code, 403)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/enterprise/keys/").status_code, 200)

    def test_viewer_cannot_create_key(self):
        self.client.force_login(self.viewer)
        r = self.client.post("/enterprise/keys/create/", {"name": "x"})
        self.assertEqual(r.status_code, 403)

    def test_owner_create_revoke_audit(self):
        from enterprise.models import ApiKey, AuditLog

        self.client.force_login(self.owner)
        r = self.client.post("/enterprise/keys/create/", {"name": "deploybot"}, follow=True)
        self.assertEqual(r.status_code, 200)
        key = ApiKey.objects.for_org(self.orgA).filter(name="deploybot").first()
        self.assertIsNotNone(key)
        self.assertTrue(
            AuditLog.objects.filter(org=self.orgA, action="apikey.created").exists()
        )
        r = self.client.post(f"/enterprise/keys/{key.pk}/revoke/", follow=True)
        key.refresh_from_db()
        self.assertIsNotNone(key.revoked_at)
        self.assertTrue(
            AuditLog.objects.filter(org=self.orgA, action="apikey.revoked").exists()
        )

    def test_edit_org_name_writes_audit(self):
        from enterprise.models import AuditLog

        self.client.force_login(self.owner)
        self.client.post("/enterprise/settings/", {"name": "Renamed"})
        self.orgA.refresh_from_db()
        self.assertEqual(self.orgA.name, "Renamed")
        self.assertTrue(
            AuditLog.objects.filter(org=self.orgA, action="org.updated").exists()
        )

    def test_org_isolation(self):
        from enterprise.models import ApiKey

        # A key in orgB must never surface in orgA's view.
        from enterprise.services import create_api_key

        create_api_key(self.orgB, "b-key")
        self.client.force_login(self.owner)
        r = self.client.get("/enterprise/keys/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "ci")
        self.assertNotContains(r, "b-key")
        # Queryset isolation.
        self.assertFalse(
            ApiKey.objects.for_org(self.orgA).filter(name="b-key").exists()
        )

    def test_outsider_cannot_see_orgA(self):
        # An orgB user has no orgA membership; their request.org is orgB, so
        # orgA keys are never returned.
        from enterprise.models import ApiKey

        self.assertFalse(
            ApiKey.objects.for_org(self.orgB).filter(name="ci").exists()
        )


class LoopRegressionTests(TestCase):
    """R21: contracts stay importable and signatures unchanged with enterprise on."""

    def test_service_contracts_import_and_signatures(self):
        import agents.services as a
        import deploys.services as d
        import observability.services as o
        import orchestration.service as orch

        self.assertEqual(
            list(inspect.signature(d.deploy).parameters),
            ["environment", "commit_sha", "source_path"],
        )
        self.assertEqual(
            list(inspect.signature(d.allocate_port).parameters), []
        )
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
