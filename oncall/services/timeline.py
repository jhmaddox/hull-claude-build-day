"""First-class incident timeline.

``record`` is the single write path and is **exception-safe**: it must NEVER
raise, because it is called from inside the autonomous incident->fix loop. Any
failure is swallowed and logged to stdout so the loop keeps going.
"""

from __future__ import annotations


def record(incident, kind, message, *, actor="helm", user=None, step_order=None):
    """Persist a :class:`oncall.models.TimelineEntry`. Never raises.

    Safe when ``incident.org`` is None (the org FK is nullable). Returns the
    created entry, or ``None`` on any failure.
    """
    try:
        from oncall.models import TimelineEntry

        org = getattr(incident, "org", None)
        return TimelineEntry.objects.create(
            incident=incident,
            org=org,
            kind=kind,
            message=(message or "")[:5000],
            actor=(actor or "helm")[:120],
            user=user if getattr(user, "pk", None) else None,
            step_order=step_order,
        )
    except Exception as exc:  # pragma: no cover - defensive; must never raise
        try:
            print(f"[helm-oncall] timeline.record failed ({kind}): {exc}")
        except Exception:
            pass
        return None


def for_incident(incident):
    """Return this incident's timeline entries, chronological."""
    try:
        from oncall.models import TimelineEntry

        return list(
            TimelineEntry.objects.filter(incident=incident).order_by(
                "created_at", "id"
            )
        )
    except Exception as exc:  # pragma: no cover
        print(f"[helm-oncall] timeline.for_incident failed: {exc}")
        return []


def has_entry(incident, kind, *, step_order=None):
    """True if an entry of ``kind`` (optionally for ``step_order``) exists."""
    try:
        from oncall.models import TimelineEntry

        qs = TimelineEntry.objects.filter(incident=incident, kind=kind)
        if step_order is not None:
            qs = qs.filter(step_order=step_order)
        return qs.exists()
    except Exception as exc:  # pragma: no cover
        print(f"[helm-oncall] timeline.has_entry failed: {exc}")
        return False
