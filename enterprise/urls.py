from django.urls import path

from . import auth, views

app_name = "enterprise"

urlpatterns = [
    path("", views.audit_view, name="home"),
    path("settings/", views.settings_view, name="settings"),
    path("keys/", views.keys_view, name="keys"),
    path("keys/create/", views.key_create, name="key_create"),
    path("keys/<int:pk>/revoke/", views.key_revoke, name="key_revoke"),
    path("audit/", views.audit_view, name="audit"),
    path("audit/export.csv", views.audit_export, name="audit_export"),
    path("members/", views.members_view, name="members"),
    path("members/<int:pk>/role/", views.member_role, name="member_role"),
    path("members/<int:pk>/remove/", views.member_remove, name="member_remove"),
    path("api/whoami/", auth.whoami, name="whoami"),
]
