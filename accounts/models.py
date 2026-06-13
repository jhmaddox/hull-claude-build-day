"""Multitenancy contract for Hull.  [OWNED BY THE MAYOR — stable contract]

Every tenant-scoped record belongs to an Org. New models should subclass
``OrgScopedModel``; existing models add ``org = models.ForeignKey('accounts.Org',
null=True, blank=True, on_delete=models.CASCADE, related_name='+')``.

Request scoping: ``accounts.middleware.CurrentOrgMiddleware`` sets the current
org per request (from the session / membership) into a thread-local AND onto
``request.org``. Views filter by ``request.org`` (see ``accounts/scoping.py``).
"""

from __future__ import annotations

import threading

from django.conf import settings
from django.db import models
from django.utils import timezone

# --------------------------------------------------------------------------- #
# Current-org thread local (set by middleware; read by managers/services).
# --------------------------------------------------------------------------- #
_state = threading.local()


def set_current_org(org):
    _state.org = org


def get_current_org():
    return getattr(_state, "org", None)


def clear_current_org():
    _state.org = None


# --------------------------------------------------------------------------- #
# Tenancy models
# --------------------------------------------------------------------------- #
class Org(models.Model):
    """A tenant. Everything in Hull belongs to exactly one Org."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=120, unique=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Membership(models.Model):
    """A user's role within an Org."""

    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        ADMIN = "admin", "Admin"
        MEMBER = "member", "Member"
        VIEWER = "viewer", "Viewer"

    org = models.ForeignKey(Org, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships"
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MEMBER)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [("org", "user")]
        ordering = ["org", "user"]

    def __str__(self):
        return f"{self.user} @ {self.org} ({self.role})"

    @property
    def can_admin(self):
        return self.role in (self.Role.OWNER, self.Role.ADMIN)


class Invitation(models.Model):
    """A pending invite to join an Org."""

    org = models.ForeignKey(Org, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    role = models.CharField(
        max_length=20, choices=Membership.Role.choices, default=Membership.Role.MEMBER
    )
    token = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"invite {self.email} -> {self.org}"


# --------------------------------------------------------------------------- #
# Org-scoped base model + manager (use for ALL new tenant models)
# --------------------------------------------------------------------------- #
class OrgScopedQuerySet(models.QuerySet):
    def for_org(self, org):
        return self.filter(org=org) if org is not None else self

    def for_current_org(self):
        return self.for_org(get_current_org())


class OrgManager(models.Manager.from_queryset(OrgScopedQuerySet)):
    """Default manager. ``Model.objects`` is unscoped (admin/agents); use
    ``Model.objects.for_current_org()`` / ``.for_org(org)`` in request paths."""


class OrgScopedModel(models.Model):
    """Abstract base: gives a model an ``org`` FK + the OrgManager."""

    org = models.ForeignKey(
        "accounts.Org",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="+",
    )
    objects = OrgManager()

    class Meta:
        abstract = True
