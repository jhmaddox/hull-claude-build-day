"""Best-effort hooks the autonomous incident->fix loop calls.

EVERY function here is exception-safe: importing or using oncall must never
block incident creation or remediation. The loop wires these in via lazy,
in-function imports wrapped in ``try/except Exception: pass``.
"""

from __future__ import annotations

from . import routing, timeline


def on_incident_opened(incident):
    """Called from observability.open_or_update_incident after creation.

    Sets ``incident.org`` (best-effort) from the project, seeds an 'opened'
    timeline entry, then routes + seeds a 'paged' entry. Never raises.
    """
    try:
        _ensure_org(incident)
    except Exception as exc:
        print(f"[helm-oncall] on_incident_opened: ensure_org failed: {exc}")
    try:
        timeline.record(
            incident, "opened", f"INC-{incident.number} opened: {incident.title}",
            actor="pagerduty",
        )
    except Exception as exc:
        print(f"[helm-oncall] on_incident_opened: record failed: {exc}")
    try:
        rule = routing.route(incident)
        if rule is not None:
            who = routing.first_oncall_user(incident)
            target = (
                f"{getattr(who, 'username', who)}"
                if who is not None
                else (rule.name or f"rule#{rule.pk}")
            )
            timeline.record(
                incident,
                "paged",
                f"Routed via '{rule.name or rule.pk}' -> paged {target}",
                actor="pagerduty",
            )
    except Exception as exc:
        print(f"[helm-oncall] on_incident_opened: routing failed: {exc}")


def _ensure_org(incident):
    """Best-effort: populate incident.org from its project's org if unset."""
    if getattr(incident, "org_id", None):
        return
    project = getattr(incident, "project", None)
    org = getattr(project, "org", None)
    if org is None:
        return
    incident.org = org
    try:
        incident.save(update_fields=["org"])
    except Exception:
        # Field list may differ; fall back to a full save.
        incident.save()


def on_pipeline_step(incident, kind, message, *, actor="claude-sre"):
    """Record a remediation-pipeline timeline step. Never raises."""
    try:
        timeline.record(incident, kind, message, actor=actor)
    except Exception as exc:
        print(f"[helm-oncall] on_pipeline_step failed: {exc}")


def on_incident_resolved(incident):
    """Called when an incident reaches resolved.

    Best-effort auto-create a stub Postmortem for sev1/sev2 incidents. Never
    raises.
    """
    try:
        timeline.record(
            incident, "resolved", f"INC-{incident.number} resolved",
            actor="claude-sre",
        )
    except Exception as exc:
        print(f"[helm-oncall] on_incident_resolved: record failed: {exc}")
    try:
        if (getattr(incident, "severity", "") or "").lower() in ("sev1", "sev2"):
            maybe_create_stub_postmortem(incident)
    except Exception as exc:
        print(f"[helm-oncall] on_incident_resolved: postmortem failed: {exc}")


def maybe_create_stub_postmortem(incident):
    """Create a stub Postmortem if one doesn't exist. Returns it or None."""
    try:
        from oncall.models import Postmortem

        existing = Postmortem.objects.filter(incident=incident).first()
        if existing:
            return existing
        return Postmortem.objects.create(
            incident=incident,
            org=getattr(incident, "org", None),
            summary=f"INC-{incident.number}: {incident.title}"[:500],
            root_cause=incident.error_message or "",
            impact="",
            resolution=(
                f"Resolved via PR #{incident.remediation_pr.number}"
                if getattr(incident, "remediation_pr_id", None)
                else ""
            ),
            lessons="",
            body="(auto-generated stub — fill in the details)",
        )
    except Exception as exc:  # pragma: no cover
        print(f"[helm-oncall] maybe_create_stub_postmortem failed: {exc}")
        return None
