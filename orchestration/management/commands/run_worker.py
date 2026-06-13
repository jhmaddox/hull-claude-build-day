"""Run a Temporal worker for Hull's orchestration task queue.

    python manage.py run_worker

Connects to settings.HELM_TEMPORAL_HOST and serves the workflows/activities
defined in orchestration.temporal_workflows on settings.HELM_TEMPORAL_TASK_QUEUE.
This is only needed when HELM_USE_TEMPORAL=1; the threaded fallback runs
without it.
"""

from __future__ import annotations

import asyncio

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run the Temporal worker for Hull orchestration workflows."

    def handle(self, *args, **options):
        try:
            from temporalio.client import Client
            from temporalio.worker import Worker
        except Exception as exc:  # noqa: BLE001
            self.stderr.write(
                self.style.ERROR(f"temporalio is not available: {exc}")
            )
            return

        from orchestration import temporal_workflows as tw

        host = settings.HELM_TEMPORAL_HOST
        namespace = settings.HELM_TEMPORAL_NAMESPACE
        task_queue = settings.HELM_TEMPORAL_TASK_QUEUE

        async def _main():
            client = await Client.connect(host, namespace=namespace)
            worker = Worker(
                client,
                task_queue=task_queue,
                workflows=tw.WORKFLOWS,
                activities=tw.ACTIVITIES,
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Hull worker connected to {host} (ns={namespace}) "
                    f"on task queue '{task_queue}' — waiting for work…"
                )
            )
            await worker.run()

        try:
            asyncio.run(_main())
        except KeyboardInterrupt:
            self.stdout.write("worker stopped")
