"""Log tailers — decouple log ingestion from the process that spawned a
deployment.

Managed apps write their stdout/stderr to a per-deployment log *file* (so the
app survives whatever process started it). A tailer thread follows that file and
streams each new line into ``observability.services.ingest_line``. Because it
reads a file (not a pipe to a specific process), the long-lived control-plane
server can *adopt* any live deployment — even ones started by a one-shot
management command — via :func:`ensure_tailers`.
"""

from __future__ import annotations

import os
import threading
import time

# Deployment pks currently being tailed *in this process*.
_TAILERS: set[int] = set()
_LOCK = threading.Lock()


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        import psutil

        return psutil.pid_exists(pid)
    except Exception:  # noqa: BLE001
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _tail(deployment_pk: int, log_path: str, from_start: bool):
    from observability import services as obs

    from .models import Deployment

    # Wait briefly for the log file to appear.
    for _ in range(50):
        if os.path.isfile(log_path):
            break
        time.sleep(0.1)
    if not os.path.isfile(log_path):
        with _LOCK:
            _TAILERS.discard(deployment_pk)
        return

    try:
        fh = open(log_path, "r", encoding="utf-8", errors="replace")
    except OSError:
        with _LOCK:
            _TAILERS.discard(deployment_pk)
        return

    if not from_start:
        fh.seek(0, os.SEEK_END)

    idle = 0
    try:
        while True:
            line = fh.readline()
            if line:
                idle = 0
                try:
                    obs.ingest_line_lookup(deployment_pk, line.rstrip("\n"))
                except Exception:  # noqa: BLE001 — ingest must never kill tailer
                    pass
                continue
            # No new data — stop once the process is gone and we've drained.
            time.sleep(0.3)
            idle += 1
            if idle % 10 == 0:
                dep = Deployment.objects.filter(pk=deployment_pk).first()
                if dep is None or not _pid_alive(dep.pid):
                    # Drain any final bytes then exit.
                    rest = fh.read()
                    for r in rest.splitlines():
                        try:
                            obs.ingest_line_lookup(deployment_pk, r)
                        except Exception:  # noqa: BLE001
                            pass
                    break
    finally:
        fh.close()
        with _LOCK:
            _TAILERS.discard(deployment_pk)


def start_tailer(deployment, *, from_start: bool = True):
    """Begin tailing a deployment's log file (idempotent per process)."""
    pk = deployment.pk
    log_path = deployment.log_path or os.path.join(
        os.path.dirname(deployment.log_path or ""), f"deploy-{pk}.log"
    )
    with _LOCK:
        if pk in _TAILERS:
            return
        _TAILERS.add(pk)
    threading.Thread(
        target=_tail, args=(pk, log_path, from_start), daemon=True, name=f"tail-{pk}"
    ).start()


def ensure_tailers():
    """Adopt every currently-live deployment (called by the web server).

    Process deployments are tailed from their log *file*; compose deployments
    need a ``docker compose logs -f`` tee instead (their container output isn't
    written to that file by anyone else), so route by runtime."""
    from .models import Deployment, Environment

    live = Deployment.objects.filter(
        status=Deployment.Status.LIVE
    ).select_related("environment")
    for dep in live:
        runtime = getattr(dep.environment, "runtime", None)
        if runtime == Environment.Runtime.COMPOSE:
            try:
                from . import services

                services.ensure_compose_log_tail(dep)
            except Exception:  # noqa: BLE001
                pass
        elif dep.log_path:
            start_tailer(dep, from_start=False)
