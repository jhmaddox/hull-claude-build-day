"""Minimal working auth + org onboarding. The `accounts` builder workstream
extends this with members management, invitations, and RBAC polish."""

import secrets

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify

from .models import Membership, Org


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
