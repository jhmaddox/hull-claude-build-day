from django.db import models
from django.utils import timezone

from accounts.models import OrgScopedModel


class PullRequest(OrgScopedModel):
    """A proposed change: a branch diffed against a base, reviewable + mergeable.

    Backed by real git in the project's repo. The diff is computed on demand
    from git but cached here for fast rendering.

    Org-scoped: subclasses ``accounts.models.OrgScopedModel`` which adds a
    nullable ``org`` FK + the ``OrgManager`` (``objects.for_org(...)``). Org is
    kept nullable so the autonomous incident->fix loop (which runs without a
    request, with ``org=None``) keeps working.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        MERGED = "merged", "Merged"
        CLOSED = "closed", "Closed"

    class CIStatus(models.TextChoices):
        NONE = "none", "No CI"
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"

    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="pull_requests"
    )
    worktree = models.ForeignKey(
        "agents.Worktree",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="pull_requests",
    )
    number = models.IntegerField(default=0)
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    base_branch = models.CharField(max_length=200, default="main")
    head_branch = models.CharField(max_length=200)
    head_commit = models.CharField(max_length=64, blank=True)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.OPEN
    )
    ci_status = models.CharField(
        max_length=20, choices=CIStatus.choices, default=CIStatus.NONE
    )

    # Cached diff + stats (recomputed from git when stale).
    diff = models.TextField(blank=True)
    files_changed = models.IntegerField(default=0)
    additions = models.IntegerField(default=0)
    deletions = models.IntegerField(default=0)

    author = models.CharField(max_length=200, default="claude-agent")
    created_at = models.DateTimeField(default=timezone.now)
    merged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"#{self.number} {self.title}"

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("vcs:pr_detail", args=[self.pk])
