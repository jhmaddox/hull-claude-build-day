"""On-call & incident-response models (Incidents v2, PagerDuty-level).

All concrete models subclass :class:`accounts.models.OrgScopedModel`, which
gives each a nullable ``org`` FK + the ``OrgManager`` (``objects.for_org(...)``).
Org is kept NULLABLE on purpose so the autonomous incident->fix loop (which runs
without a request) keeps working with ``org=None``.

This app never modifies ``observability.Incident``'s schema — it only references
it via FK and reads/writes its ``status`` / ``acknowledged_at`` / ``resolved_at``
fields, all of which already exist in the contract.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.timezone import now as _now

from accounts.models import OrgScopedModel


# --------------------------------------------------------------------------- #
# Schedules + weekly rotation
# --------------------------------------------------------------------------- #
class Schedule(OrgScopedModel):
    """An on-call schedule whose members rotate weekly (ISO week index)."""

    name = models.CharField(max_length=200)
    timezone = models.CharField(max_length=64, default="UTC")
    created_at = models.DateTimeField(default=_now)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def ordered_members(self):
        return list(self.members.all().order_by("order", "id"))

    def current_oncall(self, at=None):
        """Return the active member for ``at`` (default now).

        Rotation is deterministic: members are ordered, and the member for a
        given instant is ``members[iso_week_index % len(members)]``. Returns
        ``None`` for an empty schedule.
        """
        members = self.ordered_members()
        if not members:
            return None
        at = at or timezone.now()
        # ISO week number is 1..53; combine with ISO year so the index advances
        # monotonically across year boundaries and is stable per calendar week.
        iso = at.isocalendar()
        iso_year = iso[0]
        iso_week = iso[1]
        week_index = iso_year * 53 + (iso_week - 1)
        return members[week_index % len(members)]


class ScheduleMember(OrgScopedModel):
    """A user in a schedule's rotation; ``order`` defines rotation position."""

    schedule = models.ForeignKey(
        Schedule, on_delete=models.CASCADE, related_name="members"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="oncall_memberships",
    )
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(default=_now)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.user} (#{self.order}) in {self.schedule}"


# --------------------------------------------------------------------------- #
# Escalation policies
# --------------------------------------------------------------------------- #
class EscalationPolicy(OrgScopedModel):
    """An ordered set of escalation steps fired as time elapses unacked."""

    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(default=_now)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def ordered_steps(self):
        return list(self.steps.all().order_by("order", "after_minutes", "id"))


class EscalationStep(OrgScopedModel):
    """One rung of an escalation policy.

    ``after_minutes`` is the time-since-open threshold at which this step
    becomes active; ``order`` is the rung position.
    """

    policy = models.ForeignKey(
        EscalationPolicy, on_delete=models.CASCADE, related_name="steps"
    )
    target_schedule = models.ForeignKey(
        Schedule,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="escalation_steps",
    )
    after_minutes = models.IntegerField(default=0)
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ["order", "after_minutes", "id"]

    def __str__(self):
        return f"step#{self.order} (+{self.after_minutes}m) of {self.policy}"


# --------------------------------------------------------------------------- #
# Alert routing
# --------------------------------------------------------------------------- #
class RoutingRule(OrgScopedModel):
    """Routes an incident to an escalation policy by severity (+ project)."""

    name = models.CharField(max_length=200, blank=True)
    project = models.ForeignKey(
        "projects.Project",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="oncall_routing_rules",
    )
    # Minimum severity this rule handles. sev1 is most severe; we compare by a
    # rank so a rule with min_severity=sev2 also matches sev1 incidents.
    min_severity = models.CharField(max_length=10, default="sev3")
    policy = models.ForeignKey(
        EscalationPolicy,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="routing_rules",
    )
    priority = models.IntegerField(default=0)
    created_at = models.DateTimeField(default=_now)

    class Meta:
        ordering = ["priority", "id"]

    def __str__(self):
        return self.name or f"rule#{self.pk}"


# --------------------------------------------------------------------------- #
# First-class incident timeline
# --------------------------------------------------------------------------- #
class TimelineEntry(OrgScopedModel):
    """A first-class, chronological incident timeline entry."""

    class Kind(models.TextChoices):
        OPENED = "opened", "Opened"
        PAGED = "paged", "Paged"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"
        ESCALATED = "escalated", "Escalated"
        ASSIGNED = "assigned", "Assigned"
        NOTE = "note", "Note"
        AGENT = "agent", "Agent"
        PR = "pr", "Pull request"
        CI = "ci", "CI"
        MERGE = "merge", "Merge"
        DEPLOY = "deploy", "Deploy"
        RESOLVED = "resolved", "Resolved"
        SEVERITY_CHANGED = "severity_changed", "Severity changed"
        REOPENED = "reopened", "Reopened"

    incident = models.ForeignKey(
        "observability.Incident",
        on_delete=models.CASCADE,
        related_name="timeline_entries",
    )
    kind = models.CharField(max_length=20, default=Kind.NOTE)
    message = models.TextField(blank=True)
    # ``actor`` is a free-text label (e.g. "claude-sre", "pagerduty"); ``user``
    # links a human actor when one performed the action.
    actor = models.CharField(max_length=120, default="helm")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="oncall_timeline_entries",
    )
    # For idempotent escalation: which escalation step this entry corresponds to.
    step_order = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=_now, db_index=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["incident", "created_at"])]

    def __str__(self):
        return f"[{self.kind}] {self.message[:60]}"

    @property
    def icon(self):
        return {
            "opened": "alert",
            "paged": "alert",
            "acknowledged": "incident",
            "escalated": "alert",
            "assigned": "agent",
            "note": "log",
            "agent": "agent",
            "pr": "pr",
            "ci": "test",
            "merge": "merge",
            "deploy": "rocket",
            "resolved": "check",
        }.get(self.kind, "dot")


# --------------------------------------------------------------------------- #
# Postmortems + action items
# --------------------------------------------------------------------------- #
class Postmortem(OrgScopedModel):
    """A retrospective for a resolved incident (OneToOne)."""

    incident = models.OneToOneField(
        "observability.Incident",
        on_delete=models.CASCADE,
        related_name="postmortem",
    )
    summary = models.CharField(max_length=500, blank=True)
    root_cause = models.TextField(blank=True)
    impact = models.TextField(blank=True)
    resolution = models.TextField(blank=True)
    lessons = models.TextField(blank=True)
    body = models.TextField(blank=True)  # free-form markdown
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="oncall_postmortems",
    )
    created_at = models.DateTimeField(default=_now)
    updated_at = models.DateTimeField(default=_now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Postmortem for {self.incident}"

    def ordered_action_items(self):
        return list(self.action_items.all().order_by("order", "id"))


class ActionItem(OrgScopedModel):
    """A follow-up action from a postmortem."""

    postmortem = models.ForeignKey(
        Postmortem, on_delete=models.CASCADE, related_name="action_items"
    )
    title = models.CharField(max_length=300)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="oncall_action_items",
    )
    done = models.BooleanField(default=False)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(default=_now)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.title
