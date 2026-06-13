"""Log/metric ingestion, error detection & incident management.
[OWNER: Slice C agent]

Keep these signatures stable — deploys.services streams lines here.

Parsing model
-------------
``ingest_line`` is fed one raw process-output line at a time from a managed
deployment. It:

* parses Django dev-server / gunicorn request lines into
  method/path/status_code/latency and derives a log level;
* records ``requests`` / ``errors`` / ``latency_ms`` MetricPoints;
* assembles multi-line Python tracebacks using a module-level per-deployment
  buffer, extracts ``error_type`` / ``error_message`` and the deepest stack
  frame that points *into the deployment source tree*
  (``deployment.source_path``), and opens/updates an Incident.

``suspect_file`` is stored **relative to ``deployment.source_path``** so it is
portable to the agent's worktree (where the same repo lives under a different
absolute path). See INTEGRATION NOTE at the bottom.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading

from django.utils import timezone

# --------------------------------------------------------------------------- #
# Per-deployment traceback assembly buffers.  Module-level (process-wide) and
# guarded by a lock because deploys streams lines from a background thread.
# --------------------------------------------------------------------------- #
_BUFFERS: dict[int, dict] = {}
_LOCK = threading.RLock()

# Django dev-server request line:
#   [13/Jun/2026 16:00:00] "GET /checkout HTTP/1.1" 500 145
_DJANGO_REQ = re.compile(
    r'^\[(?P<ts>[^\]]+)\]\s+"(?P<method>[A-Z]+)\s+(?P<path>\S+)\s+HTTP/[\d.]+"\s+'
    r"(?P<status>\d{3})\s+(?P<size>\S+)"
)

# gunicorn / common-access style:
#   ... "GET /checkout HTTP/1.1" 500 145 ...   (status + size after the quote)
_ACCESS_REQ = re.compile(
    r'"(?P<method>[A-Z]+)\s+(?P<path>\S+)\s+HTTP/[\d.]+"\s+'
    r"(?P<status>\d{3})\s+(?P<size>\S+)"
)

# Start of a Python traceback.
_TB_START = re.compile(r"Traceback \(most recent call last\):")

# The exception summary line that closes a traceback, e.g.
#   ValueError: bad input
#   django.core.exceptions.ImproperlyConfigured: ...
#   KeyError
_EXC_SUMMARY = re.compile(r"^(?P<type>[A-Za-z_][\w.]*(Error|Exception|Warning))(?:: (?P<msg>.*))?$")

# A stack frame line:  File "path/to/x.py", line 42, in handler
_FRAME = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+), in (?P<func>.*)$')

# Anything that clearly looks like a fresh request log line (ends a traceback).
_NEW_REQUEST_HINT = re.compile(r'^\[.*\]\s+"[A-Z]+ ')


def ingest_line_lookup(deployment_pk: int, raw: str):
    """Tailer entry point: resolve the deployment by pk then ingest a line.

    Using the pk (not a passed object) keeps ingestion correct when the tailer
    runs in a different process/thread from the one that started the deploy.
    """
    from deploys.models import Deployment

    dep = Deployment.objects.filter(pk=deployment_pk).select_related(
        "environment__project"
    ).first()
    if dep is None:
        return None
    return ingest_line(dep, raw)


def record_metric(deployment, name: str, value: float):
    """Append a MetricPoint."""
    from .models import MetricPoint

    return MetricPoint.objects.create(
        deployment=deployment, name=name, value=float(value)
    )


def next_incident_number(project) -> int:
    from django.db.models import Max

    from .models import Incident

    current = Incident.objects.filter(project=project).aggregate(m=Max("number"))[
        "m"
    ]
    return (current or 0) + 1


# --------------------------------------------------------------------------- #
# Traceback parsing helpers
# --------------------------------------------------------------------------- #
def _extract_exception(tb_lines: list[str]) -> tuple[str, str]:
    """Return (error_type, error_message) from the final summary line."""
    for line in reversed(tb_lines):
        m = _EXC_SUMMARY.match(line.strip())
        if m:
            return m.group("type"), (m.group("msg") or "").strip()
    # Fallback: the last non-empty, non-frame line (the summary may be missing
    # if the traceback was cut short by a new request line).
    for line in reversed(tb_lines):
        txt = line.strip()
        if not txt or _FRAME.match(line) or txt.startswith("Traceback"):
            continue
        if ": " in txt:
            t, _, msg = txt.partition(": ")
            # Only treat as Type: message if the type looks like an identifier.
            if re.match(r"^[A-Za-z_][\w.]*$", t):
                return t, msg
        return "UncaughtException", txt
    return "UncaughtException", ""


def _extract_suspect(tb_lines: list[str], source_path: str) -> tuple[str, int | None]:
    """Find the deepest frame inside the deployment source tree.

    Returns (suspect_file_relative_to_source, suspect_line). Frames are listed
    outermost-first in a traceback, so the *last* matching frame is the deepest
    one in the user's code.
    """
    source_abs = os.path.abspath(source_path) if source_path else ""
    best: tuple[str, int | None] = ("", None)
    deepest_any: tuple[str, int | None] = ("", None)
    for line in tb_lines:
        m = _FRAME.match(line)
        if not m:
            continue
        raw_file = m.group("file")
        ln = int(m.group("line"))
        deepest_any = (raw_file, ln)
        if source_abs:
            file_abs = os.path.abspath(raw_file)
            if file_abs.startswith(source_abs + os.sep) or file_abs == source_abs:
                rel = os.path.relpath(file_abs, source_abs)
                best = (rel, ln)
    if best[0]:
        return best
    # No frame inside source: fall back to the deepest frame, basename only.
    if deepest_any[0]:
        return os.path.basename(deepest_any[0]), deepest_any[1]
    return "", None


def _level_for_status(status: int) -> str:
    from .models import LogLine

    if status >= 500:
        return LogLine.Level.ERROR
    if status >= 400:
        return LogLine.Level.WARNING
    return LogLine.Level.INFO


def _finalize_traceback(deployment, buf: dict):
    """Turn an assembled traceback buffer into an Incident."""
    tb_lines = buf.get("lines", [])
    if not tb_lines:
        return None
    traceback_text = "\n".join(tb_lines)
    error_type, error_message = _extract_exception(tb_lines)
    suspect_file, suspect_line = _extract_suspect(
        tb_lines, getattr(deployment, "source_path", "") or ""
    )
    return open_or_update_incident(
        deployment,
        error_type=error_type,
        error_message=error_message,
        traceback=traceback_text,
        suspect_file=suspect_file,
        suspect_line=suspect_line,
        severity="sev2",
    )


def ingest_line(deployment, raw: str):
    """Parse a raw log line from a deployment's process output. See module doc."""
    from .models import LogLine

    raw = (raw or "").rstrip("\n")
    dep_id = deployment.pk

    method = ""
    path = ""
    status_code = None
    latency_ms = None
    level = LogLine.Level.INFO

    # ----- request line parsing (Django dev-server, then generic access) -----
    req = _DJANGO_REQ.match(raw) or _ACCESS_REQ.search(raw)
    is_request_line = False
    if req:
        is_request_line = True
        method = req.group("method")
        path = req.group("path")[:500]
        try:
            status_code = int(req.group("status"))
        except (TypeError, ValueError):
            status_code = None
        size = req.group("size")
        try:
            latency_ms = float(size)
        except (TypeError, ValueError):
            latency_ms = None
        if status_code is not None:
            level = _level_for_status(status_code)

    # ----- traceback assembly state machine ---------------------------------
    finalize_after = None
    with _LOCK:
        buf = _BUFFERS.get(dep_id)

        if _TB_START.search(raw):
            # Start (or restart) capture.
            _BUFFERS[dep_id] = {"lines": [raw]}
            buf = _BUFFERS[dep_id]
        elif buf is not None:
            # Currently capturing a traceback.
            if is_request_line or _NEW_REQUEST_HINT.match(raw):
                # A fresh request line ends the prior traceback (don't include).
                finalize_after = _BUFFERS.pop(dep_id, None)
            else:
                buf["lines"].append(raw)
                if _EXC_SUMMARY.match(raw.strip()):
                    # Summary line closes the traceback (inclusive).
                    finalize_after = _BUFFERS.pop(dep_id, None)
                elif len(buf["lines"]) > 400:
                    # Safety valve against runaway buffering.
                    finalize_after = _BUFFERS.pop(dep_id, None)

        if level == LogLine.Level.INFO and not is_request_line:
            low = raw.lower()
            if "internal server error" in low or "exception" in low or "error" in low:
                level = LogLine.Level.WARNING

    log = LogLine.objects.create(
        deployment=deployment,
        ts=timezone.now(),
        level=level,
        message=raw[:5000],
        method=method,
        path=path,
        status_code=status_code,
        latency_ms=latency_ms,
    )

    # ----- metrics ----------------------------------------------------------
    if is_request_line:
        record_metric(deployment, "requests", 1)
        if latency_ms is not None:
            record_metric(deployment, "latency_ms", latency_ms)
        if status_code is not None and status_code >= 500:
            record_metric(deployment, "errors", 1)

    # ----- incident from a completed traceback ------------------------------
    if finalize_after:
        try:
            _finalize_traceback(deployment, finalize_after)
        except Exception as exc:  # never let ingestion crash the stream
            print(f"[helm-obs] failed to finalize traceback: {exc}")

    return log


def _compute_signature(error_type, error_message, suspect_file, suspect_line) -> str:
    if suspect_file:
        basis = f"{error_type}:{suspect_file}:{suspect_line}"
    else:
        basis = f"{error_type}:{error_message}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def open_or_update_incident(
    deployment,
    *,
    error_type: str,
    error_message: str,
    traceback: str = "",
    suspect_file: str = "",
    suspect_line: int | None = None,
    severity: str = "sev2",
):
    """Dedupe by signature; open a new Incident + fire alert + auto-remediate."""
    import os as _os

    from core.models import Event

    from .models import Incident

    project = deployment.project if deployment else None
    signature = _compute_signature(
        error_type, error_message, suspect_file, suspect_line
    )

    # Dedupe: an existing unresolved incident with the same signature.
    existing = (
        Incident.objects.filter(signature=signature)
        .exclude(status=Incident.Status.RESOLVED)
        .order_by("created_at")
        .first()
    )
    if existing:
        from django.db.models import F

        Incident.objects.filter(pk=existing.pk).update(occurrences=F("occurrences") + 1)
        existing.refresh_from_db(fields=["occurrences"])
        print(
            f"[helm-pagerduty] INC-{existing.number} re-fired "
            f"(occurrence #{existing.occurrences}): {existing.title}"
        )
        return existing

    title = f"{error_type} in {suspect_file or (deployment and 'deployment') or 'app'}"
    number = next_incident_number(project)
    incident = Incident.objects.create(
        project=project,
        deployment=deployment,
        number=number,
        title=title[:300],
        severity=severity,
        status=Incident.Status.FIRING,
        signature=signature,
        error_type=error_type[:200],
        error_message=error_message,
        traceback=traceback,
        suspect_file=suspect_file[:500],
        suspect_line=suspect_line,
        occurrences=1,
    )

    Event.log(
        f"🚨 INC-{number} {title}",
        project=project,
        actor="pagerduty",
        level="error",
        icon="alert",
        url=incident.get_absolute_url(),
    )
    print(
        "\n" + "=" * 70 + "\n"
        f"🚨 PAGERDUTY  INC-{number}  [{severity.upper()}]  {title}\n"
        f"   {error_type}: {error_message}\n"
        f"   suspect: {suspect_file}:{suspect_line}\n"
        + "=" * 70
    )

    # Auto-remediation (default on). Reads env at call time so it can be
    # toggled for tests / demos.
    if _os.environ.get("HELM_AUTO_REMEDIATE", "1") == "1":
        try:
            from orchestration import service as orch

            orch.remediate(incident.id)
        except Exception as exc:  # remediation must never break ingestion
            print(f"[helm-obs] auto-remediate dispatch failed: {exc}")

    return incident
