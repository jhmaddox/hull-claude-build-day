"""Root-level reverse-proxy routes so every deployment gets a public URL at
``{HELM_BASE_URL}/d/<env_pk>/``. Included by helm/urls.py. Slice A implements
``deploys.views.proxy``."""

from django.urls import path, re_path

from . import views

urlpatterns = [
    path("d/<int:env_pk>/", views.proxy, {"path": ""}, name="proxy_root"),
    re_path(r"^d/(?P<env_pk>\d+)/(?P<path>.*)$", views.proxy, name="proxy"),
]
