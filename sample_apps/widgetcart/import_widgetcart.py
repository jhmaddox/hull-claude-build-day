#!/usr/bin/env python
"""Import the WidgetCart Node sample into Hull and assert a LIVE HTTP 200.

PROJECTS-4 acceptance: importing a non-Django sample that ships a Procfile +
docker-compose.yml runs the full import pipeline and yields a live deployment
returning HTTP 200 (via Docker Compose when Docker is present, else the process
runtime running ``node server.js``).

Run from the repo root with the project's venv active::

    python sample_apps/widgetcart/import_widgetcart.py

Exits 0 on a live 200, non-zero (with a reason) otherwise. Skips cleanly with a
clear message if Node is unavailable on this box.
"""

import os
import shutil
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SAMPLE_PATH = os.path.join(REPO_ROOT, "sample_apps", "widgetcart")


def _setup_django():
    sys.path.insert(0, REPO_ROOT)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "helm.settings")
    import django

    django.setup()


def main() -> int:
    if shutil.which("node") is None and shutil.which("docker") is None:
        print("SKIP: neither node nor docker is available on this box.")
        return 0

    _setup_django()

    from projects import services as proj_svc
    from projects.models import Project

    # Import (clone -> detect -> verify -> provision -> READY).
    project = proj_svc.import_project(
        "WidgetCart", SAMPLE_PATH, description="Node generality proof"
    )
    if project.status != Project.Status.READY:
        print(f"FAIL: import did not reach READY (status={project.status}).")
        print(project.import_log[-800:])
        return 1
    print(f"OK: imported {project.slug} framework={project.framework}")
    if project.framework != "compose":
        print(f"WARN: expected framework=compose, got {project.framework}")

    # Deploy staging (advances the live import stepper).
    env = project.environments.get(name="staging")
    dep = proj_svc.deploy_environment(env)
    if dep is None:
        print("FAIL: deploy_environment returned no deployment.")
        return 1
    print(f"OK: deploy status={dep.status} port={dep.port}")

    # Poll the deployment port for a live 200.
    import requests

    port = dep.port
    if not port:
        print("FAIL: deployment has no port.")
        return 1

    deadline = time.time() + 30
    last = None
    while time.time() < deadline:
        try:
            resp = requests.get(f"http://127.0.0.1:{port}/", timeout=4)
            last = resp.status_code
            if resp.status_code == 200:
                print(f"PASS: live 200 at http://127.0.0.1:{port}/")
                return 0
        except Exception as exc:  # noqa: BLE001
            last = f"err({exc})"
        time.sleep(1.0)

    print(f"FAIL: never saw a 200 (last={last}).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
