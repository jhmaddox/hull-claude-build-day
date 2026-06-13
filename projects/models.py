from django.db import models
from django.utils import timezone


class Project(models.Model):
    """A software project Helm operates: version control, deploys, agents, ops."""

    class Status(models.TextChoices):
        IMPORTING = "importing", "Importing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=120, unique=True)
    repo_url = models.CharField(max_length=500, blank=True)
    # Absolute path to the canonical clone Helm manages.
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

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("projects:detail", args=[self.slug])
