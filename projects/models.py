from django.db import models
from django.utils import timezone

from accounts.models import OrgScopedModel


class Project(OrgScopedModel):
    """A software project Hull operates: version control, deploys, agents, ops.

    Org-scoped: subclasses ``accounts.models.OrgScopedModel`` which adds a
    nullable ``org`` FK + the ``OrgManager`` (``objects.for_org(...)``). Org is
    kept nullable so the autonomous incident->fix loop (which runs without a
    request) keeps working with ``org=None``.
    """

    class Status(models.TextChoices):
        IMPORTING = "importing", "Importing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    name = models.CharField(max_length=200)
    # Slug is unique per-org (see Meta.constraints), not globally, so two orgs
    # can each have e.g. an "api" project.
    slug = models.SlugField(max_length=120)
    repo_url = models.CharField(max_length=500, blank=True)
    # Absolute path to the canonical clone Hull manages.
    local_path = models.CharField(max_length=1000, blank=True)
    default_branch = models.CharField(max_length=200, default="main")

    # Detected runtime info.
    framework = models.CharField(max_length=50, default="generic")
    run_command = models.CharField(max_length=500, blank=True)
    install_command = models.CharField(max_length=500, blank=True)
    app_subdir = models.CharField(max_length=300, blank=True, default="")

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.IMPORTING
    )
    description = models.TextField(blank=True)
    import_log = models.TextField(blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["org", "slug"], name="uniq_org_slug"
            ),
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("projects:detail", args=[self.slug])


# Canonical ordered import phases surfaced as a live stepper (PROJECTS-2).
IMPORT_STEPS = [
    ("clone", "Clone"),
    ("detect", "Detect runtime"),
    ("verify", "Verify environment"),
    ("provision", "Provision domain"),
    ("deploy_staging", "Deploy staging"),
    ("deploy_prod", "Deploy prod"),
]


class ImportStep(models.Model):
    """One ordered phase of a project's import, rendered as a live stepper.

    The import flow (``projects.services``) creates these for a project and
    flips their ``state`` as each phase runs, so an HTMX-polled fragment can
    animate pending -> running -> done/failed in real time. Org scoping is
    inherited from the parent ``Project`` (these rows are never queried directly
    cross-tenant — always via a project already resolved through
    ``Project.objects.for_org``).
    """

    class State(models.TextChoices):
        PENDING = "pending", "Pending"
        RUNNING = "running", "Running"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="import_steps"
    )
    key = models.CharField(max_length=40)
    label = models.CharField(max_length=80)
    order = models.IntegerField(default=0)
    state = models.CharField(
        max_length=20, choices=State.choices, default=State.PENDING
    )
    detail = models.CharField(max_length=500, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["project", "order"]
        unique_together = [("project", "key")]

    def __str__(self):
        return f"{self.project.slug}/{self.key}={self.state}"
