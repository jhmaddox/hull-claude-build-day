"""API-key Bearer authentication + a session-less whoami endpoint.

This proves programmatic, org-scoped, session-less access: the org is derived
from the API key (``key.org``), never from a session cookie.
"""

from __future__ import annotations

from functools import wraps

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from . import services
from .rbac import role_rank


def _extract_raw(request):
    auth = request.META.get("HTTP_AUTHORIZATION", "")
    if auth:
        parts = auth.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
    # Fallback header.
    x_api = request.META.get("HTTP_X_API_KEY", "")
    if x_api:
        return x_api.strip()
    return None


def resolve_api_key(request):
    """Return the active :class:`ApiKey` for the request's credential, or None."""
    raw = _extract_raw(request)
    if not raw:
        return None
    return services.verify_api_key(raw)


def api_key_required(view):
    """Decorator: 401 JSON unless a valid API key is presented.

    Attaches the resolved key to ``request.api_key`` and its org to
    ``request.org`` for the wrapped view.
    """

    @csrf_exempt
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        key = resolve_api_key(request)
        if key is None:
            return JsonResponse(
                {"error": "unauthorized", "detail": "valid API key required"},
                status=401,
            )
        request.api_key = key
        request.org = key.org
        return view(request, *args, **kwargs)

    return _wrapped


@api_key_required
def whoami(request):
    """GET /enterprise/api/whoami/ — session-less identity for an API key."""
    key = request.api_key
    org = key.org
    return JsonResponse(
        {
            "org": getattr(org, "name", None),
            "org_id": getattr(org, "id", None),
            "org_slug": getattr(org, "slug", None),
            "key": key.prefix,
            "key_name": key.name,
            "role": "api",
            "role_rank": role_rank("api"),
        }
    )
