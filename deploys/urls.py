from django.urls import path

from . import views

app_name = "deploys"

urlpatterns = [
    path("", views.deploy_list, name="list"),
    path("rows/", views.deploy_rows, name="rows"),
    # Caddy on-demand TLS ask endpoint + ops host map (public / unscoped).
    path("tls/ask/", views.tls_ask, name="tls_ask"),
    path("tls/hostmap/", views.host_map, name="host_map"),
    # Per-environment management (org-scoped).
    path("env/<int:env_pk>/history/", views.env_history, name="history"),
    path("env/<int:env_pk>/vars/", views.env_vars, name="env_vars"),
    path("env/<int:env_pk>/vars/<int:pk>/delete/", views.env_var_delete, name="env_var_delete"),
    path("env/<int:env_pk>/domains/", views.domains, name="domains"),
    path("env/<int:env_pk>/domains/<int:pk>/delete/", views.domain_delete, name="domain_delete"),
    path("env/<int:env_pk>/rollback/<int:pk>/", views.deploy_rollback, name="rollback"),
    # Deployment detail / actions.
    path("<int:pk>/", views.deploy_detail, name="detail"),
    path("<int:pk>/status/", views.deploy_detail_status, name="status"),
    path("<int:pk>/stop/", views.deploy_stop, name="stop"),
    path("<int:pk>/restart/", views.deploy_restart, name="restart"),
]
