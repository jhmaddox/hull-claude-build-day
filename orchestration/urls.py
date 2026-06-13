from django.urls import path

from . import views

app_name = "orchestration"

urlpatterns = [
    path("", views.workflow_list, name="workflow_list"),
    path("table/", views.workflow_table, name="workflow_table"),
    path("activity/", views.activity, name="activity"),
    path("activity/panel/", views.activity_panel, name="activity_panel"),
    # Agent-org dashboard [ORCHESTRATION-19]
    path("agents/", views.agents_dashboard, name="agents_dashboard"),
    path("agents/panel/", views.agents_panel, name="agents_panel"),
    # Manual remediation trigger [ORCHESTRATION-21]
    path(
        "remediate/<int:incident_id>/",
        views.remediate_incident,
        name="remediate_incident",
    ),
    path("<int:pk>/", views.workflow_detail, name="workflow_detail"),
    path(
        "<int:pk>/panel/",
        views.workflow_detail_panel,
        name="workflow_detail_panel",
    ),
]
