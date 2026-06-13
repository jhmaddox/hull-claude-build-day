"""Root-level reverse-proxy routes so every deployment gets a public URL at
``{HELM_BASE_URL}/d/<env_pk>/``. Included by helm/urls.py.

Two forms:
  * ``proxy_urlpatterns`` — the legacy path form ``/d/<env_pk>/...`` (kept).
  * ``host_proxy_urlpatterns`` — a host-based catch-all that resolves the target
    environment from the inbound Host header via an active custom Domain. The
    integrator mounts this LAST in the root urlconf (after every app prefix) so
    custom hostnames route to their bound environment. ``deploys.views.proxy``
    falls through to the 404 not-found page for unknown hosts.
"""

from django.urls import path, re_path

from . import views

# Legacy path-form proxy (mounted at site root by the integrator).
urlpatterns = [
    path("d/<int:env_pk>/", views.proxy, {"path": ""}, name="proxy_root"),
    re_path(r"^d/(?P<env_pk>\d+)/(?P<path>.*)$", views.proxy, name="proxy"),
]
proxy_urlpatterns = urlpatterns

# Host-based catch-all (no env_pk -> resolve by Host header). Mount LAST.
host_proxy_urlpatterns = [
    path("", views.proxy, {"path": ""}, name="host_proxy_root"),
    re_path(r"^(?P<path>.*)$", views.proxy, name="host_proxy"),
]
