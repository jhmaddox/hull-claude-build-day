from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("signup/", views.signup, name="signup"),
    path("onboarding/", views.onboarding, name="onboarding"),
    path("switch/<int:org_id>/", views.switch_org, name="switch_org"),
    # Build-out: members, invitations, org settings, profile
    path("members/", views.members, name="members"),
    path("members/<int:membership_id>/role/", views.change_role, name="change_role"),
    path("members/<int:membership_id>/remove/", views.remove_member, name="remove_member"),
    path("invitations/", views.invitations, name="invitations"),
    path("invitations/<int:invite_id>/revoke/", views.revoke_invite, name="revoke_invite"),
    path("invite/<str:token>/", views.accept_invite, name="accept_invite"),
    path("org/", views.org_settings, name="org_settings"),
    path("profile/", views.profile, name="profile"),
]
