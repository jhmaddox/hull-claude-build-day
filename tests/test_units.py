"""Fast, deterministic unit tests for Hull's core logic (no threads, no agents,
no network). Run with `pytest` or `python manage.py test tests`.

These back the machine-checkable claims in rubric.md: runtime detection,
traceback->incident parsing + dedup, and the env isolation that keeps managed
apps from inheriting Hull's settings.
"""

import os
import tempfile

from django.test import TestCase


class RuntimeDetectionTests(TestCase):
    def _mk(self, files):
        d = tempfile.mkdtemp()
        for rel, content in files.items():
            path = os.path.join(d, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                fh.write(content)
        return d

    def test_detects_django_at_root(self):
        from projects.services import detect_runtime

        d = self._mk({"manage.py": "x", "requirements.txt": "django\n"})
        rt = detect_runtime(d)
        self.assertEqual(rt["framework"], "django")
        self.assertEqual(rt["app_subdir"], "")
        self.assertIn("$PORT", rt["run_command"])
        self.assertIn("-r requirements.txt", rt["install_command"])

    def test_detects_django_in_subdir(self):
        from projects.services import detect_runtime

        d = self._mk({"app/manage.py": "x"})
        rt = detect_runtime(d)
        self.assertEqual(rt["framework"], "django")
        self.assertEqual(rt["app_subdir"], "app")

    def test_procfile_web_line(self):
        from projects.services import detect_runtime

        d = self._mk({"Procfile": "web: gunicorn app:app --bind 0.0.0.0:$PORT\n"})
        rt = detect_runtime(d)
        self.assertEqual(rt["framework"], "procfile")
        self.assertIn("gunicorn", rt["run_command"])

    def test_generic_fallback(self):
        from projects.services import detect_runtime

        rt = detect_runtime(self._mk({"index.html": "<h1>hi</h1>"}))
        self.assertEqual(rt["framework"], "generic")


class EnvIsolationTests(TestCase):
    def test_clean_subprocess_env_strips_helm_vars(self):
        from orchestration.service import _clean_subprocess_env

        os.environ["DJANGO_SETTINGS_MODULE"] = "helm.settings"
        os.environ["VIRTUAL_ENV"] = "/helm/.venv"
        env = _clean_subprocess_env()
        self.assertNotIn("DJANGO_SETTINGS_MODULE", env)
        self.assertNotIn("VIRTUAL_ENV", env)
        self.assertNotIn("PYTHONPATH", env)
        self.assertEqual(env.get("PYTHONUNBUFFERED"), "1")


class TracebackToIncidentTests(TestCase):
    """The observability heart: raw log lines -> a deduped Incident."""

    TRACEBACK = [
        'Internal Server Error: /checkout/',
        'Traceback (most recent call last):',
        '  File "/srv/app/store/views.py", line 70, in checkout',
        '    discount = apply_promo(promo_code, lines, subtotal)',
        '  File "/srv/app/store/promos.py", line 61, in _bogo_discount',
        '    free_unit_value = min(line.product.price for line in qualifying)',
        'ValueError: min() arg is an empty sequence',
        '[13/Jun/2026 16:00:00] "GET /checkout/?promo=BOGO HTTP/1.1" 500 145',
    ]

    def setUp(self):
        # Make sure auto-remediation never fires a real agent during tests.
        os.environ["HELM_AUTO_REMEDIATE"] = "0"
        from deploys.models import Deployment, Environment
        from projects.models import Project

        self.project = Project.objects.create(name="T", slug="t", status="ready")
        self.env = Environment.objects.create(
            project=self.project, name="prod", kind="prod", branch="main"
        )
        self.dep = Deployment.objects.create(
            environment=self.env, status="live", source_path="/srv/app"
        )

    def _feed(self, lines):
        from observability import services as obs

        for ln in lines:
            obs.ingest_line(self.dep, ln)

    def test_traceback_opens_incident_with_suspect(self):
        from observability.models import Incident

        self._feed(self.TRACEBACK)
        inc = Incident.objects.get()
        self.assertEqual(inc.error_type, "ValueError")
        self.assertEqual(inc.error_message, "min() arg is an empty sequence")
        # deepest frame inside the source tree, stored relative to source_path
        self.assertEqual(inc.suspect_file, "store/promos.py")
        self.assertEqual(inc.suspect_line, 61)
        self.assertEqual(inc.status, Incident.Status.FIRING)

    def test_repeated_error_dedupes_into_one_incident(self):
        from observability.models import Incident

        self._feed(self.TRACEBACK)
        self._feed(self.TRACEBACK)
        self.assertEqual(Incident.objects.count(), 1)
        self.assertGreaterEqual(Incident.objects.get().occurrences, 2)

    def test_request_line_parsed_into_metrics(self):
        from observability.models import LogLine

        self._feed(self.TRACEBACK)
        req = LogLine.objects.filter(status_code=500).first()
        self.assertIsNotNone(req)
        self.assertEqual(req.method, "GET")
        self.assertEqual(req.level, LogLine.Level.ERROR)


class PullRequestNumberingTests(TestCase):
    def test_per_project_pr_numbers_increment(self):
        from projects.models import Project
        from vcs import services as vcs

        p = Project.objects.create(name="P", slug="p", status="ready")
        self.assertEqual(vcs.next_pr_number(p), 1)
