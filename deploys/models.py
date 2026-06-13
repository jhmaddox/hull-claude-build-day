from django.db import models
from django.utils import timezone

from accounts.models import OrgScopedModel


class Environment(OrgScopedModel):
    """A logical deploy target for a project (e.g. staging, prod, a worktree env).

    Org-scoped via ``accounts.models.OrgScopedModel`` (nullable ``org`` FK +
    ``OrgManager``). The autonomous loop builds envs without a request, so
    ``org`` stays nullable and defaults to ``None``.
    """

    class Kind(models.TextChoices):
        STAGING = "staging", "Staging"
        PROD = "prod", "Production"
        PREVIEW = "preview", "Preview"

    class Runtime(models.TextChoices):
        PROCESS = "process", "Process (subprocess)"
        COMPOSE = "compose", "Docker Compose"

    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="environments"
    )
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.PREVIEW)
    # Runtime selects how the env is deployed. 'process' is the original
    # subprocess path (default, always-available fallback). 'compose' runs a
    # web+db+worker+redis Docker-Compose stack when Docker is present.
    runtime = models.CharField(
        max_length=20, choices=Runtime.choices, default=Runtime.PROCESS
    )
    branch = models.CharField(max_length=200, default="main")
    # Stable port assigned to this environment's current deployment.
    port = models.IntegerField(null=True, blank=True)
    # Source worktree for preview environments (string ref avoids circular import).
    worktree = models.ForeignKey(
        "agents.Worktree",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="environments",
    )
    auto_deploy = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["project", "kind", "name"]
        unique_together = [("project", "name")]

    def __str__(self):
        return f"{self.project.slug}/{self.name}"

    @property
    def current_deployment(self):
        return self.deployments.exclude(status=Deployment.Status.STOPPED).order_by(
            "-created_at"
        ).first()

    @property
    def public_url(self):
        from django.conf import settings

        return f"{settings.HELM_BASE_URL.rstrip('/')}/d/{self.pk}/"

    @property
    def primary_domain(self):
        """First active custom Domain bound to this env, if any."""
        return self.domains.filter(status=Domain.Status.ACTIVE).order_by(
            "created_at"
        ).first()


class Deployment(OrgScopedModel):
    """A single build+run of an environment at a specific commit.

    Org-scoped; ``org`` is denormalized from ``environment.org`` at create time
    (may be ``None`` for the autonomous loop).
    """

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        BUILDING = "building", "Building"
        LIVE = "live", "Live"
        FAILED = "failed", "Failed"
        STOPPED = "stopped", "Stopped"

    class Health(models.TextChoices):
        UNKNOWN = "unknown", "Unknown"
        HEALTHY = "healthy", "Healthy"
        UNHEALTHY = "unhealthy", "Unhealthy"

    environment = models.ForeignKey(
        Environment, on_delete=models.CASCADE, related_name="deployments"
    )
    commit_sha = models.CharField(max_length=64, blank=True)
    commit_message = models.CharField(max_length=500, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.QUEUED
    )
    health = models.CharField(
        max_length=20, choices=Health.choices, default=Health.UNKNOWN
    )
    port = models.IntegerField(null=True, blank=True)
    pid = models.IntegerField(null=True, blank=True)
    # Absolute path to the checked-out source this deployment runs from.
    source_path = models.CharField(max_length=1000, blank=True)
    log_path = models.CharField(max_length=1000, blank=True)
    build_log = models.TextField(blank=True)
    error = models.TextField(blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    live_at = models.DateTimeField(null=True, blank=True)
    stopped_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.environment} @ {self.commit_sha[:8]} ({self.status})"

    @property
    def project(self):
        return self.environment.project

    @property
    def public_url(self):
        return self.environment.public_url

    @property
    def is_running(self):
        return self.status == self.Status.LIVE and self.pid is not None


class EnvVar(OrgScopedModel):
    """A per-environment configuration / secret value.

    Secret values are masked on read in every UI/HTMX response; the raw value is
    only ever used at deploy time to populate the child process / container env.
    """

    MASK = "••••••"

    environment = models.ForeignKey(
        Environment, on_delete=models.CASCADE, related_name="env_vars"
    )
    key = models.CharField(max_length=200)
    value = models.TextField(blank=True)
    is_secret = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["key"]
        unique_together = [("environment", "key")]

    def __str__(self):
        return f"{self.environment}:{self.key}"

    @property
    def display_value(self):
        """Masked value safe to render in any read response."""
        return self.MASK if self.is_secret else self.value


class Domain(OrgScopedModel):
    """A custom hostname bound to an environment for host-based proxy routing
    and Caddy on-demand TLS."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACTIVE = "active", "Active"
        ERROR = "error", "Error"

    environment = models.ForeignKey(
        Environment, on_delete=models.CASCADE, related_name="domains"
    )
    hostname = models.CharField(max_length=253, unique=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["hostname"]

    def __str__(self):
        return self.hostname
