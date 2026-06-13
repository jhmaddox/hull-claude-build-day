from django.urls import path

from . import auth, views

app_name = "enterprise"

urlpatterns = [
    path("settings/", views.settings_view, name="settings"),
    path("keys/", views.keys_view, name="keys"),
    path("keys/create/", views.key_create, name="key_create"),
    path("keys/<int:pk>/revoke/", views.key_revoke, name="key_revoke"),
    path("audit/", views.audit_view, name="audit"),
    # Session-less, API-key-authenticated JSON endpoint.
    path("api/whoami/", auth.whoami, name="whoami"),
]
