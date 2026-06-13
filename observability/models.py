from django.db import models
from django.utils import timezone


class LogLine(models.Model):
    """A single log line captured from a deployment's process output."""

    class Level(models.TextChoices):
        DEBUG = "debug", "Debug"
        INFO = "info", "Info"
        WARNING = "warning", "Warning"
        ERROR = "error", "Error"

    deployment = models.ForeignKey(
        "deploys.Deployment", on_delete=models.CASCADE, related_name="logs"
    )
    ts = models.DateTimeField(default=timezone.now, db_index=True)
    level = models.CharField(max_length=10, choices=Level.choices, default=Level.INFO)
    message = models.TextField()
    # Optional parsed HTTP fields.
    method = models.CharField(max_length=10, blank=True)
    path = models.CharField(max_length=500, blank=True)
    status_code = models.IntegerField(null=True, blank=True)
    latency_ms = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["-ts"]
        indexes = [models.Index(fields=["deployment", "-ts"])]

    def __str__(self):
        return f"[{self.level}] {self.message[:80]}"


class MetricPoint(models.Model):
    """A time-series metric sample for a deployment (req rate, errors, p95...)."""

    deployment = models.ForeignKey(
        "deploys.Deployment", on_delete=models.CASCADE, related_name="metrics"
    )
    ts = models.DateTimeField(default=timezone.now, db_index=True)
    name = models.CharField(max_length=80)  # e.g. requests, errors, latency_ms
    value = models.FloatField()

    class Meta:
        ordering = ["-ts"]
        indexes = [models.Index(fields=["deployment", "name", "-ts"])]

    def __str__(self):
        return f"{self.name}={self.value}"


class Incident(models.Model):
    """An operational incident — PagerDuty-style — auto-opened from errors."""

    class Severity(models.TextChoices):
        SEV1 = "sev1", "SEV1 — Critical"
        SEV2 = "sev2", "SEV2 — Major"
        SEV3 = "sev3", "SEV3 — Minor"

    class Status(models.TextChoices):
        FIRING = "firing", "Firing"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        REMEDIATING = "remediating", "Remediating"
        RESOLVED = "resolved", "Resolved"

    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="incidents"
    )
    deployment = models.ForeignKey(
        "deploys.Deployment",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="incidents",
    )
    number = models.IntegerField(default=0)
    title = models.CharField(max_length=300)
    severity = models.CharField(
        max_length=10, choices=Severity.choices, default=Severity.SEV2
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.FIRING
    )
    # A stable signature used to dedupe repeated errors into one incident.
    signature = models.CharField(max_length=200, db_index=True, blank=True)
    error_type = models.CharField(max_length=200, blank=True)
    error_message = models.TextField(blank=True)
    traceback = models.TextField(blank=True)
    suspect_file = models.CharField(max_length=500, blank=True)
    suspect_line = models.IntegerField(null=True, blank=True)
    occurrences = models.IntegerField(default=1)

    # The remediation PR an agent produced, if any.
    remediation_pr = models.ForeignKey(
        "vcs.PullRequest",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="incidents",
    )

    created_at = models.DateTimeField(default=timezone.now)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"INC-{self.number} {self.title}"

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("observability:incident_detail", args=[self.pk])
