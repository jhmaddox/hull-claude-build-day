"""Enterprise services: loop-safe audit writes + API key lifecycle.

``record_audit`` is the single write path for the audit log. It NEVER raises:
the entire body is wrapped in try/except so an audit failure can never take down
a request handler or — critically — the autonomous incident->fix loop. Loop /
internal calls simply omit ``request``/``org``/``user`` and get
``actor='system'``, ``org=None``.

Cross-app example (e.g. from observability after opening an incident)::

    from enterprise.services import record_audit
    record_audit("incident.opened", org=org, actor="system", target=incident)

API keys: ``create_api_key`` returns ``(ApiKey, raw)`` where ``raw`` is shown to
the operator exactly once; only ``sha256(raw)`` is persisted.
"""

from __future__ import annotations

import hashlib
import logging
import secrets

from django.utils import timezone

from .models import ApiKey, AuditLog

logger = logging.getLogger("enterprise")

RAW_KEY_PREFIX = "hull_"


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #
def _client_ip(request):
    try:
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        if xff:
            return xff.split(",")[0].strip()
        return request.META.get("REMOTE_ADDR") or None
    except Exception:
        return None


def _target_fields(target):
    """Best-effort extraction of (type, id, repr) from any target object."""
    if target is None:
        return "", "", ""
    try:
        target_type = type(target).__name__
    except Exception:
        target_type = ""
    target_id = ""
    try:
        pk = getattr(target, "pk", None)
        if pk is not None:
            target_id = str(pk)
    except Exception:
        target_id = ""
    target_repr = ""
    try:
        target_repr = str(target)[:300]
    except Exception:
        target_repr = ""
    return target_type, target_id, target_repr


def record_audit(
    action,
    *,
    org=None,
    actor="system",
    actor_user=None,
    target=None,
    metadata=None,
    ip=None,
    request=None,
):
    """Write an :class:`AuditLog` row. Returns the row, or ``None`` on failure.

    Loop-safe: this function NEVER raises. Pass ``request`` to auto-derive
    ``org``, ``actor``, ``actor_user`` and ``ip`` from the current request;
    explicit kwargs win over request-derived values.
    """
    try:
        if request is not None:
            if org is None:
                org = getattr(request, "org", None)
            user = getattr(request, "user", None)
            if actor_user is None and user is not None and getattr(
                user, "is_authenticated", False
            ):
                actor_user = user
            if actor == "system" and actor_user is not None:
                actor = (
                    getattr(actor_user, "username", None)
                    or getattr(actor_user, "email", None)
                    or "system"
                )
            if ip is None:
                ip = _client_ip(request)

        if actor == "system" and actor_user is not None:
            actor = (
                getattr(actor_user, "username", None)
                or getattr(actor_user, "email", None)
                or "system"
            )

        target_type, target_id, target_repr = _target_fields(target)
        action = str(action) if action is not None else ""

        return AuditLog.objects.create(
            org=org,
            actor=actor or "system",
            actor_user=actor_user,
            action=action,
            target_type=target_type,
            target_id=target_id,
            target_repr=target_repr,
            metadata=metadata or {},
            ip=ip,
        )
    except Exception:  # pragma: no cover - defensive; audit must never break flow
        logger.exception("record_audit failed for action=%r", action)
        return None


def audit(request, action, **kw):
    """Convenience wrapper: ``audit(request, 'org.updated', target=org)``."""
    kw.setdefault("request", request)
    return record_audit(action, **kw)


# --------------------------------------------------------------------------- #
# API keys
# --------------------------------------------------------------------------- #
def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create_api_key(org, name, created_by=None):
    """Create an API key for ``org``. Returns ``(ApiKey, raw)``.

    ``raw`` is the only time the plaintext token exists; persist nothing but its
    sha256 digest. Emits ``apikey.created`` audit + a ``core.Event``.
    """
    raw = RAW_KEY_PREFIX + secrets.token_urlsafe(32)
    key = ApiKey.objects.create(
        org=org,
        name=name or "key",
        prefix=raw[:8] + "…",
        hashed_key=hash_key(raw),
        created_by=created_by,
    )
    record_audit(
        "apikey.created",
        org=org,
        actor=getattr(created_by, "username", None) or "system",
        actor_user=created_by,
        target=key,
        metadata={"name": key.name, "prefix": key.prefix},
    )
    _emit_event(
        f"created API key “{key.name}”",
        actor=getattr(created_by, "username", None) or "helm",
        icon="check",
        level="success",
    )
    return key, raw


def verify_api_key(raw):
    """Return the active :class:`ApiKey` for ``raw`` (touching last_used_at), else None."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        key = ApiKey.objects.filter(
            hashed_key=hash_key(raw), revoked_at__isnull=True
        ).first()
    except Exception:
        return None
    if key is None:
        return None
    try:
        key.last_used_at = timezone.now()
        key.save(update_fields=["last_used_at"])
    except Exception:
        pass
    return key


def revoke_api_key(api_key, actor_user=None):
    """Revoke ``api_key`` (idempotent). Emits ``apikey.revoked`` audit + Event."""
    if api_key.revoked_at is None:
        api_key.revoked_at = timezone.now()
        api_key.save(update_fields=["revoked_at"])
    record_audit(
        "apikey.revoked",
        org=api_key.org,
        actor=getattr(actor_user, "username", None) or "system",
        actor_user=actor_user,
        target=api_key,
        metadata={"name": api_key.name, "prefix": api_key.prefix},
    )
    _emit_event(
        f"revoked API key “{api_key.name}”",
        actor=getattr(actor_user, "username", None) or "helm",
        icon="x",
        level="warning",
    )
    return api_key


def _emit_event(verb, *, actor="helm", icon="dot", level="info"):
    """Best-effort activity-feed entry; never raises."""
    try:
        from core.models import Event

        Event.log(verb, actor=actor, level=level, icon=icon)
    except Exception:
        pass
