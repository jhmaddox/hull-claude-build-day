import threading

import requests
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from accounts.scoping import org_required, visible

from .models import Deployment, Domain, EnvVar, Environment

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
<title>{title} · Hull</title>
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
  <p><a href="/deploys/">← Back to Hull deployments</a></p>
</div></body></html>"""
    return HttpResponse(html, content_type="text/html", status=status)


def _resolve_env_by_host(request):
    """Resolve an Environment from the inbound Host header via an ACTIVE
    custom Domain. Returns the Environment or None."""
    host = (request.get_host() or "").split(":")[0].strip().lower()
    if not host:
        return None
    domain = (
        Domain.objects.filter(hostname__iexact=host, status=Domain.Status.ACTIVE)
        .select_related("environment", "environment__project")
        .first()
    )
    return domain.environment if domain else None


def _proxy_to(request, environment, path):
    """Forward the request to the environment's live deployment process."""
    deployment = environment.current_deployment
    if (
        deployment is None
        or deployment.status != Deployment.Status.LIVE
        or not deployment.port
    ):
        return _error_page(
            environment.pk,
            "No live deployment",
            f"{environment.project.name} / {environment.name} is not currently "
            "serving a live deployment.",
            status=502,
        )

    upstream = f"http://127.0.0.1:{deployment.port}/{path}"
    if request.META.get("QUERY_STRING"):
        upstream += "?" + request.META["QUERY_STRING"]

    fwd_headers = {}
    for key, value in request.headers.items():
        if key.lower() in _HOP_BY_HOP:
            continue
        fwd_headers[key] = value
    fwd_headers["X-Forwarded-Prefix"] = f"/d/{environment.pk}"
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
            environment.pk,
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


@csrf_exempt
def proxy(request, env_pk=None, path=""):
    """Reverse-proxy a request to the live deployment process for an Environment.

    Two routing modes (UNSCOPED — serves public traffic):
      * legacy path form ``/d/<env_pk>/<path>`` (env_pk provided), and
      * host-based: when no env_pk, resolve the env from an ACTIVE custom
        Domain matching the inbound Host header.
    An unknown host / env yields the 404 not-found page (never a 500).
    """
    if env_pk is not None:
        environment = Environment.objects.filter(pk=env_pk).first()
        if environment is None:
            return _error_page(
                env_pk, "Environment not found",
                "No such environment in Hull.", status=404,
            )
        return _proxy_to(request, environment, path)

    # Host-based routing.
    environment = _resolve_env_by_host(request)
    if environment is None:
        return _error_page(
            None,
            "Domain not configured",
            f"No active Hull environment is bound to host "
            f"{request.get_host()!r}.",
            status=404,
        )
    return _proxy_to(request, environment, path)


# ---------------------------------------------------------------------------
# Caddy on-demand TLS ask endpoint
# ---------------------------------------------------------------------------
@csrf_exempt
def tls_ask(request):
    """Caddy ``on_demand_tls { ask <url> }`` allowlist endpoint.

    GET ?domain=<hostname>:
      * 200 if a known ACTIVE Domain matches -> Caddy may issue a cert.
      * 404 otherwise. Never raises.
    """
    host = (request.GET.get("domain") or "").split(":")[0].strip().lower()
    if not host:
        return HttpResponse("missing domain", status=404, content_type="text/plain")
    ok = Domain.objects.filter(
        hostname__iexact=host, status=Domain.Status.ACTIVE
    ).exists()
    if ok:
        return HttpResponse("ok", status=200, content_type="text/plain")
    return HttpResponse("unknown domain", status=404, content_type="text/plain")


def host_map(request):
    """JSON map of active hostname -> upstream local port, for Caddy/ops.
    UNSCOPED (ops integration)."""
    out = {}
    for d in Domain.objects.filter(status=Domain.Status.ACTIVE).select_related(
        "environment"
    ):
        dep = d.environment.current_deployment
        if dep and dep.status == Deployment.Status.LIVE and dep.port:
            out[d.hostname] = dep.port
    return JsonResponse(out)


# ---------------------------------------------------------------------------
# Deployments UI (org-scoped)
# ---------------------------------------------------------------------------
@org_required
def deploy_list(request):
    deployments = (
        visible(Deployment, request)
        .select_related("environment", "environment__project")
        .order_by("-created_at")[:100]
    )
    return render(request, "deploys/list.html", {"deployments": deployments})


@org_required
def deploy_rows(request):
    """HTMX fragment: just the table rows, for auto-refresh."""
    deployments = (
        visible(Deployment, request)
        .select_related("environment", "environment__project")
        .order_by("-created_at")[:100]
    )
    return render(request, "deploys/_rows.html", {"deployments": deployments})


@org_required
def deploy_detail(request, pk):
    deployment = get_object_or_404(
        visible(Deployment, request).select_related(
            "environment", "environment__project"
        ),
        pk=pk,
    )
    return render(request, "deploys/detail.html", {"deployment": deployment})


def deploy_detail_status(request, pk):
    """HTMX fragment: the status header of a deployment. (Unscoped fragment used
    by the public detail poller; harmless read of status only.)"""
    deployment = get_object_or_404(Deployment, pk=pk)
    return render(request, "deploys/_status.html", {"deployment": deployment})


@org_required
def deploy_stop(request, pk):
    deployment = get_object_or_404(visible(Deployment, request), pk=pk)
    from . import services

    services.stop(deployment)
    messages.success(request, f"Stopped deployment #{deployment.pk}.")
    return redirect(request.META.get("HTTP_REFERER") or reverse("deploys:list"))


@org_required
def deploy_restart(request, pk):
    deployment = get_object_or_404(visible(Deployment, request), pk=pk)
    from . import services

    threading.Thread(target=services.restart, args=(deployment,), daemon=True).start()
    messages.success(request, f"Restarting deployment #{deployment.pk}…")
    return redirect(request.META.get("HTTP_REFERER") or reverse("deploys:list"))


# ---------------------------------------------------------------------------
# Per-environment: deploy history + rollback (org-scoped)
# ---------------------------------------------------------------------------
def _get_env(request, env_pk):
    return get_object_or_404(
        visible(Environment, request).select_related("project"),
        pk=env_pk,
    )


@org_required
def env_history(request, env_pk):
    environment = _get_env(request, env_pk)
    deployments = environment.deployments.order_by("-created_at")[:200]
    return render(
        request,
        "deploys/history.html",
        {"environment": environment, "deployments": deployments},
    )


@org_required
def deploy_rollback(request, env_pk, pk):
    environment = _get_env(request, env_pk)
    target = get_object_or_404(
        visible(Deployment, request), pk=pk, environment=environment
    )
    from . import services

    threading.Thread(
        target=services.rollback, args=(environment, target), daemon=True
    ).start()
    messages.success(
        request, f"Rolling back {environment.name} to deployment #{target.pk}…"
    )
    return redirect(
        request.META.get("HTTP_REFERER")
        or reverse("deploys:history", args=[environment.pk])
    )


# ---------------------------------------------------------------------------
# Per-environment: env-vars & secrets (masked) — org-scoped
# ---------------------------------------------------------------------------
@org_required
def env_vars(request, env_pk):
    environment = _get_env(request, env_pk)
    if request.method == "POST":
        key = (request.POST.get("key") or "").strip()
        value = request.POST.get("value") or ""
        is_secret = bool(request.POST.get("is_secret"))
        if key:
            EnvVar.objects.update_or_create(
                environment=environment,
                key=key,
                defaults={
                    "value": value,
                    "is_secret": is_secret,
                    "org": environment.org,
                    "updated_at": timezone.now(),
                },
            )
            messages.success(request, f"Saved {key}.")
        if request.headers.get("HX-Request"):
            return _env_vars_fragment(request, environment)
        return redirect("deploys:env_vars", env_pk=environment.pk)
    return render(
        request,
        "deploys/env_vars.html",
        {"environment": environment, "vars": environment.env_vars.all()},
    )


def _env_vars_fragment(request, environment):
    return render(
        request,
        "deploys/_env_vars.html",
        {"environment": environment, "vars": environment.env_vars.all()},
    )


@org_required
def env_var_delete(request, env_pk, pk):
    environment = _get_env(request, env_pk)
    ev = get_object_or_404(
        visible(EnvVar, request), pk=pk, environment=environment
    )
    ev.delete()
    if request.headers.get("HX-Request"):
        return _env_vars_fragment(request, environment)
    messages.success(request, "Deleted env-var.")
    return redirect("deploys:env_vars", env_pk=environment.pk)


# ---------------------------------------------------------------------------
# Per-environment: custom domains — org-scoped
# ---------------------------------------------------------------------------
@org_required
def domains(request, env_pk):
    environment = _get_env(request, env_pk)
    if request.method == "POST":
        hostname = (request.POST.get("hostname") or "").strip().lower()
        if hostname:
            obj, created = Domain.objects.get_or_create(
                hostname=hostname,
                defaults={
                    "environment": environment,
                    "org": environment.org,
                    "status": Domain.Status.ACTIVE,
                    "verified_at": timezone.now(),
                },
            )
            if created:
                from core.models import Event

                Event.log(
                    f"bound custom domain {hostname} to {environment.name}",
                    project=environment.project,
                    icon="deploy",
                    level="success",
                )
                messages.success(request, f"Added {hostname}.")
            else:
                messages.error(request, f"{hostname} is already in use.")
        return redirect("deploys:domains", env_pk=environment.pk)
    return render(
        request,
        "deploys/domains.html",
        {"environment": environment, "domains": environment.domains.all()},
    )


@org_required
def domain_delete(request, env_pk, pk):
    environment = _get_env(request, env_pk)
    dom = get_object_or_404(
        visible(Domain, request), pk=pk, environment=environment
    )
    dom.delete()
    messages.success(request, "Removed domain.")
    return redirect("deploys:domains", env_pk=environment.pk)
