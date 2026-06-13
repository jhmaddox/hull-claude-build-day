"""End-to-end demo driver for Hull.

    python manage.py helm_demo               # import PocketShop + deploy staging & prod
    python manage.py helm_demo --break        # also trigger the prod bug -> autonomous fix
    python manage.py helm_demo --reset        # wipe demo state first

Everything it does is also doable from the UI; this just scripts the happy path
so a judge can watch the whole loop with one command.
"""

import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Run the Hull end-to-end demo."

    def add_arguments(self, parser):
        parser.add_argument(
            "--repo",
            default=str(settings.BASE_DIR / "sample_apps" / "pocketshop"),
            help="Path/URL of the legacy repo to import (default: bundled PocketShop).",
        )
        parser.add_argument("--name", default="PocketShop")
        parser.add_argument(
            "--break", dest="do_break", action="store_true",
            help="Trigger the production bug after deploy to kick off remediation.",
        )
        parser.add_argument(
            "--reset", action="store_true", help="Delete existing demo project first."
        )
        parser.add_argument(
            "--bug-item", dest="bug_item", default="drift-cold-brew-maker",
            help="Slug of a non-qualifying product to put in the cart before BOGO.",
        )

    def log(self, msg, ok=True):
        prefix = self.style.SUCCESS("✓") if ok else self.style.WARNING("…")
        self.stdout.write(f"{prefix} {msg}")

    def handle(self, *args, **opts):
        from deploys import services as deploys
        from deploys.models import Deployment
        from observability.models import Incident
        from projects import services as projects
        from projects.models import Project

        if opts["reset"]:
            Project.objects.filter(name=opts["name"]).delete()
            self.log("reset demo project")

        # 1. Import.
        self.stdout.write(self.style.MIGRATE_HEADING("\n▸ Importing legacy project"))
        project = projects.import_project(opts["name"], opts["repo"])
        if project.status != Project.Status.READY:
            self.stderr.write(f"import failed: {project.import_log[-500:]}")
            return
        self.log(f"imported {project.name} [{project.framework}] @ {project.default_branch}")

        # 2. Deploy staging + prod.
        self.stdout.write(self.style.MIGRATE_HEADING("\n▸ Deploying environments"))
        live = {}
        for env in project.environments.all().order_by("kind"):
            self.log(f"deploying {env.name}…", ok=False)
            dep = deploys.deploy(env)
            ok = dep.status == Deployment.Status.LIVE
            live[env.name] = dep
            url = f"{settings.HELM_BASE_URL.rstrip('/')}/d/{env.pk}/"
            self.log(f"{env.name}: {dep.get_status_display()} → {url}", ok=ok)

        prod = project.environments.filter(kind="prod").first()
        prod_url = f"{settings.HELM_BASE_URL.rstrip('/')}/d/{prod.pk}/"

        # Force the long-lived control-plane server to adopt the new
        # deployments' log tailers (so it ingests the error we're about to
        # trigger). The dashboard/feed call ensure_tailers() on load.
        import requests

        for _ in range(3):
            try:
                requests.get(f"{settings.HELM_BASE_URL.rstrip('/')}/feed/", timeout=5)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(1)

        if not opts["do_break"]:
            self.stdout.write(
                self.style.SUCCESS(f"\n✓ Demo ready. Prod: {prod_url}\n")
            )
            self.stdout.write(
                "  Run with --break to trigger the production incident and watch "
                "the autonomous fix.\n"
            )
            return

        # 3. Trigger the production bug as a real shopper would: add a
        #    non-qualifying item to the cart, then apply the BOGO promo at
        #    checkout (the planted bug crashes on an all-non-qualifying cart).
        self.stdout.write(self.style.MIGRATE_HEADING("\n▸ Triggering production incident"))

        before = Incident.objects.count()
        bug_item = opts.get("bug_item") or "drift-cold-brew-maker"
        s = requests.Session()
        try:
            s.get(prod_url, timeout=10)
            s.get(f"{prod_url}product/{bug_item}/add/", timeout=10)  # non-qualifying item
            trigger = f"{prod_url}checkout/?promo=BOGO"
            r = s.get(trigger, timeout=15)
            self.log(f"shopper applied promo BOGO → {trigger} → {r.status_code}",
                     ok=(r.status_code >= 500))
        except Exception as exc:  # noqa: BLE001
            self.log(f"trigger error (expected on crash): {exc}")

        # 4. Watch the loop.
        self.stdout.write(self.style.MIGRATE_HEADING("\n▸ Autonomous remediation"))
        deadline = time.time() + 600
        inc = None
        while time.time() < deadline:
            inc = Incident.objects.order_by("-created_at").first()
            if inc and Incident.objects.count() > before:
                status = inc.get_status_display()
                pr = inc.remediation_pr
                extra = f" · PR #{pr.number} [{pr.get_ci_status_display()}]" if pr else ""
                self.stdout.write(f"  INC-{inc.number} {inc.title}: {status}{extra}")
                if inc.status == Incident.Status.RESOLVED:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"\n✓ Incident auto-resolved by Claude. Prod healthy: {prod_url}\n"
                        )
                    )
                    return
            time.sleep(5)
        self.stderr.write("timed out watching remediation (check the dashboard)")
