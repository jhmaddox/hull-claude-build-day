"""Log/metric ingestion, error detection & incident management.
[OWNER: Slice C agent]

Keep these signatures stable — deploys.services streams lines here.
"""

from __future__ import annotations


def ingest_line(deployment, raw: str):
    """Parse a raw log line from a deployment's process output.

    Create a LogLine (parsing Django/gunicorn request lines into method/path/
    status_code/latency_ms and level when possible). Update rolling MetricPoints
    (requests, errors, latency_ms). If the line indicates a server error (HTTP
    5xx, "Traceback (most recent call last)", "Internal Server Error", or an
    uncaught exception), feed it to the error detector which may open/append an
    Incident via open_or_update_incident. Returns the LogLine.

    NOTE: tracebacks span multiple lines — maintain enough buffering on the
    deployment (e.g. a module-level dict keyed by deployment id) to assemble a
    full traceback before opening the incident.
    """
    raise NotImplementedError


def record_metric(deployment, name: str, value: float):
    """Append a MetricPoint."""
    raise NotImplementedError


def next_incident_number(project) -> int:
    raise NotImplementedError


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
    """Dedupe by signature (hash of error_type+top frame). If an unresolved
    Incident with that signature exists, increment occurrences and return it.
    Otherwise create one (status=FIRING), fire the PagerDuty-style alert
    (core.Event + console), and — if the project has auto-remediation enabled —
    kick off orchestration.remediate(incident) which spawns a remediation
    agent. Returns the Incident.
    """
    raise NotImplementedError
