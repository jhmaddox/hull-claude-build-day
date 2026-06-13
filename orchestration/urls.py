from django.urls import path

from . import views

app_name = "orchestration"

urlpatterns = [
    path("", views.workflow_list, name="workflow_list"),
    path("table/", views.workflow_table, name="workflow_table"),
    path("activity/", views.activity, name="activity"),
    path("activity/panel/", views.activity_panel, name="activity_panel"),
    path("<int:pk>/", views.workflow_detail, name="workflow_detail"),
]
