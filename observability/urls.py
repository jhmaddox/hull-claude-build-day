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
    path(
        "deployment/<int:pk>/logs/",
        views.deployment_logs,
        name="deployment_logs",
    ),
]
