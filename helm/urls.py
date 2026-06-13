"""Root URL configuration for Helm.

Each Helm app owns its own ``urls.py`` with an ``app_name`` namespace and is
included below. Parallel build agents should ONLY edit their own app's
``urls.py`` — never this file.
"""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("deploys.proxy_urls")),  # /d/<env_pk>/... reverse proxy
    path("", include("core.urls")),
    path("projects/", include("projects.urls")),
    path("deploys/", include("deploys.urls")),
    path("agents/", include("agents.urls")),
    path("vcs/", include("vcs.urls")),
    path("obs/", include("observability.urls")),
    path("orchestration/", include("orchestration.urls")),
]
