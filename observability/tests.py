import os
from unittest import mock

from django.test import TestCase

from deploys.models import Deployment, Environment
from observability import services
from observability.models import Incident, LogLine, MetricPoint
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
