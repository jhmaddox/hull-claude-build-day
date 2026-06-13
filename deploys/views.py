from django.http import HttpResponse
from django.shortcuts import render

# Slice A: implement the full deployments UI and the reverse proxy below.


def proxy(request, env_pk, path=""):
    """Reverse-proxy a request to the live deployment process for Environment
    <env_pk> on its local port, so the app is reachable at /d/<env_pk>/<path>.

    STUB — Slice A replaces this with a real streaming proxy to
    127.0.0.1:<deployment.port>.
    """
    return HttpResponse(
        "Deployment proxy not yet implemented.", content_type="text/plain", status=501
    )
