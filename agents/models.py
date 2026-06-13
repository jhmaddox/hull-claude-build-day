from django.db import models
from django.utils import timezone

from accounts.models import OrgScopedModel


class Worktree(OrgScopedModel):
    """An isolated git worktree where an agent (or human) works on a branch."""

    class Status(models.TextChoices):
        CREATING = "creating", "Creating"
        ACTIVE = "active", "Active"
        MERGED = "merged", "Merged"
        ARCHIVED = "archived", "Archived"

    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="worktrees"
    )
    name = models.CharField(max_length=200)
    branch = models.CharField(max_length=200)
    base_branch = models.CharField(max_length=200, default="main")
    base_commit = models.CharField(max_length=64, blank=True)
    path = models.CharField(max_length=1000, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.CREATING
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.project.slug}:{self.branch}"


class AgentRun(OrgScopedModel):
    """A headless Claude agent session executing a task in a worktree."""

    class Kind(models.TextChoices):
        FEATURE = "feature", "Feature"
        REMEDIATION = "remediation", "Remediation"
        CI = "ci", "CI"
        REVIEW = "review", "Review"
        CHORE = "chore", "Chore"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="agent_runs"
    )
    worktree = models.ForeignKey(
        Worktree,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="agent_runs",
    )
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.FEATURE)
    title = models.CharField(max_length=300)
    prompt = models.TextField()
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.QUEUED
    )

    # Streaming output captured from the claude CLI (newline-delimited).
    output = models.TextField(blank=True)
    result_summary = models.TextField(blank=True)
    num_turns = models.IntegerField(default=0)
    cost_usd = models.FloatField(null=True, blank=True)
    error = models.TextField(blank=True)

    # Cross-app links (string refs avoid circular imports).
    pull_request = models.ForeignKey(
        "vcs.PullRequest",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="agent_runs",
    )
    incident = models.ForeignKey(
        "observability.Incident",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="agent_runs",
    )

    created_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.kind}] {self.title}"

    def append_output(self, text):
        """Append streamed text and persist just that field.

        Uses Concat (not ``F("output") + text``) because SQLite coerces ``+``
        to numeric addition, which would turn the text column into 0.
        """
        from django.db.models.functions import Concat
        from django.db.models import Value

        AgentRun.objects.filter(pk=self.pk).update(
            output=Concat(models.F("output"), Value(text))
        )
