from django.urls import path

from . import views

app_name = "observability"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("incidents/", views.incident_list, name="incident_list"),
    path("incidents/<int:pk>/", views.incident_detail, name="incident_detail"),
    path(
        "incidents/<int:pk>/status/",
        views.incident_status,
        name="incident_status",
    ),
    path(
        "incidents/<int:pk>/remediate/",
        views.incident_remediate,
        name="incident_remediate",
    ),
    # Per-deployment observability.
    path(
        "deployment/<int:pk>/",
        views.deployment_dashboard,
        name="deployment_dashboard",
    ),
    path(
        "deployment/<int:pk>/metrics/",
        views.deployment_metrics,
        name="deployment_metrics",
    ),
    path(
        "deployment/<int:pk>/logs/",
        views.deployment_logs,
        name="deployment_logs",
    ),
    # Monitors CRUD.
    path("monitors/", views.monitor_list, name="monitor_list"),
    path("monitors/new/", views.monitor_new, name="monitor_new"),
    path("monitors/<int:pk>/edit/", views.monitor_edit, name="monitor_edit"),
    path("monitors/<int:pk>/mute/", views.monitor_mute, name="monitor_mute"),
    path(
        "monitors/<int:pk>/delete/",
        views.monitor_delete,
        name="monitor_delete",
    ),
]
