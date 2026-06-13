"""Enterprise UI: org settings, API keys, and the audit log — all RBAC-gated and
strictly org-scoped via ``Model.objects.for_org(request.org)``.
"""

from __future__ import annotations

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.models import Membership

from . import services
from .models import ApiKey, AuditLog
from .rbac import current_membership, role_required


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
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
                "org.updated",
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
            "active_keys": ApiKey.objects.for_org(org).filter(
                revoked_at__isnull=True
            ).count(),
            "audit_count": AuditLog.objects.for_org(org).count(),
        },
    )


# --------------------------------------------------------------------------- #
# API keys
# --------------------------------------------------------------------------- #
@role_required("admin")
def keys_view(request):
    org = request.org
    keys = ApiKey.objects.for_org(org)
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
    # Show the raw token exactly once, via the message/toast channel.
    messages.success(
        request,
        f"API key “{key.name}” created. Copy it now — it will not be shown again: {raw}",
    )
    return redirect("enterprise:keys")


@role_required("admin")
@require_POST
def key_revoke(request, pk):
    # Scope the lookup to the current org so orgB keys are never reachable.
    key = get_object_or_404(ApiKey.objects.for_org(request.org), pk=pk)
    services.revoke_api_key(key, actor_user=request.user)
    messages.success(request, f"API key “{key.name}” revoked.")
    return redirect("enterprise:keys")


# --------------------------------------------------------------------------- #
# Audit log
# --------------------------------------------------------------------------- #
@role_required("admin")
def audit_view(request):
    rows = AuditLog.objects.for_org(request.org)
    action = (request.GET.get("action") or "").strip()
    actor = (request.GET.get("actor") or "").strip()
    if action:
        rows = rows.filter(action=action)
    if actor:
        rows = rows.filter(actor__icontains=actor)
    rows = rows.select_related("actor_user")[:300]

    actions = (
        AuditLog.objects.for_org(request.org)
        .order_by("action")
        .values_list("action", flat=True)
        .distinct()
    )
    return render(
        request,
        "enterprise/audit.html",
        {
            "rows": rows,
            "actions": sorted(set(actions)),
            "f_action": action,
            "f_actor": actor,
        },
    )


def _forbidden(request):
    from django.http import HttpResponseForbidden
    from django.template.loader import render_to_string

    return HttpResponseForbidden(
        render_to_string("enterprise/403.html", {"required_role": "admin"}, request=request)
    )
