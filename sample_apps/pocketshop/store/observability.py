"""Observability surface for PocketShop.

Hull ingests a deployment's stdout/stderr via
``observability.services.ingest_line`` and parses structured-ish request lines
into ``LogLine`` rows (level, method, path, status_code, latency_ms) plus
``MetricPoint`` latency samples. To make Hull's logs / latency charts / incident
signal look real, PocketShop:

- emits one structured request log line per request (method, path, status,
  latency in ms), at a level that varies with the response status (info for
  2xx/3xx, warning for 4xx, error for 5xx), and
- exposes an intentionally slower endpoint (``/slow/``) so the latency
  distribution Hull plots has a visible p95/p99 tail.

The log format is deliberately greppable and close to a common access-log
shape so Hull's ``ingest_line`` regexes have something to bite on:

    [pocketshop] level=info method=GET path=/ status=200 latency_ms=12.3
"""
import logging
import time

logger = logging.getLogger("pocketshop.access")


def _level_for_status(status_code):
    if status_code >= 500:
        return logging.ERROR
    if status_code >= 400:
        return logging.WARNING
    return logging.INFO


class RequestLogMiddleware:
    """Emit a structured access-log line (with latency) for every request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.perf_counter()
        response = self.get_response(request)
        latency_ms = (time.perf_counter() - start) * 1000.0

        level = _level_for_status(response.status_code)
        levelname = logging.getLevelName(level).lower()
        logger.log(
            level,
            "[pocketshop] level=%s method=%s path=%s status=%s latency_ms=%.1f",
            levelname,
            request.method,
            request.path,
            response.status_code,
            latency_ms,
        )
        # Expose latency to downstream tooling / tests without re-parsing logs.
        response["X-Response-Time-Ms"] = f"{latency_ms:.1f}"
        return response
