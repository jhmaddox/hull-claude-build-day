from django.db import models
from django.utils import timezone

from accounts.models import OrgManager


class WorkflowRun(models.Model):
    """A durable, observable unit of orchestration work.

    Backs the orchestration UI. One is created for every top-level call into
    ``orchestration.service`` (import/deploy/agent/ci/remediate) whether the
    work runs on Temporal or the threaded fallback.
    """

    class Status(models.TextChoices):
        RUNNING = "running", "Running"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    name = models.CharField(max_length=200)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.RUNNING
    )
    # Org tenancy (contract): nullable so the autonomous loop can create runs
    # request-less (org=None). Request paths scope via objects.for_org(...).
    org = models.ForeignKey(
        "accounts.Org",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="+",
    )
    project = models.ForeignKey(
        "projects.Project",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="workflow_runs",
    )
    detail = models.TextField(blank=True)
    # Optional pointer back at the entity this workflow operates on
    # (e.g. "incident"/42, "pull_request"/7) — kept loose to avoid FKs.
    ref_type = models.CharField(max_length=40, blank=True)
    ref_id = models.IntegerField(null=True, blank=True)
    backend = models.CharField(max_length=20, default="thread")

    created_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)

    # OrgManager gives WorkflowRun.objects.for_org(org) / .for_current_org().
    objects = OrgManager()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.status})"

    @property
    def duration_s(self):
        end = self.ended_at or timezone.now()
        return (end - self.created_at).total_seconds()

    def append_detail(self, text):
        WorkflowRun.objects.filter(pk=self.pk).update(
            detail=models.F("detail") + text
        )
