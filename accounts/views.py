"""Minimal working auth + org onboarding. The `accounts` builder workstream
extends this with members management, invitations, and RBAC polish."""

import secrets

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from .models import Invitation, Membership, Org
from .permissions import is_org_admin, require_org_admin
from .scoping import org_required


def _unique_org_slug(name):
    base = slugify(name) or "org"
    slug, n = base, 1
    while Org.objects.filter(slug=slug).exists():
        n += 1
        slug = f"{base}-{n}"
    return slug


def signup(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        org_name = request.POST.get("org_name", "").strip() or f"{username}'s org"
        if not username or not password:
            messages.error(request, "Username and password are required.")
        elif User.objects.filter(username=username).exists():
            messages.error(request, "That username is taken.")
        else:
            user = User.objects.create_user(username=username, email=email, password=password)
            org = Org.objects.create(name=org_name, slug=_unique_org_slug(org_name))
            Membership.objects.create(org=org, user=user, role=Membership.Role.OWNER)
            login(request, user)
            request.session["org_id"] = org.id
            return redirect("core:dashboard")
    return render(request, "accounts/signup.html")


def login_view(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    if request.method == "POST":
        user = authenticate(
            request,
            username=request.POST.get("username"),
            password=request.POST.get("password"),
        )
        if user is not None:
            login(request, user)
            return redirect(request.GET.get("next") or "core:dashboard")
        messages.error(request, "Invalid credentials.")
    return render(request, "accounts/login.html")


def logout_view(request):
    logout(request)
    return redirect("accounts:login")


@login_required
def onboarding(request):
    """Create a first org if the user has none."""
    if request.method == "POST":
        name = request.POST.get("org_name", "").strip() or "My Org"
        org = Org.objects.create(name=name, slug=_unique_org_slug(name))
        Membership.objects.create(org=org, user=request.user, role=Membership.Role.OWNER)
        request.session["org_id"] = org.id
        return redirect("core:dashboard")
    return render(request, "accounts/onboarding.html")


@login_required
def switch_org(request, org_id):
    membership = get_object_or_404(Membership, user=request.user, org_id=org_id)
    request.session["org_id"] = membership.org_id
    return redirect(request.META.get("HTTP_REFERER") or "core:dashboard")


# --------------------------------------------------------------------------- #
# Members management (ACC-2 / ACC-3)
# --------------------------------------------------------------------------- #
def _owner_count(org):
    return Membership.objects.filter(org=org, role=Membership.Role.OWNER).count()


@org_required
def members(request):
    memberships = (
        Membership.objects.filter(org=request.org)
        .select_related("user")
        .order_by("role", "user__username")
    )
    return render(
        request,
        "accounts/members.html",
        {
            "active": "members",
            "memberships": memberships,
            "roles": Membership.Role.choices,
            "is_admin": is_org_admin(request),
        },
    )


@require_org_admin
def change_role(request, membership_id):
    if request.method != "POST":
        return redirect("accounts:members")
    target = get_object_or_404(Membership, id=membership_id, org=request.org)
    new_role = (request.POST.get("role") or "").strip()
    valid_roles = {r for r, _ in Membership.Role.choices}
    if new_role not in valid_roles:
        messages.error(request, "Invalid role.")
        return redirect("accounts:members")

    # Admins (non-owners) cannot modify owners.
    actor = request.membership
    if target.role == Membership.Role.OWNER and actor.role != Membership.Role.OWNER:
        messages.error(request, "Only an owner can change another owner's role.")
        return redirect("accounts:members")

    # Last-owner guard: never demote the final owner.
    if (
        target.role == Membership.Role.OWNER
        and new_role != Membership.Role.OWNER
        and _owner_count(request.org) <= 1
    ):
        messages.error(request, "Can't demote the last owner of the org.")
        return redirect("accounts:members")

    if target.role != new_role:
        target.role = new_role
        target.save(update_fields=["role"])
        messages.success(request, f"Updated {target.user.username}'s role to {new_role}.")
    return redirect("accounts:members")


@require_org_admin
def remove_member(request, membership_id):
    if request.method != "POST":
        return redirect("accounts:members")
    target = get_object_or_404(Membership, id=membership_id, org=request.org)
    actor = request.membership

    if target.role == Membership.Role.OWNER and actor.role != Membership.Role.OWNER:
        messages.error(request, "Only an owner can remove another owner.")
        return redirect("accounts:members")

    if target.role == Membership.Role.OWNER and _owner_count(request.org) <= 1:
        messages.error(request, "Can't remove the last owner of the org.")
        return redirect("accounts:members")

    username = target.user.username
    target.delete()
    messages.success(request, f"Removed {username} from the org.")
    return redirect("accounts:members")


# --------------------------------------------------------------------------- #
# Invitations (ACC-4)
# --------------------------------------------------------------------------- #
def _unique_invite_token():
    while True:
        token = secrets.token_urlsafe(32)
        if not Invitation.objects.filter(token=token).exists():
            return token


@org_required
def invitations(request):
    if not is_org_admin(request):
        messages.error(request, "You don't have permission to manage invitations.")
        return redirect("accounts:members")

    if request.method == "POST":
        email = (request.POST.get("email") or "").strip()
        role = (request.POST.get("role") or Membership.Role.MEMBER).strip()
        valid_roles = {r for r, _ in Membership.Role.choices}
        if not email:
            messages.error(request, "Email is required.")
        elif role not in valid_roles:
            messages.error(request, "Invalid role.")
        else:
            Invitation.objects.create(
                org=request.org,
                email=email,
                role=role,
                token=_unique_invite_token(),
                invited_by=request.user,
            )
            messages.success(request, f"Invitation sent to {email}.")
        return redirect("accounts:invitations")

    invites = Invitation.objects.filter(org=request.org).select_related("invited_by")
    pending, accepted = [], []
    for inv in invites:
        url = request.build_absolute_uri(
            reverse("accounts:accept_invite", args=[inv.token])
        )
        row = {"invite": inv, "accept_url": url}
        (accepted if inv.accepted_at else pending).append(row)
    return render(
        request,
        "accounts/invitations.html",
        {
            "active": "invitations",
            "pending": pending,
            "accepted": accepted,
            "roles": Membership.Role.choices,
        },
    )


@require_org_admin
def revoke_invite(request, invite_id):
    if request.method != "POST":
        return redirect("accounts:invitations")
    invite = get_object_or_404(
        Invitation, id=invite_id, org=request.org, accepted_at__isnull=True
    )
    email = invite.email
    invite.delete()
    messages.success(request, f"Revoked invitation for {email}.")
    return redirect("accounts:invitations")


# --------------------------------------------------------------------------- #
# Accept invite (ACC-5) — idempotent
# --------------------------------------------------------------------------- #
@login_required
def accept_invite(request, token):
    invite = get_object_or_404(Invitation, token=token)
    membership, created = Membership.objects.get_or_create(
        org=invite.org,
        user=request.user,
        defaults={"role": invite.role},
    )
    if invite.accepted_at is None:
        invite.accepted_at = timezone.now()
        invite.save(update_fields=["accepted_at"])
    request.session["org_id"] = invite.org_id
    if created:
        messages.success(request, f"You've joined {invite.org.name}.")
    else:
        messages.success(request, f"You're already a member of {invite.org.name}.")
    return redirect("core:dashboard")


# --------------------------------------------------------------------------- #
# Org settings (ACC-6)
# --------------------------------------------------------------------------- #
@org_required
def org_settings(request):
    if request.method == "POST":
        if not is_org_admin(request):
            messages.error(request, "You don't have permission to rename the org.")
            return redirect("accounts:org_settings")
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "Organization name can't be empty.")
        else:
            org = request.org
            org.name = name
            org.save(update_fields=["name"])
            messages.success(request, "Organization name updated.")
        return redirect("accounts:org_settings")
    return render(
        request,
        "accounts/org_settings.html",
        {"active": "org", "org": request.org, "is_admin": is_org_admin(request)},
    )


# --------------------------------------------------------------------------- #
# Profile (ACC-7)
# --------------------------------------------------------------------------- #
@login_required
def profile(request):
    if request.method == "POST":
        form = request.POST.get("form")
        if form == "password":
            current = request.POST.get("current_password") or ""
            new1 = request.POST.get("new_password") or ""
            new2 = request.POST.get("confirm_password") or ""
            if not request.user.check_password(current):
                messages.error(request, "Current password is incorrect.")
            elif not new1:
                messages.error(request, "New password can't be empty.")
            elif new1 != new2:
                messages.error(request, "New passwords don't match.")
            else:
                request.user.set_password(new1)
                request.user.save()
                update_session_auth_hash(request, request.user)
                messages.success(request, "Password changed.")
        else:
            user = request.user
            user.first_name = (request.POST.get("first_name") or "").strip()
            user.last_name = (request.POST.get("last_name") or "").strip()
            user.email = (request.POST.get("email") or "").strip()
            user.save(update_fields=["first_name", "last_name", "email"])
            messages.success(request, "Profile updated.")
        return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {"active": "profile", "u": request.user})
