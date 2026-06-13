"""Issues (Jira) — org-scoped work tracking.

The agent backlog lives here: PM agents file tickets via ``issues.services``,
builder agents pick them up. Every tenant record subclasses
``accounts.models.OrgScopedModel`` (nullable ``org`` FK + ``OrgManager``) so the
autonomous loop — which runs without a request/org — keeps working with
``org=None``.

Cross-app links to ``observability.Incident``, ``vcs.PullRequest`` and
``agents.AgentRun`` are nullable + additive (``SET_NULL``) so nothing here can
break the incident -> fix loop.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.models import OrgScopedModel


class Board(OrgScopedModel):
    """A project board — a kanban surface that holds tickets and sprints."""

    name = models.CharField(max_length=200)
    key = models.CharField(
        max_length=12,
        default="HULL",
        help_text="Short prefix used to mint ticket keys, e.g. HULL-1.",
    )
    description = models.TextField(blank=True)
    project = models.ForeignKey(
        "projects.Project",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="issue_boards",
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.key} · {self.name}"


class Sprint(OrgScopedModel):
    """A time-boxed iteration grouping a set of tickets."""

    class Status(models.TextChoices):
        PLANNED = "planned", "Planned"
        ACTIVE = "active", "Active"
        COMPLETED = "completed", "Completed"

    board = models.ForeignKey(
        Board,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="sprints",
    )
    name = models.CharField(max_length=200)
    goal = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PLANNED
    )
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class Label(OrgScopedModel):
    """A tag applied to tickets (bug, infra, agent, etc.)."""

    name = models.CharField(max_length=60)
    color = models.CharField(max_length=20, default="badge-neutral")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Ticket(OrgScopedModel):
    """A unit of work — the core of the agent backlog."""

    class Type(models.TextChoices):
        STORY = "story", "Story"
        BUG = "bug", "Bug"
        TASK = "task", "Task"
        EPIC = "epic", "Epic"
        INCIDENT = "incident", "Incident"

    class Status(models.TextChoices):
        BACKLOG = "backlog", "Backlog"
        TODO = "todo", "To Do"
        IN_PROGRESS = "in_progress", "In Progress"
        IN_REVIEW = "in_review", "In Review"
        DONE = "done", "Done"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    # Board / sprint placement.
    board = models.ForeignKey(
        Board,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tickets",
    )
    sprint = models.ForeignKey(
        Sprint,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tickets",
    )

    key = models.CharField(max_length=40, blank=True, db_index=True)
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)

    type = models.CharField(max_length=20, choices=Type.choices, default=Type.TASK)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.BACKLOG
    )
    priority = models.CharField(
        max_length=20, choices=Priority.choices, default=Priority.MEDIUM
    )

    # People.
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="assigned_tickets",
    )
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reported_tickets",
    )
    # Agent-friendly free-text actor (PM agent filed it, builder agent picked it).
    assignee_name = models.CharField(max_length=120, blank=True)
    reporter_name = models.CharField(max_length=120, blank=True)

    labels = models.ManyToManyField(Label, blank=True, related_name="tickets")

    # --- Additive, nullable cross-app links (never required) -------------- #
    incident = models.ForeignKey(
        "observability.Incident",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tickets",
    )
    pull_request = models.ForeignKey(
        "vcs.PullRequest",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tickets",
    )
    agent_run = models.ForeignKey(
        "agents.AgentRun",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tickets",
    )

    story_points = models.IntegerField(null=True, blank=True)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "-created_at"]

    def __str__(self):
        return f"{self.key or 'TICKET'} · {self.title}"

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse("issues:ticket", args=[self.pk])

    @property
    def is_done(self):
        return self.status == self.Status.DONE


class Comment(OrgScopedModel):
    """A comment on a ticket."""

    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="comments"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="ticket_comments",
    )
    author_name = models.CharField(max_length=120, blank=True)
    body = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"comment on {self.ticket_id}"

    @property
    def display_author(self):
        if self.author:
            return self.author.get_username()
        return self.author_name or "helm"


class Activity(OrgScopedModel):
    """An audit/timeline entry for a ticket (status change, pick-up, link...)."""

    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="activities"
    )
    actor = models.CharField(max_length=120, default="helm")
    verb = models.CharField(max_length=300)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "activities"

    def __str__(self):
        return f"{self.actor} {self.verb}"
