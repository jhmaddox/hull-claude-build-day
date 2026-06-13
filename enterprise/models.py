"""Enterprise models: org-scoped audit log + API keys.

Both subclass ``accounts.models.OrgScopedModel`` (org FK + OrgManager). ``org`` is
nullable so the autonomous incident->fix loop (which runs without a request /
org) can still write audit rows with ``org=None``.

We NEVER persist the plaintext API token: only its sha256 hex digest
(``hashed_key``) and a human-readable ``prefix`` are stored.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from accounts.models import OrgScopedModel


class AuditLog(OrgScopedModel):
    """An immutable record of a meaningful action taken in an org.

    Written exclusively through ``enterprise.services.record_audit`` so the call
    site never has to worry about exceptions (the helper is loop-safe).
    """

    # actor is a denormalized string ("system", a username, "api:<prefix>") so
    # audit rows survive even if the user is later deleted.
    actor = models.CharField(max_length=150, default="system")
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    action = models.CharField(max_length=120, db_index=True)
    target_type = models.CharField(max_length=120, blank=True)
    target_id = models.CharField(max_length=120, blank=True)
    target_repr = models.CharField(max_length=300, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["org", "-created_at"]),
            models.Index(fields=["action"]),
        ]

    def __str__(self):
        return f"{self.actor} {self.action} {self.target_repr}".strip()


class ApiKey(OrgScopedModel):
    """A programmatic credential scoped to an org.

    The raw token (``hull_...``) is shown to the user exactly once at creation;
    only its sha256 digest is stored. Authentication hashes the presented token
    and looks it up by ``hashed_key``.
    """

    name = models.CharField(max_length=150)
    # First 8 visible chars of the raw token + an ellipsis, e.g. "hull_AbC…".
    prefix = models.CharField(max_length=16)
    hashed_key = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["org", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.prefix})"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None
