import threading

import requests
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import Deployment, Environment

# Headers we must not forward verbatim to/from the upstream app.
_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-encoding",
    "content-length",
    "host",
}


def _error_page(env_pk, title, detail, status=502):
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{title} · Helm</title>
<style>
  html,body{{margin:0;height:100%;background:#0a0c11;color:#e7eaf1;
    font-family:Inter,system-ui,sans-serif;display:grid;place-items:center}}
  .box{{max-width:520px;text-align:center;padding:40px;
    border:1px solid #20242f;border-radius:12px;
    background:linear-gradient(180deg,#12151d,#161a24)}}
  .code{{font-size:54px;font-weight:700;color:#f87171;letter-spacing:-.02em}}
  h1{{font-size:20px;margin:8px 0}}
  p{{color:#8a92a6}}
  a{{color:#6d8bff;text-decoration:none}}
</style></head>
<body><div class="box">
  <div class="code">{status}</div>
  <h1>{title}</h1>
  <p>{detail}</p>
  <p><a href="/deploys/">← Back to Helm deployments</a></p>
</div></body></html>"""
    return HttpResponse(html, content_type="text/html", status=status)


@csrf_exempt
def proxy(request, env_pk, path=""):
    """Reverse-proxy a request to the live deployment process for Environment
    <env_pk> on its local port, so the app is reachable at /d/<env_pk>/<path>."""
    environment = Environment.objects.filter(pk=env_pk).first()
    if environment is None:
        return _error_page(env_pk, "Environment not found",
                           "No such environment in Helm.", status=404)

    deployment = environment.current_deployment
    if deployment is None or deployment.status != Deployment.Status.LIVE or not deployment.port:
        return _error_page(
            env_pk,
            "No live deployment",
            f"{environment.project.name} / {environment.name} is not currently "
            "serving a live deployment.",
            status=502,
        )

    upstream = f"http://127.0.0.1:{deployment.port}/{path}"
    if request.META.get("QUERY_STRING"):
        upstream += "?" + request.META["QUERY_STRING"]

    # Forward headers (minus hop-by-hop), add proxy hints.
    fwd_headers = {}
    for key, value in request.headers.items():
        if key.lower() in _HOP_BY_HOP:
            continue
        fwd_headers[key] = value
    fwd_headers["X-Forwarded-Prefix"] = f"/d/{env_pk}"
    fwd_headers["X-Forwarded-Host"] = request.get_host()
    fwd_headers["X-Forwarded-For"] = request.META.get("REMOTE_ADDR", "")
    fwd_headers["X-Forwarded-Proto"] = "https" if request.is_secure() else "http"
    fwd_headers["Host"] = f"127.0.0.1:{deployment.port}"

    try:
        upstream_resp = requests.request(
            method=request.method,
            url=upstream,
            headers=fwd_headers,
            data=request.body if request.body else None,
            allow_redirects=False,
            stream=True,
            timeout=30,
        )
    except requests.exceptions.RequestException as exc:
        return _error_page(
            env_pk,
            "Upstream unreachable",
            f"Could not reach the deployment process on port {deployment.port}: {exc}",
            status=502,
        )

    content = upstream_resp.content
    response = HttpResponse(
        content,
        status=upstream_resp.status_code,
        content_type=upstream_resp.headers.get("Content-Type"),
    )
    # Set-Cookie must be forwarded one-per-header. requests' CaseInsensitiveDict
    # collapses duplicates into a single comma-joined string, which corrupts
    # session/csrf cookies (breaking the app's cart, logins, etc). Pull the
    # individual values from the underlying urllib3 header container instead.
    set_cookies = []
    try:
        set_cookies = upstream_resp.raw.headers.getlist("Set-Cookie")  # urllib3
    except Exception:  # noqa: BLE001
        sc = upstream_resp.headers.get("Set-Cookie")
        if sc:
            set_cookies = [sc]
    for cookie_str in set_cookies:
        try:
            response.cookies.load(cookie_str)
        except Exception:  # noqa: BLE001
            pass

    for key, value in upstream_resp.headers.items():
        if key.lower() in _HOP_BY_HOP or key.lower() in ("content-type", "set-cookie"):
            continue
        response[key] = value
    return response


# ---------------------------------------------------------------------------
# Deployments UI
# ---------------------------------------------------------------------------
def deploy_list(request):
    deployments = (
        Deployment.objects.select_related("environment", "environment__project")
        .order_by("-created_at")[:100]
    )
    return render(request, "deploys/list.html", {"deployments": deployments})


def deploy_rows(request):
    """HTMX fragment: just the table rows, for auto-refresh."""
    deployments = (
        Deployment.objects.select_related("environment", "environment__project")
        .order_by("-created_at")[:100]
    )
    return render(request, "deploys/_rows.html", {"deployments": deployments})


def deploy_detail(request, pk):
    deployment = get_object_or_404(
        Deployment.objects.select_related("environment", "environment__project"), pk=pk
    )
    return render(request, "deploys/detail.html", {"deployment": deployment})


def deploy_detail_status(request, pk):
    """HTMX fragment: the status header of a deployment."""
    deployment = get_object_or_404(Deployment, pk=pk)
    return render(request, "deploys/_status.html", {"deployment": deployment})


def deploy_stop(request, pk):
    deployment = get_object_or_404(Deployment, pk=pk)
    from . import services

    services.stop(deployment)
    messages.success(request, f"Stopped deployment #{deployment.pk}.")
    return redirect(request.META.get("HTTP_REFERER") or reverse("deploys:list"))


def deploy_restart(request, pk):
    deployment = get_object_or_404(Deployment, pk=pk)
    from . import services

    threading.Thread(target=services.restart, args=(deployment,), daemon=True).start()
    messages.success(request, f"Restarting deployment #{deployment.pk}…")
    return redirect(request.META.get("HTTP_REFERER") or reverse("deploys:list"))
