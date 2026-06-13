from django.urls import path

from . import views

app_name = "orchestration"

urlpatterns = [
    path("", views.workflow_list, name="workflow_list"),
    path("table/", views.workflow_table, name="workflow_table"),
    path("<int:pk>/", views.workflow_detail, name="workflow_detail"),
]
