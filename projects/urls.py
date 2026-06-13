from django.urls import path

from . import views

app_name = "projects"

urlpatterns = [
    path("", views.project_list, name="list"),
    path("new/", views.project_new, name="new"),
    path("<slug:slug>/", views.project_detail, name="detail"),
    path(
        "<slug:slug>/import-steps/",
        views.import_steps_fragment,
        name="import_steps",
    ),
    path("<slug:slug>/deploy/<int:env_pk>/", views.project_deploy, name="deploy"),
]
