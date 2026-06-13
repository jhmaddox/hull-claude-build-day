"""Projects multitenancy tests.

Covers tenant isolation, import org-tagging, autonomous-loop safety (org-less
imports), per-org slug reuse, and auth/onboarding gating. Service imports are
called directly with the ``org`` kwarg to avoid any real git clone.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Membership, Org

from . import services
from .models import Project

User = get_user_model()


def _make_user(username, org=None, role=Membership.Role.MEMBER):
    user = User.objects.create_user(username=username, password="pw12345!")
    if org is not None:
        Membership.objects.create(org=org, user=user, role=role)
    return user


class TenantIsolationTests(TestCase):
    def setUp(self):
        self.org_a = Org.objects.create(name="Org A", slug="org-a")
        self.org_b = Org.objects.create(name="Org B", slug="org-b")
        self.proj_a = Project.objects.create(
            name="Alpha", slug="alpha", org=self.org_a, status=Project.Status.READY
        )
        self.proj_b = Project.objects.create(
            name="Beta", slug="beta", org=self.org_b, status=Project.Status.READY
        )
        self.user_b = _make_user("bob", org=self.org_b)

    def test_list_shows_only_acting_orgs_projects(self):
        # [R8] Cross-tenant list isolation.
        self.client.force_login(self.user_b)
        resp = self.client.get(reverse("projects:list"))
        self.assertEqual(resp.status_code, 200)
        names = [p.name for p in resp.context["projects"]]
        self.assertIn("Beta", names)
        self.assertNotIn("Alpha", names)

    def test_detail_of_other_orgs_project_404(self):
        # [R9] Cross-tenant detail isolation.
        self.client.force_login(self.user_b)
        resp = self.client.get(
            reverse("projects:detail", args=[self.proj_a.slug])
        )
        self.assertEqual(resp.status_code, 404)

    def test_detail_resolves_own_project_in_scope(self):
        # [R6] The org-scoped queryset resolves the acting org's project (and
        # would 404 for others — covered above). Asserted at the queryset level
        # so it doesn't depend on sibling apps' (agents/deploys) migration state
        # during parallel builds; the full page render is exercised in
        # integration once all org migrations are present.
        from .models import Project

        qs = Project.objects.for_org(self.org_b)
        self.assertEqual(qs.get(slug=self.proj_b.slug), self.proj_b)
        self.assertFalse(qs.filter(slug=self.proj_a.slug).exists())


class AuthGatingTests(TestCase):
    def setUp(self):
        self.org = Org.objects.create(name="Org A", slug="org-a")

    def test_anon_redirects_to_login(self):
        # [R13] anon -> login (302).
        resp = self.client.get(reverse("projects:list"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp["Location"])

    def test_orgless_user_redirects_to_onboarding(self):
        # [R13] authenticated, no org -> onboarding (302).
        user = _make_user("nora")  # no membership
        self.client.force_login(user)
        resp = self.client.get(reverse("projects:list"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("accounts:onboarding"), resp["Location"])


class ImportTaggingTests(TestCase):
    def setUp(self):
        self.org = Org.objects.create(name="Org A", slug="org-a")

    def test_service_import_tags_org(self):
        # [R10] service import tags the passed org.
        project = services.import_project(
            "Local Tagged", "file:///nonexistent-path-xyz", org=self.org
        )
        # Even though the clone fails (no real repo), the Project is created and
        # must carry the org tag.
        self.assertEqual(project.org_id, self.org.id)

    def test_service_import_without_org_is_none(self):
        # [R11] loop safety: no org -> org is None.
        project = services.import_project("Loopy", "file:///nonexistent-path-xyz")
        self.assertIsNone(project.org_id)

    def test_ui_import_tags_request_org(self):
        # [R10] UI import (project_new) tags request.org.
        user = _make_user("ula", org=self.org)
        self.client.force_login(user)
        # Run the import body synchronously by calling the helper directly,
        # avoiding the background thread + real clone races.
        from . import views

        views._import_in_background(
            "Ui Project", "file:///nonexistent-path-xyz", "", org=self.org
        )
        project = Project.objects.get(slug="ui-project")
        self.assertEqual(project.org_id, self.org.id)


class SlugReuseTests(TestCase):
    def setUp(self):
        self.org_a = Org.objects.create(name="Org A", slug="org-a")
        self.org_b = Org.objects.create(name="Org B", slug="org-b")

    def test_per_org_slug_reuse(self):
        # [R12] 'api' in two orgs -> two projects, same slug.
        a = Project.objects.create(name="API", slug="api", org=self.org_a)
        b = Project.objects.create(name="API", slug="api", org=self.org_b)
        self.assertEqual(a.slug, "api")
        self.assertEqual(b.slug, "api")
        self.assertNotEqual(a.pk, b.pk)

    def test_unique_slug_helper_is_per_org(self):
        Project.objects.create(name="API", slug="api", org=self.org_a)
        # Same org -> deduped.
        self.assertEqual(services._unique_slug("API", org=self.org_a), "api-2")
        # Different org -> reusable.
        self.assertEqual(services._unique_slug("API", org=self.org_b), "api")
        # No org context -> reusable (loop path).
        self.assertEqual(services._unique_slug("API"), "api")


class LoopSafetyTests(TestCase):
    def test_import_project_signature_org_optional(self):
        # [R11] org param is keyword-only with default None.
        import inspect

        sig = inspect.signature(services.import_project)
        org_param = sig.parameters["org"]
        self.assertEqual(org_param.kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIsNone(org_param.default)


# ---------------------------------------------------------------------------
# New-UX behavior: org-scoped search + status filter, portfolio summary,
# health verdict helper, per-card / detail badges, distinct empty states,
# and N+1 safety. [R11-R18]
# ---------------------------------------------------------------------------

from django.utils import timezone  # noqa: E402

from deploys.models import Deployment, Environment  # noqa: E402
from observability.models import Incident  # noqa: E402

from .health import (  # noqa: E402
    DEGRADED,
    DOWN,
    LIVE,
    NEVER_DEPLOYED,
    health_verdict,
)


def _env(project, name="prod", org=None):
    return Environment.objects.create(
        project=project, name=name, kind=Environment.Kind.PROD, org=org
    )


def _deploy(env, status, org=None, created=None):
    return Deployment.objects.create(
        environment=env,
        status=status,
        org=org,
        created_at=created or timezone.now(),
    )


class HealthVerdictHelperTests(TestCase):
    # [R14] Verdict helper correctness + tolerance of org=None / zero envs.
    def setUp(self):
        self.org = Org.objects.create(name="Org A", slug="org-a")

    def test_never_deployed_when_no_deployments(self):
        p = Project.objects.create(name="P", slug="p", org=self.org)
        _env(p, "prod", org=self.org)  # env but no deployment
        v = health_verdict(p)
        self.assertEqual(v.verdict, NEVER_DEPLOYED)
        self.assertEqual(v.badge_class, "badge-neutral")

    def test_live_when_all_live(self):
        p = Project.objects.create(name="P", slug="p", org=self.org)
        e = _env(p, "prod", org=self.org)
        _deploy(e, Deployment.Status.LIVE, org=self.org)
        v = health_verdict(p)
        self.assertEqual(v.verdict, LIVE)
        self.assertEqual(v.live_count, 1)
        self.assertEqual(v.down_count, 0)
        self.assertIn(("prod", "live"), v.envs)

    def test_down_when_deployed_but_none_live(self):
        p = Project.objects.create(name="P", slug="p", org=self.org)
        e = _env(p, "prod", org=self.org)
        _deploy(e, Deployment.Status.FAILED, org=self.org)
        v = health_verdict(p)
        self.assertEqual(v.verdict, DOWN)
        self.assertIn(("prod", "down"), v.envs)

    def test_degraded_when_mixed(self):
        p = Project.objects.create(name="P", slug="p", org=self.org)
        e1 = _env(p, "prod", org=self.org)
        e2 = _env(p, "staging", org=self.org)
        _deploy(e1, Deployment.Status.LIVE, org=self.org)
        _deploy(e2, Deployment.Status.FAILED, org=self.org)
        v = health_verdict(p)
        self.assertEqual(v.verdict, DEGRADED)
        self.assertEqual(v.live_count, 1)
        self.assertEqual(v.down_count, 1)

    def test_tolerates_org_none_and_zero_envs(self):
        p = Project.objects.create(name="Loop", slug="loop")  # org=None, no envs
        v = health_verdict(p)  # must not raise
        self.assertEqual(v.verdict, NEVER_DEPLOYED)
        self.assertEqual(v.open_incident_count, 0)

    def test_open_incident_count_excludes_resolved(self):
        p = Project.objects.create(name="P", slug="p", org=self.org)
        Incident.objects.create(
            project=p, title="boom", status=Incident.Status.FIRING, org=self.org
        )
        Incident.objects.create(
            project=p, title="ok", status=Incident.Status.RESOLVED, org=self.org
        )
        v = health_verdict(p)
        self.assertEqual(v.open_incident_count, 1)


class SearchAndFilterTests(TestCase):
    # [R11] org-scoped search, [R12] validated status filter.
    def setUp(self):
        self.org_a = Org.objects.create(name="Org A", slug="org-a")
        self.org_b = Org.objects.create(name="Org B", slug="org-b")
        self.p_payments = Project.objects.create(
            name="Payments", slug="payments", org=self.org_b,
            status=Project.Status.READY, repo_url="https://git/payments",
        )
        self.p_billing = Project.objects.create(
            name="Billing", slug="billing", org=self.org_b,
            status=Project.Status.FAILED, repo_url="https://git/billing",
        )
        # Org A's project that B must never see via search.
        self.p_secret = Project.objects.create(
            name="SecretAlpha", slug="secretalpha", org=self.org_a,
            status=Project.Status.READY,
        )
        self.user_b = _make_user("bob", org=self.org_b)
        self.client.force_login(self.user_b)

    def _names(self, resp):
        return [p.name for p in resp.context["projects"]]

    def test_search_matches_own_project(self):
        resp = self.client.get(reverse("projects:list"), {"q": "pay"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._names(resp), ["Payments"])

    def test_search_is_org_scoped_zero_results_for_other_org(self):
        resp = self.client.get(reverse("projects:list"), {"q": "SecretAlpha"})
        self.assertEqual(self._names(resp), [])

    def test_search_matches_repo_url(self):
        resp = self.client.get(reverse("projects:list"), {"q": "git/billing"})
        self.assertEqual(self._names(resp), ["Billing"])

    def test_status_filter_valid(self):
        resp = self.client.get(reverse("projects:list"), {"status": "failed"})
        self.assertEqual(self._names(resp), ["Billing"])
        self.assertEqual(resp.context["status"], "failed")

    def test_status_filter_unknown_ignored(self):
        resp = self.client.get(reverse("projects:list"), {"status": "bogus"})
        self.assertEqual(resp.context["status"], "")
        self.assertEqual(sorted(self._names(resp)), ["Billing", "Payments"])

    def test_empty_status_returns_all(self):
        resp = self.client.get(reverse("projects:list"), {"status": ""})
        self.assertEqual(sorted(self._names(resp)), ["Billing", "Payments"])


class SummaryStripTests(TestCase):
    # [R13] portfolio summary is org-scoped and correct.
    def setUp(self):
        self.org_a = Org.objects.create(name="Org A", slug="org-a")
        self.org_b = Org.objects.create(name="Org B", slug="org-b")
        # Org B portfolio: one live, one failed (with incident).
        self.p_live = Project.objects.create(
            name="Live", slug="live", org=self.org_b, status=Project.Status.READY
        )
        e = _env(self.p_live, "prod", org=self.org_b)
        _deploy(e, Deployment.Status.LIVE, org=self.org_b)
        self.p_bad = Project.objects.create(
            name="Bad", slug="bad", org=self.org_b, status=Project.Status.FAILED
        )
        Incident.objects.create(
            project=self.p_bad, title="oops",
            status=Incident.Status.FIRING, org=self.org_b,
        )
        # Org A noise that must not leak into B's summary.
        Project.objects.create(
            name="OtherA", slug="othera", org=self.org_a,
            status=Project.Status.FAILED,
        )
        self.user_b = _make_user("bob", org=self.org_b)
        self.client.force_login(self.user_b)

    def test_summary_counts_are_org_scoped_and_correct(self):
        resp = self.client.get(reverse("projects:list"))
        s = resp.context["summary"]
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["live"], 1)
        self.assertEqual(s["failed"], 1)
        self.assertEqual(s["incidents"], 1)

    def test_summary_independent_of_active_filter(self):
        # Even with a filter that hides everything, the strip reflects the
        # whole org portfolio.
        resp = self.client.get(reverse("projects:list"), {"q": "zzz-nomatch"})
        self.assertEqual(resp.context["summary"]["total"], 2)
        self.assertEqual(resp.context["projects"], [])


class CardAndDetailBadgeTests(TestCase):
    # [R15] per-card verdict + open-incident badge; [R16] detail rollup.
    def setUp(self):
        self.org = Org.objects.create(name="Org A", slug="org-a")
        self.project = Project.objects.create(
            name="Web", slug="web", org=self.org, status=Project.Status.READY
        )
        e = _env(self.project, "prod", org=self.org)
        _deploy(e, Deployment.Status.LIVE, org=self.org)
        Incident.objects.create(
            project=self.project, title="boom",
            status=Incident.Status.FIRING, org=self.org,
        )
        self.user = _make_user("ula", org=self.org)
        self.client.force_login(self.user)

    def test_list_card_shows_verdict_and_incident_badge(self):
        resp = self.client.get(reverse("projects:list"))
        html = resp.content.decode()
        self.assertIn("badge-success", html)  # Live verdict
        self.assertIn("Live", html)
        self.assertIn("open incident", html)

    def test_detail_header_rollup_and_incident_count(self):
        resp = self.client.get(reverse("projects:detail", args=[self.project.slug]))
        self.assertEqual(resp.status_code, 200)
        v = resp.context["health"]
        self.assertEqual(v.verdict, LIVE)
        self.assertIn(("prod", "live"), v.envs)
        self.assertEqual(v.open_incident_count, 1)
        html = resp.content.decode()
        self.assertIn("prod", html)
        self.assertIn("open incident", html)


class EmptyStateTests(TestCase):
    # [R17] distinct empty states.
    def setUp(self):
        self.org = Org.objects.create(name="Org A", slug="org-a")
        self.user = _make_user("ula", org=self.org)
        self.client.force_login(self.user)

    def test_genuinely_empty_org_shows_import_cta(self):
        resp = self.client.get(reverse("projects:list"))
        html = resp.content.decode()
        self.assertFalse(resp.context["has_query"])
        self.assertIn("Import one", html)
        self.assertNotIn("No projects match", html)

    def test_no_match_state_when_query_active(self):
        Project.objects.create(
            name="Real", slug="real", org=self.org, status=Project.Status.READY
        )
        resp = self.client.get(reverse("projects:list"), {"q": "nomatch-zzz"})
        html = resp.content.decode()
        self.assertTrue(resp.context["has_query"])
        self.assertIn("No projects match", html)
        # Reset link back to /projects/.
        self.assertIn('href="/projects/"', html)


class NoNPlusOneTests(TestCase):
    # [R18] rendering N projects must not issue O(N) extra queries.
    def setUp(self):
        self.org = Org.objects.create(name="Org A", slug="org-a")
        self.user = _make_user("ula", org=self.org)
        self._n = 0

    def _seed(self, n):
        for _ in range(n):
            i = self._n
            self._n += 1
            p = Project.objects.create(
                name=f"P{i}", slug=f"p{i}", org=self.org,
                status=Project.Status.READY,
            )
            e = _env(p, "prod", org=self.org)
            _deploy(e, Deployment.Status.LIVE, org=self.org)
            Incident.objects.create(
                project=p, title="x", status=Incident.Status.FIRING, org=self.org
            )

    def test_query_count_stable_as_projects_grow(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        self.client.force_login(self.user)
        self._seed(2)
        with CaptureQueriesContext(connection) as ctx_small:
            self.client.get(reverse("projects:list"))
        small = len(ctx_small.captured_queries)

        self._seed(6)  # now 8 projects total
        with CaptureQueriesContext(connection) as ctx_big:
            self.client.get(reverse("projects:list"))
        big = len(ctx_big.captured_queries)

        # Adding 6 projects (each with env+deploy+incident) must not add a
        # per-project burst of queries; allow a tiny constant slack.
        self.assertLessEqual(big - small, 2, (small, big))
