from django.urls import path

from . import views

app_name = "deploys"

urlpatterns = [
    path("", views.deploy_list, name="list"),
    path("rows/", views.deploy_rows, name="rows"),
    path("<int:pk>/", views.deploy_detail, name="detail"),
    path("<int:pk>/status/", views.deploy_detail_status, name="status"),
    path("<int:pk>/stop/", views.deploy_stop, name="stop"),
    path("<int:pk>/restart/", views.deploy_restart, name="restart"),
]
