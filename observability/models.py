from django.db import models
from django.utils import timezone

from accounts.models import OrgScopedModel


class LogLine(models.Model):
    """A single log line captured from a deployment's process output.

    Multitenancy: an additive nullable ``org`` FK (per the tenancy contract).
    Kept NULLABLE so the autonomous incident->fix loop (which ingests lines with
    no request context) keeps working with ``org=None``.
    """

    # Additive org FK. Nullable -> loop-safe (services default org=None).
    org = models.ForeignKey(
        "accounts.Org",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="+",
    )

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
    """A time-series metric sample for a deployment (req rate, errors, p95...).

    Additive nullable ``org`` FK; nullable -> loop-safe.
    """

    org = models.ForeignKey(
        "accounts.Org",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="+",
    )
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

    class Source(models.TextChoices):
        AUTO = "auto", "Auto-detected"
        MANUAL = "manual", "Manually declared"

    # Additive nullable org FK; nullable -> loop-safe.
    org = models.ForeignKey(
        "accounts.Org",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="+",
    )
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

    # How this incident came to exist. ``auto`` (the default) is what the
    # detector / monitor breach path writes; ``manual`` is a human "Declare
    # incident". Defaulted -> existing rows + the loop are unaffected.
    source = models.CharField(
        max_length=10, choices=Source.choices, default=Source.AUTO
    )
    # Username of the human who declared a manual incident (blank for auto).
    declared_by = models.CharField(max_length=150, blank=True)

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


class Monitor(OrgScopedModel):
    """A threshold alert on a deployment metric (Datadog-style monitor).

    When ``evaluate_monitors`` computes the configured ``metric`` for the
    deployment over ``window_minutes`` and the comparator/threshold fires, an
    Incident is opened via the existing ``open_or_update_incident`` (feeding the
    autonomous remediation loop). Org-scoped via ``OrgScopedModel`` (nullable
    org -> loop-safe).
    """

    class Metric(models.TextChoices):
        ERROR_RATE = "error_rate", "Error rate (%)"
        P50 = "p50", "Latency p50 (ms)"
        P95 = "p95", "Latency p95 (ms)"
        P99 = "p99", "Latency p99 (ms)"
        REQ_RATE = "req_rate", "Request rate (req/min)"
        THROUGHPUT = "throughput", "Throughput (total requests)"

    class Comparator(models.TextChoices):
        GT = "gt", "> greater than"
        GTE = "gte", ">= greater or equal"
        LT = "lt", "< less than"
        LTE = "lte", "<= less or equal"

    class Severity(models.TextChoices):
        SEV1 = "sev1", "SEV1 — Critical"
        SEV2 = "sev2", "SEV2 — Major"
        SEV3 = "sev3", "SEV3 — Minor"

    deployment = models.ForeignKey(
        "deploys.Deployment",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="monitors",
    )
    name = models.CharField(max_length=200, blank=True)
    metric = models.CharField(
        max_length=20, choices=Metric.choices, default=Metric.ERROR_RATE
    )
    comparator = models.CharField(
        max_length=4, choices=Comparator.choices, default=Comparator.GT
    )
    threshold = models.FloatField(default=0.0)
    window_minutes = models.IntegerField(default=5)
    severity = models.CharField(
        max_length=10, choices=Severity.choices, default=Severity.SEV2
    )
    enabled = models.BooleanField(default=True)
    # Snooze/mute: while ``muted_until`` is in the future the monitor opens
    # nothing and recovers nothing (purely time-based; auto-expires, no cron).
    # Nullable -> loop-safe, no required value on existing rows.
    muted_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name or f"{self.metric} {self.comparator} {self.threshold}"

    # ----- breach signature (shared by evaluate_monitors + recovery) --------- #
    def breach_error_message(self, window_minutes=None) -> str:
        """The stable ``monitor:<pk> ...`` error_message basis a breach uses.

        Kept identical to what ``evaluate_monitors`` writes so the derived
        signature dedupes/locates this monitor's MonitorBreach incident. The live
        measured value is intentionally NOT part of this string (it lives in the
        incident traceback), so the signature is stable across fluctuating values.
        """
        window = max(1, int(window_minutes or self.window_minutes or 5))
        label = self.get_metric_display()
        return (
            f"monitor:{self.pk} {label} {self.comparator_symbol} "
            f"{self.threshold} over {window}m"
        )

    def breach_signature(self, window_minutes=None) -> str:
        """The Incident.signature a MonitorBreach for this monitor would carry."""
        from .services import _compute_signature

        return _compute_signature(
            "MonitorBreach",
            self.breach_error_message(window_minutes),
            "",
            None,
        )

    @property
    def is_muted(self) -> bool:
        return bool(self.muted_until and self.muted_until > timezone.now())

    def live_status(self) -> str:
        """Derived status: one of ``{"muted","disabled","alerting","ok"}``.

        Order matters: a muted monitor reads as muted even if disabled/alerting;
        a disabled monitor reads disabled; otherwise it is ``alerting`` iff an
        unresolved MonitorBreach incident matches this monitor's signature, else
        ``ok``. Derived (no stored column) to avoid stale state + migration churn.
        """
        if self.is_muted:
            return "muted"
        if not self.enabled:
            return "disabled"
        from .models import Incident  # local to avoid any import surprises

        try:
            sig = self.breach_signature()
            alerting = (
                Incident.objects.filter(
                    error_type="MonitorBreach", signature=sig
                )
                .exclude(status=Incident.Status.RESOLVED)
                .exists()
            )
        except Exception:
            alerting = False
        return "alerting" if alerting else "ok"

    @property
    def status_pill_class(self) -> str:
        """helm.css badge class for the live status pill."""
        return {
            "ok": "badge-success",
            "alerting": "badge-danger",
            "muted": "badge-neutral",
            "disabled": "badge-neutral",
        }.get(self.live_status(), "badge-neutral")

    @property
    def status_label(self) -> str:
        return {
            "ok": "OK",
            "alerting": "Alerting",
            "muted": "Muted",
            "disabled": "Disabled",
        }.get(self.live_status(), "OK")

    @property
    def comparator_symbol(self):
        return {
            self.Comparator.GT: ">",
            self.Comparator.GTE: ">=",
            self.Comparator.LT: "<",
            self.Comparator.LTE: "<=",
        }.get(self.comparator, self.comparator)

    def breaches(self, value) -> bool:
        """True if ``value`` violates this monitor's comparator/threshold."""
        if value is None:
            return False
        t = self.threshold
        c = self.comparator
        if c == self.Comparator.GT:
            return value > t
        if c == self.Comparator.GTE:
            return value >= t
        if c == self.Comparator.LT:
            return value < t
        if c == self.Comparator.LTE:
            return value <= t
        return False

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("observability:monitor_list")
