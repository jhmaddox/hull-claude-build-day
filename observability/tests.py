import os
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Membership, Org
from deploys.models import Deployment, Environment
from observability import services
from observability.models import Incident, LogLine, MetricPoint, Monitor
from projects.models import Project


TRACEBACK_LINES = [
    "Traceback (most recent call last):",
    '  File "/srv/app/manage.py", line 22, in <module>',
    "    main()",
    '  File "/srv/app/shop/views.py", line 41, in checkout',
    "    total = cart.total()",
    '  File "/srv/app/shop/cart.py", line 88, in total',
    "    return sum(i.price for i in self.items) / self.count",
    "ZeroDivisionError: division by zero",
]


class IngestionTests(TestCase):
    def setUp(self):
        os.environ["HELM_AUTO_REMEDIATE"] = "0"
        self.project = Project.objects.create(name="Shop", slug="shop")
        self.env = Environment.objects.create(project=self.project, name="prod")
        self.dep = Deployment.objects.create(
            environment=self.env,
            source_path="/srv/app",
            status=Deployment.Status.LIVE,
        )
        services._BUFFERS.clear()

    def test_parses_django_request_line(self):
        log = services.ingest_line(
            self.dep, '[13/Jun/2026 16:00:00] "GET /checkout HTTP/1.1" 500 145'
        )
        self.assertEqual(log.method, "GET")
        self.assertEqual(log.path, "/checkout")
        self.assertEqual(log.status_code, 500)
        self.assertEqual(log.latency_ms, 145.0)
        self.assertEqual(log.level, LogLine.Level.ERROR)
        self.assertTrue(
            MetricPoint.objects.filter(deployment=self.dep, name="requests").exists()
        )
        self.assertTrue(
            MetricPoint.objects.filter(deployment=self.dep, name="errors").exists()
        )

    def test_level_for_4xx_is_warning(self):
        log = services.ingest_line(
            self.dep, '[13/Jun/2026 16:00:00] "GET /missing HTTP/1.1" 404 12'
        )
        self.assertEqual(log.level, LogLine.Level.WARNING)
        self.assertFalse(
            MetricPoint.objects.filter(deployment=self.dep, name="errors").exists()
        )

    def test_assembles_traceback_and_opens_incident(self):
        for line in TRACEBACK_LINES:
            services.ingest_line(self.dep, line)
        inc = Incident.objects.get()
        self.assertEqual(inc.error_type, "ZeroDivisionError")
        self.assertEqual(inc.error_message, "division by zero")
        self.assertEqual(inc.suspect_file, "shop/cart.py")
        self.assertEqual(inc.suspect_line, 88)
        self.assertIn("ZeroDivisionError", inc.traceback)
        self.assertEqual(inc.status, Incident.Status.FIRING)

    def test_dedup_increments_occurrences(self):
        for _ in range(2):
            for line in TRACEBACK_LINES:
                services.ingest_line(self.dep, line)
        self.assertEqual(Incident.objects.count(), 1)
        self.assertEqual(Incident.objects.get().occurrences, 2)

    def test_traceback_ended_by_request_line(self):
        services.ingest_line(self.dep, "Traceback (most recent call last):")
        services.ingest_line(
            self.dep, '  File "/srv/app/shop/views.py", line 41, in checkout'
        )
        services.ingest_line(
            self.dep, '[13/Jun/2026 16:00:01] "GET / HTTP/1.1" 200 9'
        )
        self.assertEqual(Incident.objects.count(), 1)


class IncidentSignatureTests(TestCase):
    def test_signature_uses_file_when_present(self):
        sig_a = services._compute_signature("ValueError", "x", "a/b.py", 10)
        sig_b = services._compute_signature("ValueError", "different", "a/b.py", 10)
        self.assertEqual(sig_a, sig_b)

    def test_signature_uses_message_when_no_file(self):
        sig_a = services._compute_signature("ValueError", "x", "", None)
        sig_b = services._compute_signature("ValueError", "y", "", None)
        self.assertNotEqual(sig_a, sig_b)


class AutoRemediateDispatchTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name="Shop", slug="shop2")
        self.env = Environment.objects.create(project=self.project, name="prod")
        self.dep = Deployment.objects.create(
            environment=self.env,
            source_path="/srv/app",
            status=Deployment.Status.LIVE,
        )

    def test_opening_incident_dispatches_remediate(self):
        os.environ["HELM_AUTO_REMEDIATE"] = "1"
        with mock.patch("orchestration.service.remediate") as m:
            inc = services.open_or_update_incident(
                self.dep, error_type="ValueError", error_message="boom"
            )
            m.assert_called_once_with(inc.id)


# --------------------------------------------------------------------------- #
# Observability v2 — rollups, monitors, recovery, mute, org isolation.
# --------------------------------------------------------------------------- #
def _mk_dep(project, source_path="/srv/app"):
    env = Environment.objects.create(project=project, name="prod")
    return Deployment.objects.create(
        environment=env,
        source_path=source_path,
        status=Deployment.Status.LIVE,
    )


class RollupsTests(TestCase):
    def setUp(self):
        os.environ["HELM_AUTO_REMEDIATE"] = "0"
        self.project = Project.objects.create(name="Roll", slug="roll")
        self.dep = _mk_dep(self.project)

    def test_percentile_keys_and_monotonicity(self):
        for v in range(10, 101, 10):  # 10,20,...,100
            services.record_metric(self.dep, "latency_ms", v)
        r = services.rollups(self.dep)
        for key in ("req_rate", "error_rate", "throughput", "p50", "p95", "p99"):
            self.assertIn(key, r)
        self.assertLessEqual(r["p50"], r["p95"])
        self.assertLessEqual(r["p95"], r["p99"])
        # nearest-rank: p95 of 10 samples -> ceil(.95*10)=10th -> 100
        self.assertEqual(r["p95"], 100)

    def test_error_rate_math(self):
        for _ in range(10):
            services.record_metric(self.dep, "requests", 1)
        for _ in range(2):
            services.record_metric(self.dep, "errors", 1)
        r = services.rollups(self.dep)
        self.assertAlmostEqual(r["error_rate"], 20.0, places=1)
        self.assertGreaterEqual(r["error_rate"], 0.0)
        self.assertLessEqual(r["error_rate"], 100.0)

    def test_window_param_returns_valid_dicts(self):
        for w in (1, 60):
            r = services.rollups(self.dep, window_minutes=w)
            self.assertIsInstance(r, dict)
            self.assertIn("p95", r)


class MonitorBreachRecoveryTests(TestCase):
    def setUp(self):
        os.environ["HELM_AUTO_REMEDIATE"] = "0"
        self.project = Project.objects.create(name="Mon", slug="mon")
        self.dep = _mk_dep(self.project)
        services._BUFFERS.clear()

    def _err_monitor(self, **kw):
        defaults = dict(
            deployment=self.dep,
            metric=Monitor.Metric.ERROR_RATE,
            comparator=Monitor.Comparator.GT,
            threshold=10.0,
            window_minutes=5,
            enabled=True,
        )
        defaults.update(kw)
        return Monitor.objects.create(**defaults)

    def _drive_error_rate(self, requests=10, errors=5):
        for _ in range(requests):
            services.record_metric(self.dep, "requests", 1)
        for _ in range(errors):
            services.record_metric(self.dep, "errors", 1)

    def test_breach_opens_exactly_one_incident_and_dedupes(self):
        mon = self._err_monitor()
        self._drive_error_rate(errors=5)  # 50% > 10%
        opened = services.evaluate_monitors(self.dep)
        self.assertIsInstance(opened, list)
        self.assertEqual(
            Incident.objects.filter(error_type="MonitorBreach").count(), 1
        )
        # re-eval while still breached -> no second incident
        services.evaluate_monitors(self.dep)
        self.assertEqual(
            Incident.objects.filter(error_type="MonitorBreach").count(), 1
        )

    def test_recovery_auto_resolves_only_its_own_incident(self):
        mon = self._err_monitor()
        self._drive_error_rate(errors=5)
        services.evaluate_monitors(self.dep)
        inc = Incident.objects.get(error_type="MonitorBreach")
        self.assertEqual(inc.status, Incident.Status.FIRING)

        # Co-existing traceback incident must stay firing.
        for line in TRACEBACK_LINES:
            services.ingest_line(self.dep, line)
        tb = Incident.objects.get(error_type="ZeroDivisionError")

        # Recover: drop error rate to 0 (only healthy requests in a fresh window).
        MetricPoint.objects.filter(deployment=self.dep, name="errors").delete()
        services.evaluate_monitors(self.dep)

        inc.refresh_from_db()
        tb.refresh_from_db()
        self.assertEqual(inc.status, Incident.Status.RESOLVED)
        self.assertIsNotNone(inc.resolved_at)
        # crown-jewel guard: traceback incident untouched
        self.assertEqual(tb.status, Incident.Status.FIRING)
        self.assertEqual(tb.suspect_file, "shop/cart.py")

    def test_muted_monitor_opens_nothing(self):
        self._err_monitor(
            muted_until=timezone.now() + timezone.timedelta(minutes=30)
        )
        self._drive_error_rate(errors=5)
        opened = services.evaluate_monitors(self.dep)
        self.assertEqual(opened, [])
        self.assertEqual(
            Incident.objects.filter(error_type="MonitorBreach").count(), 0
        )

    def test_live_status_values(self):
        mon = self._err_monitor(enabled=False)
        self.assertEqual(mon.live_status(), "disabled")
        mon.enabled = True
        mon.muted_until = timezone.now() + timezone.timedelta(minutes=5)
        self.assertEqual(mon.live_status(), "muted")
        mon.muted_until = None
        mon.save(update_fields=["enabled", "muted_until"])
        self.assertEqual(mon.live_status(), "ok")
        self._drive_error_rate(errors=5)
        services.evaluate_monitors(self.dep)
        self.assertEqual(mon.live_status(), "alerting")


class IngestLoopSafetyTests(TestCase):
    def setUp(self):
        os.environ["HELM_AUTO_REMEDIATE"] = "0"
        self.project = Project.objects.create(name="Loop", slug="loop")
        self.dep = _mk_dep(self.project)
        services._BUFFERS.clear()

    def test_ingest_orgless_returns_logline_org_none(self):
        log = services.ingest_line(
            self.dep, '[13/Jun/2026 16:00:00] "GET / HTTP/1.1" 200 12'
        )
        self.assertIsInstance(log, LogLine)
        self.assertIsNone(log.org)

    def test_ingest_safe_with_recovering_monitor(self):
        Monitor.objects.create(
            deployment=self.dep,
            metric=Monitor.Metric.ERROR_RATE,
            comparator=Monitor.Comparator.GT,
            threshold=10.0,
            enabled=True,
        )
        # No errors -> monitor evaluates recovery path; must not raise.
        log = services.ingest_line(
            self.dep, '[13/Jun/2026 16:00:00] "GET / HTTP/1.1" 200 12'
        )
        self.assertIsInstance(log, LogLine)


class ObsOrgIsolationTests(TestCase):
    def setUp(self):
        os.environ["HELM_AUTO_REMEDIATE"] = "0"
        User = get_user_model()
        self.org_a = Org.objects.create(name="A", slug="org-a")
        self.org_b = Org.objects.create(name="B", slug="org-b")
        self.user_a = User.objects.create_user(username="alice", password="pw")
        self.user_b = User.objects.create_user(username="bob", password="pw")
        Membership.objects.create(org=self.org_a, user=self.user_a)
        Membership.objects.create(org=self.org_b, user=self.user_b)

        self.project_a = Project.objects.create(name="PA", slug="pa", org=self.org_a)
        self.dep_a = _mk_dep(self.project_a)
        self.monitor_a = Monitor.objects.create(
            org=self.org_a,
            deployment=self.dep_a,
            metric=Monitor.Metric.ERROR_RATE,
            threshold=10.0,
            enabled=True,
        )

    def test_monitor_absent_for_other_org(self):
        self.client.force_login(self.user_b)
        resp = self.client.get(reverse("observability:monitor_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, f"/obs/monitors/{self.monitor_a.pk}/edit/")

    def test_other_org_cannot_mute_or_delete(self):
        self.client.force_login(self.user_b)
        url = reverse("observability:monitor_mute", args=[self.monitor_a.pk])
        self.assertEqual(self.client.post(url, {"minutes": 30}).status_code, 404)
        durl = reverse("observability:monitor_delete", args=[self.monitor_a.pk])
        self.assertEqual(self.client.post(durl).status_code, 404)

    def test_owner_can_mute(self):
        self.client.force_login(self.user_a)
        url = reverse("observability:monitor_mute", args=[self.monitor_a.pk])
        resp = self.client.post(url, {"minutes": 30})
        self.assertEqual(resp.status_code, 302)
        self.monitor_a.refresh_from_db()
        self.assertIsNotNone(self.monitor_a.muted_until)
        self.assertEqual(self.monitor_a.live_status(), "muted")

    def test_other_org_dashboard_and_logs_404(self):
        self.client.force_login(self.user_b)
        self.assertEqual(
            self.client.get(
                reverse("observability:deployment_dashboard", args=[self.dep_a.pk])
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse("observability:deployment_logs", args=[self.dep_a.pk])
            ).status_code,
            404,
        )

    def test_overview_fleet_summary_scoped(self):
        self.client.force_login(self.user_a)
        resp = self.client.get(reverse("observability:overview"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "TOTAL REQ RATE")

    def test_empty_org_overview_no_500(self):
        self.client.force_login(self.user_b)
        resp = self.client.get(reverse("observability:overview"))
        self.assertEqual(resp.status_code, 200)

    def test_window_param_views(self):
        self.client.force_login(self.user_a)
        for window in ("15", "abc", "9999"):
            d = self.client.get(
                reverse("observability:deployment_dashboard", args=[self.dep_a.pk]),
                {"window": window},
            )
            self.assertEqual(d.status_code, 200)
            m = self.client.get(
                reverse("observability:deployment_metrics", args=[self.dep_a.pk]),
                {"window": window},
            )
            self.assertEqual(m.status_code, 200)
        # poll fragment carries window=15
        frag = self.client.get(
            reverse("observability:deployment_metrics", args=[self.dep_a.pk]),
            {"window": "15"},
        )
        self.assertContains(frag, "window=15")

    def test_unauthenticated_redirects(self):
        for name, args in [
            ("observability:overview", []),
            ("observability:monitor_list", []),
            ("observability:deployment_dashboard", [self.dep_a.pk]),
            ("observability:deployment_logs", [self.dep_a.pk]),
        ]:
            resp = self.client.get(reverse(name, args=args))
            self.assertIn(resp.status_code, (301, 302))
