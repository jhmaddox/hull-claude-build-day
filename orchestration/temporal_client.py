"""Shared Temporal client connection for Hull.

Supports Temporal Cloud (API-key auth + TLS) and a local dev server, driven by
settings (which read the standard TEMPORAL_* env vars). Used by both the worker
(``run_worker``) and the dispatcher (``service._run``).
"""

from __future__ import annotations

from django.conf import settings


async def connect():
    """Return a connected temporalio Client per Hull settings.

    Cloud: api_key + tls when HELM_TEMPORAL_API_KEY is set. Local: plain.
    Raises if temporalio is unavailable or the connection fails.
    """
    from temporalio.client import Client

    address = settings.HELM_TEMPORAL_HOST
    namespace = settings.HELM_TEMPORAL_NAMESPACE
    api_key = getattr(settings, "HELM_TEMPORAL_API_KEY", "") or None
    tls = getattr(settings, "HELM_TEMPORAL_TLS", False) or bool(api_key)

    kwargs = {"namespace": namespace}
    if api_key:
        kwargs["api_key"] = api_key
    if tls:
        kwargs["tls"] = True
    return await Client.connect(address, **kwargs)


def connection_label() -> str:
    """Human-readable target for logs/UI (no secrets)."""
    kind = "cloud" if getattr(settings, "HELM_TEMPORAL_API_KEY", "") else "local"
    return f"{settings.HELM_TEMPORAL_HOST} ns={settings.HELM_TEMPORAL_NAMESPACE} ({kind})"
