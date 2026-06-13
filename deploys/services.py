"""Deployment lifecycle & process management.  [OWNER: Slice A agent]

Runs managed apps as local subprocesses on allocated ports, captures their
output via observability.services.ingest_line, and exposes them publicly via
the reverse-proxy view. Keep these signatures stable.
"""

from __future__ import annotations


def allocate_port() -> int:
    """Return a free port in [HELM_PORT_START, HELM_PORT_END] not in use by a
    LIVE deployment and not bound on the OS."""
    raise NotImplementedError


def deploy(environment, *, commit_sha: str | None = None, source_path: str | None = None):
    """Build & start a Deployment for ``environment``.

    Steps: create Deployment(status=BUILDING); materialize source (git worktree
    or checkout of commit_sha into a per-deployment dir, OR use source_path for
    a preview env backed by an existing worktree); run project.install_command;
    run migrations if Django; allocate a port; spawn the run_command subprocess
    with PORT set, redirecting stdout/stderr to a log file AND streaming each
    line to observability.services.ingest_line(deployment, line) on a thread;
    poll http://127.0.0.1:<port>/ until healthy (or timeout); set status=LIVE,
    health=HEALTHY, live_at, pid, port. On failure set status=FAILED + error.
    Stops any previous LIVE deployment for the same environment first.
    Logs core.Event. Returns the Deployment.
    """
    raise NotImplementedError


def stop(deployment) -> None:
    """Terminate the deployment's process group; set status=STOPPED, stopped_at."""
    raise NotImplementedError


def restart(deployment):
    """Stop and re-deploy the same commit. Returns the new Deployment."""
    raise NotImplementedError


def health_check(deployment) -> bool:
    """HTTP GET the deployment root; update health; return True if 2xx/3xx."""
    raise NotImplementedError
