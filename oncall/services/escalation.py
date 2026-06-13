"""Pure escalation-step selection (no DB writes)."""

from __future__ import annotations


def next_step(policy, minutes_elapsed):
    """Return the active escalation step for ``minutes_elapsed``.

    The active step is the highest-``order`` step whose ``after_minutes`` is
    ``<= minutes_elapsed``. At ``minutes_elapsed == 0`` this is the first step
    (assuming the first step has ``after_minutes == 0``). The result is
    monotonic: as ``minutes_elapsed`` increases, the returned step's order never
    decreases. Returns ``None`` when no step qualifies (or the policy is None).
    """
    if policy is None:
        return None
    try:
        steps = policy.ordered_steps()
    except Exception:
        steps = []
    eligible = [s for s in steps if (s.after_minutes or 0) <= minutes_elapsed]
    if not eligible:
        return None
    # Highest order wins; tie-break by after_minutes then id for determinism.
    return max(eligible, key=lambda s: (s.order or 0, s.after_minutes or 0, s.id))


def tick(incident, *, now=None):
    """Idempotent escalation tick for an unacked incident.

    Computes minutes elapsed since the incident opened, finds the active
    escalation step (via the incident's routed policy), and records an
    'escalated' TimelineEntry exactly once per step (keyed by ``step_order``).
    Returns the TimelineEntry created this tick, or ``None`` (already-acked,
    no policy/step, or already escalated for the current step). Never raises.
    """
    from django.utils import timezone

    from . import routing, timeline

    try:
        status = (getattr(incident, "status", "") or "").lower()
        if status in ("acknowledged", "remediating", "resolved"):
            return None

        rule = routing.route(incident)
        if rule is None or rule.policy_id is None:
            return None
        policy = rule.policy

        now = now or timezone.now()
        opened = getattr(incident, "created_at", None) or now
        minutes = max(0.0, (now - opened).total_seconds() / 60.0)

        step = next_step(policy, minutes)
        if step is None:
            return None

        if timeline.has_entry(incident, "escalated", step_order=step.order):
            return None  # idempotent: already escalated for this step

        target = step.target_schedule.name if step.target_schedule else "(unassigned)"
        return timeline.record(
            incident,
            "escalated",
            f"Escalated to step #{step.order} (+{step.after_minutes}m) -> {target}",
            actor="pagerduty",
            step_order=step.order,
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[helm-oncall] escalation.tick failed: {exc}")
        return None
