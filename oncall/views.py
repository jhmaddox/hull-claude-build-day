"""oncall views — incident center, schedules, policies, routing, postmortems.

All request views scope by ``request.org`` (via ``accounts.scoping``) so a
member of org A never sees org B's data. Action endpoints are HTMX POST views
guarded by ``org_required`` (login + active org).
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.scoping import org_required, scoped
from core.models import Event
from observability.models import Incident

from .models import (
    ActionItem,
    EscalationPolicy,
    EscalationStep,
    Postmortem,
    RoutingRule,
    Schedule,
    ScheduleMember,
)
from .services import escalation, routing, timeline

User = get_user_model()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _scoped_incident(request, pk):
    """Fetch an incident scoped to the request's org (404 across orgs)."""
    qs = Incident.objects.select_related("project", "deployment")
    org = getattr(request, "org", None)
    qs = qs.filter(org=org) if org is not None else qs.none()
    return get_object_or_404(qs, pk=pk)


def _org_members(request):
    """Users who belong to the request's org (for assign dropdowns)."""
    org = getattr(request, "org", None)
    if org is None:
        return User.objects.none()
    return User.objects.filter(memberships__org=org).distinct()


# --------------------------------------------------------------------------- #
# Incident center
# --------------------------------------------------------------------------- #
@org_required
def board(request):
    """/oncall/ — open-incidents board (org-scoped)."""
    incidents = (
        scoped(Incident, request)
        .select_related("project")
        .exclude(status=Incident.Status.RESOLVED)
        .order_by("-created_at")
    )
    resolved = (
        scoped(Incident, request)
        .filter(status=Incident.Status.RESOLVED)
        .order_by("-resolved_at")[:10]
    )
    ctx = {
        "incidents": incidents,
        "resolved": resolved,
        "open_count": incidents.count(),
    }
    return render(request, "oncall/board.html", ctx)


@org_required
def incident_detail(request, pk):
    incident = _scoped_incident(request, pk)
    ctx = _incident_ctx(request, incident)
    return render(request, "oncall/incident_detail.html", ctx)


def _incident_ctx(request, incident):
    return {
        "incident": incident,
        "entries": timeline.for_incident(incident),
        "members": _org_members(request),
        "routed_rule": routing.route(incident),
        "postmortem": Postmortem.objects.filter(incident=incident).first(),
    }


@org_required
def incident_timeline(request, pk):
    """HTMX fragment: the timeline feed only (pollable)."""
    incident = _scoped_incident(request, pk)
    return render(
        request,
        "oncall/_timeline.html",
        {"incident": incident, "entries": timeline.for_incident(incident)},
    )


# --------------------------------------------------------------------------- #
# Human actions (HTMX POST)
# --------------------------------------------------------------------------- #
def _require_post(request):
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    return None


@org_required
def ack(request, pk):
    bad = _require_post(request)
    if bad:
        return bad
    incident = _scoped_incident(request, pk)
    incident.status = Incident.Status.ACKNOWLEDGED
    incident.acknowledged_at = timezone.now()
    incident.save(update_fields=["status", "acknowledged_at"])
    timeline.record(
        incident,
        "acknowledged",
        f"{request.user} acknowledged INC-{incident.number}",
        actor=str(request.user),
        user=request.user,
    )
    Event.log(
        f"{request.user} acknowledged INC-{incident.number}",
        project=incident.project,
        actor=str(request.user),
        level="warning",
        icon="incident",
        url=f"/oncall/incidents/{incident.pk}/",
    )
    messages.success(request, f"Acknowledged INC-{incident.number}.")
    return _action_response(request, incident)


@org_required
def resolve(request, pk):
    bad = _require_post(request)
    if bad:
        return bad
    incident = _scoped_incident(request, pk)
    incident.status = Incident.Status.RESOLVED
    incident.resolved_at = timezone.now()
    incident.save(update_fields=["status", "resolved_at"])
    timeline.record(
        incident,
        "resolved",
        f"{request.user} resolved INC-{incident.number}",
        actor=str(request.user),
        user=request.user,
    )
    Event.log(
        f"{request.user} resolved INC-{incident.number}",
        project=incident.project,
        actor=str(request.user),
        level="success",
        icon="check",
        url=f"/oncall/incidents/{incident.pk}/",
    )
    # Best-effort auto-stub postmortem for sev1/sev2.
    try:
        from .services import loop as loop_svc

        if (incident.severity or "").lower() in ("sev1", "sev2"):
            loop_svc.maybe_create_stub_postmortem(incident)
    except Exception:
        pass
    messages.success(request, f"Resolved INC-{incident.number}.")
    return _action_response(request, incident)


@org_required
def note(request, pk):
    bad = _require_post(request)
    if bad:
        return bad
    incident = _scoped_incident(request, pk)
    text = (request.POST.get("message") or request.POST.get("text") or "").strip()
    if text:
        timeline.record(
            incident,
            "note",
            text,
            actor=str(request.user),
            user=request.user,
        )
    return _action_response(request, incident)


@org_required
def assign(request, pk):
    bad = _require_post(request)
    if bad:
        return bad
    incident = _scoped_incident(request, pk)
    user_id = request.POST.get("user") or request.POST.get("user_id")
    target = None
    if user_id:
        target = _org_members(request).filter(pk=user_id).first()
    label = str(target) if target else "(unassigned)"
    timeline.record(
        incident,
        "assigned",
        f"{request.user} assigned INC-{incident.number} to {label}",
        actor=str(request.user),
        user=target or request.user,
    )
    messages.success(request, f"Assigned to {label}.")
    return _action_response(request, incident)


@org_required
def tick(request, pk):
    """Idempotent escalation tick (HTMX POST)."""
    bad = _require_post(request)
    if bad:
        return bad
    incident = _scoped_incident(request, pk)
    escalation.tick(incident)
    return _action_response(request, incident)


def _action_response(request, incident):
    """For HTMX requests, return the timeline fragment; else redirect back."""
    if request.headers.get("HX-Request"):
        return render(
            request,
            "oncall/_timeline.html",
            {"incident": incident, "entries": timeline.for_incident(incident)},
        )
    return redirect("oncall:incident_detail", pk=incident.pk)


# --------------------------------------------------------------------------- #
# Postmortems
# --------------------------------------------------------------------------- #
@org_required
def postmortem(request, pk):
    incident = _scoped_incident(request, pk)
    pm = Postmortem.objects.filter(incident=incident).first()
    if request.method == "POST":
        if pm is None:
            pm = Postmortem(incident=incident, org=getattr(request, "org", None))
        pm.summary = (request.POST.get("summary") or "")[:500]
        pm.root_cause = request.POST.get("root_cause") or ""
        pm.impact = request.POST.get("impact") or ""
        pm.resolution = request.POST.get("resolution") or ""
        pm.lessons = request.POST.get("lessons") or ""
        pm.body = request.POST.get("body") or ""
        pm.author = request.user
        pm.updated_at = timezone.now()
        if pm.org is None:
            pm.org = getattr(request, "org", None)
        pm.save()
        # Ordered action items from repeated 'action_item' fields.
        titles = request.POST.getlist("action_item")
        if titles:
            pm.action_items.all().delete()
            for i, title in enumerate(t for t in titles if t.strip()):
                ActionItem.objects.create(
                    postmortem=pm,
                    org=pm.org,
                    title=title.strip()[:300],
                    order=i,
                )
        messages.success(request, "Postmortem saved.")
        return redirect("oncall:postmortem", pk=incident.pk)
    return render(
        request,
        "oncall/postmortem.html",
        {
            "incident": incident,
            "postmortem": pm,
            "action_items": pm.ordered_action_items() if pm else [],
            "members": _org_members(request),
        },
    )


# --------------------------------------------------------------------------- #
# Schedules
# --------------------------------------------------------------------------- #
@org_required
def schedules(request):
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        if name:
            Schedule.objects.create(
                name=name[:200],
                timezone=(request.POST.get("timezone") or "UTC")[:64],
                org=getattr(request, "org", None),
            )
            messages.success(request, f"Created schedule '{name}'.")
        return redirect("oncall:schedules")
    items = scoped(Schedule, request).order_by("name")
    rows = []
    for s in items:
        rows.append({"schedule": s, "current": s.current_oncall()})
    return render(request, "oncall/schedules.html", {"rows": rows})


@org_required
def schedule_detail(request, pk):
    schedule = get_object_or_404(scoped(Schedule, request), pk=pk)
    if request.method == "POST":
        user_id = request.POST.get("user")
        target = _org_members(request).filter(pk=user_id).first() if user_id else None
        if target:
            existing = schedule.members.count()
            order = request.POST.get("order")
            ScheduleMember.objects.create(
                schedule=schedule,
                org=schedule.org,
                user=target,
                order=int(order) if order else existing,
            )
            messages.success(request, f"Added {target} to {schedule.name}.")
        return redirect("oncall:schedule_detail", pk=schedule.pk)
    return render(
        request,
        "oncall/schedule_detail.html",
        {
            "schedule": schedule,
            "members": schedule.ordered_members(),
            "current": schedule.current_oncall(),
            "org_members": _org_members(request),
        },
    )


# --------------------------------------------------------------------------- #
# Escalation policies
# --------------------------------------------------------------------------- #
@org_required
def policies(request):
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        if name:
            EscalationPolicy.objects.create(
                name=name[:200], org=getattr(request, "org", None)
            )
            messages.success(request, f"Created policy '{name}'.")
        return redirect("oncall:policies")
    items = scoped(EscalationPolicy, request).order_by("name")
    return render(request, "oncall/policies.html", {"policies": items})


@org_required
def policy_detail(request, pk):
    policy = get_object_or_404(scoped(EscalationPolicy, request), pk=pk)
    if request.method == "POST":
        sched_id = request.POST.get("target_schedule")
        target_schedule = (
            scoped(Schedule, request).filter(pk=sched_id).first() if sched_id else None
        )
        after = request.POST.get("after_minutes") or 0
        order = request.POST.get("order")
        EscalationStep.objects.create(
            policy=policy,
            org=policy.org,
            target_schedule=target_schedule,
            after_minutes=int(after),
            order=int(order) if order else policy.steps.count(),
        )
        messages.success(request, "Added escalation step.")
        return redirect("oncall:policy_detail", pk=policy.pk)
    return render(
        request,
        "oncall/policy_detail.html",
        {
            "policy": policy,
            "steps": policy.ordered_steps(),
            "schedules": scoped(Schedule, request).order_by("name"),
        },
    )


# --------------------------------------------------------------------------- #
# Routing rules
# --------------------------------------------------------------------------- #
@org_required
def rules(request):
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        policy_id = request.POST.get("policy")
        policy = (
            scoped(EscalationPolicy, request).filter(pk=policy_id).first()
            if policy_id
            else None
        )
        project_id = request.POST.get("project")
        project = None
        if project_id:
            from projects.models import Project

            project = scoped(Project, request).filter(pk=project_id).first()
        RoutingRule.objects.create(
            name=name[:200],
            org=getattr(request, "org", None),
            min_severity=(request.POST.get("min_severity") or "sev3"),
            policy=policy,
            project=project,
            priority=int(request.POST.get("priority") or 0),
        )
        messages.success(request, "Created routing rule.")
        return redirect("oncall:rules")
    from projects.models import Project

    return render(
        request,
        "oncall/rules.html",
        {
            "rules": scoped(RoutingRule, request).order_by("priority", "id"),
            "policies": scoped(EscalationPolicy, request).order_by("name"),
            "projects": scoped(Project, request).order_by("name"),
        },
    )
