"""Lightweight health + readiness endpoints for Hull's per-deployment checks.

``GET /healthz`` returns a small JSON 200 with no DB write (a cheap read-only
connectivity probe), so Hull's ``deploys.services.health_check`` can poll it on
every deployment. It honors the reverse-proxy subpath because it is wired
through ``{% url %}`` / the normal URLconf (FORCE_SCRIPT_NAME applies).
"""
import time

from django.db import connection
from django.http import JsonResponse

# Process start time, so /healthz can report uptime without any DB write.
_STARTED_AT = time.time()


def healthz(request):
    """Return 200 JSON if the process is up and the DB is reachable.

    Performs only a trivial read-only ``SELECT 1`` (no writes) so it is safe to
    poll frequently and never mutates demo data.
    """
    db_ok = True
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:  # pragma: no cover - DB should always be reachable in demo
        db_ok = False

    payload = {
        "status": "ok" if db_ok else "degraded",
        "service": "pocketshop",
        "db": "ok" if db_ok else "error",
        "uptime_seconds": round(time.time() - _STARTED_AT, 1),
    }
    return JsonResponse(payload, status=200 if db_ok else 503)
