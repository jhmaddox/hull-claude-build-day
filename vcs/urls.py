from django.urls import path

from . import views

app_name = "vcs"

urlpatterns = [
    path("", views.pr_list, name="list"),
    path("pr/<int:pk>/", views.pr_detail, name="pr_detail"),
    path("pr/<int:pk>/ci/", views.pr_run_ci, name="pr_ci"),
    path("pr/<int:pk>/merge/", views.pr_merge, name="pr_merge"),
]
