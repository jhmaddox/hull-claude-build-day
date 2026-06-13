"""Enterprise UI: org settings, API keys, the audit log, and member role
management — all RBAC-gated and strictly org-scoped via
``visible(Model, request)`` / ``Membership.objects.filter(org=...)``.
"""

from __future__ import annotations

import csv

from accounts.scoping import visible

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import Membership

from . import audit_actions, services
from .models import ApiKey, AuditLog
from .rbac import current_membership, role_required


@role_required("member")
def settings_view(request):
    org = request.org
    membership = current_membership(request)
    can_edit = membership is not None and membership.role in (
        Membership.Role.OWNER,
        Membership.Role.ADMIN,
    )

    if request.method == "POST":
        if not can_edit:
            return _forbidden(request)
        new_name = (request.POST.get("name") or "").strip()
        if new_name and new_name != org.name:
            old = org.name
            org.name = new_name
            org.save(update_fields=["name"])
            services.audit(
                request,
                audit_actions.ORG_UPDATED,
                target=org,
                metadata={"from": old, "to": new_name},
            )
            services._emit_event(
                f"renamed org to “{new_name}”",
                actor=getattr(request.user, "username", "helm"),
                icon="check",
                level="success",
            )
            messages.success(request, "Organization updated.")
        return redirect("enterprise:settings")

    role_counts = {}
    for m in Membership.objects.filter(org=org):
        role_counts[m.role] = role_counts.get(m.role, 0) + 1
    counts = [
        (label, role_counts.get(value, 0))
        for value, label in Membership.Role.choices
    ]

    return render(
        request,
        "enterprise/settings.html",
        {
            "org": org,
            "can_edit": can_edit,
            "role_counts": counts,
            "member_total": Membership.objects.filter(org=org).count(),
            "active_keys": visible(ApiKey, request).filter(
                revoked_at__isnull=True
            ).count(),
            "audit_count": visible(AuditLog, request).count(),
        },
    )


@role_required("admin")
def keys_view(request):
    org = request.org
    keys = visible(ApiKey, request)
    return render(
        request,
        "enterprise/keys.html",
        {
            "active_keys": keys.filter(revoked_at__isnull=True),
            "revoked_keys": keys.filter(revoked_at__isnull=False),
        },
    )


@role_required("admin")
@require_POST
def key_create(request):
    name = (request.POST.get("name") or "").strip() or "Untitled key"
    key, raw = services.create_api_key(request.org, name, created_by=request.user)
    messages.success(
        request,
        f"API key “{key.name}” created. Copy it now — it will not be shown again: {raw}",
    )
    return redirect("enterprise:keys")


@role_required("admin")
@require_POST
def key_revoke(request, pk):
    key = get_object_or_404(visible(ApiKey, request), pk=pk)
    services.revoke_api_key(key, actor_user=request.user)
    messages.success(request, f"API key “{key.name}” revoked.")
    return redirect("enterprise:keys")


def _filtered_audit_rows(request):
    rows = visible(AuditLog, request)
    action = (request.GET.get("action") or "").strip()
    actor = (request.GET.get("actor") or "").strip()
    if action:
        rows = rows.filter(action=action)
    if actor:
        rows = rows.filter(actor__icontains=actor)
    return rows.select_related("actor_user"), action, actor


@role_required("admin")
def audit_view(request):
    rows, action, actor = _filtered_audit_rows(request)
    paginator = Paginator(rows, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    actions = (
        visible(AuditLog, request)
        .order_by("action")
        .values_list("action", flat=True)
        .distinct()
    )
    return render(
        request,
        "enterprise/audit.html",
        {
            "page_obj": page_obj,
            "rows": page_obj.object_list,
            "actions": sorted(set(actions)),
            "f_action": action,
            "f_actor": actor,
        },
    )


@role_required("admin")
def audit_export(request):
    rows, _action, _actor = _filtered_audit_rows(request)
    response = HttpResponse(content_type="text/csv")
    stamp = timezone.now().strftime("%Y%m%d-%H%M%S")
    response["Content-Disposition"] = f'attachment; filename="audit-{stamp}.csv"'
    writer = csv.writer(response)
    writer.writerow(
        ["created_at", "actor", "action", "target_type", "target_repr", "ip"]
    )
    for r in rows.iterator():
        writer.writerow(
            [
                r.created_at.isoformat(),
                r.actor,
                r.action,
                r.target_type,
                r.target_repr,
                r.ip or "",
            ]
        )
    return response


@role_required("admin")
def members_view(request):
    org = request.org
    memberships = (
        Membership.objects.filter(org=org)
        .select_related("user")
        .order_by("role", "user__username")
    )
    return render(
        request,
        "enterprise/members.html",
        {
            "memberships": memberships,
            "roles": Membership.Role.choices,
            "owner_count": memberships.filter(role=Membership.Role.OWNER).count(),
            "my_membership": current_membership(request),
        },
    )


def _is_last_owner(org, membership) -> bool:
    if membership.role != Membership.Role.OWNER:
        return False
    return (
        Membership.objects.filter(org=org, role=Membership.Role.OWNER).count() <= 1
    )


@role_required("admin")
@require_POST
def member_role(request, pk):
    org = request.org
    membership = get_object_or_404(Membership.objects.filter(org=org), pk=pk)
    new_role = (request.POST.get("role") or "").strip()
    valid = {value for value, _ in Membership.Role.choices}
    if new_role not in valid:
        messages.error(request, "Unknown role.")
        return redirect("enterprise:members")

    old_role = membership.role
    if new_role == old_role:
        return redirect("enterprise:members")

    if old_role == Membership.Role.OWNER and new_role != Membership.Role.OWNER:
        if _is_last_owner(org, membership):
            messages.error(request, "Cannot demote the last owner.")
            return redirect("enterprise:members")

    membership.role = new_role
    membership.save(update_fields=["role"])

    services.record_audit(
        audit_actions.MEMBER_ROLE_CHANGED,
        org=org,
        target=membership,
        metadata={
            "user": getattr(membership.user, "username", str(membership.user)),
            "from": old_role,
            "to": new_role,
        },
        request=request,
    )
    services._emit_event(
        f"changed {membership.user} role {old_role} → {new_role}",
        actor=getattr(request.user, "username", "helm"),
        icon="check",
        level="success",
    )
    messages.success(request, "Member role updated.")
    return redirect("enterprise:members")


@role_required("admin")
@require_POST
def member_remove(request, pk):
    org = request.org
    membership = get_object_or_404(Membership.objects.filter(org=org), pk=pk)
    if _is_last_owner(org, membership):
        messages.error(request, "Cannot remove the last owner.")
        return redirect("enterprise:members")

    username = getattr(membership.user, "username", str(membership.user))
    role = membership.role
    membership.delete()

    services.record_audit(
        audit_actions.MEMBER_REMOVED,
        org=org,
        target=membership,
        metadata={"user": username, "role": role},
        request=request,
    )
    services._emit_event(
        f"removed {username} from the org",
        actor=getattr(request.user, "username", "helm"),
        icon="x",
        level="warning",
    )
    messages.success(request, f"Removed {username}.")
    return redirect("enterprise:members")


def _forbidden(request):
    from django.http import HttpResponseForbidden
    from django.template.loader import render_to_string

    return HttpResponseForbidden(
        render_to_string("enterprise/403.html", {"required_role": "admin"}, request=request)
    )
