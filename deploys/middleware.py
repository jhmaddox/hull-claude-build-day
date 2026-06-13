"""Host-based deployment routing.

If an inbound request's Host header matches an ACTIVE custom Domain bound to an
environment, this middleware reverse-proxies the request straight to that
deployment's process/container — BEFORE Hull's session/CSRF/auth/url routing.
That gives every deployment a real hostname (e.g.
``acme-prod.apps.dev-reservclaims.com``) instead of the ``/d/<pk>/`` path.

Control-plane traffic (the Hull dashboard host, localhost, etc.) has no matching
Domain row, so it passes straight through to normal routing. The legacy
``/d/<pk>/`` path proxy stays mounted as a fallback (the autonomous loop uses it).
"""

from __future__ import annotations


class HostProxyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Lazy import: views pulls in requests/models; keep middleware import light.
        from .views import _proxy_to, _resolve_env_by_host

        try:
            environment = _resolve_env_by_host(request)
        except Exception:  # noqa: BLE001 — never let routing lookup 500 the site
            environment = None

        if environment is not None:
            # Visiting a live app runs inside the long-lived web server, so this
            # is a reliable moment to (idempotently) adopt log tailers — incl.
            # compose tees that would otherwise be missing after a restart or a
            # one-shot deploy. Cheap + best-effort; never block the proxy.
            try:
                from .tailer import ensure_tailers

                ensure_tailers()
            except Exception:  # noqa: BLE001
                pass
            path = request.path_info.lstrip("/")
            return _proxy_to(request, environment, path)

        return self.get_response(request)
