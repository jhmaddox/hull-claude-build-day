"""Deployment lifecycle & process management.  [OWNER: Slice A agent]

Runs managed apps as local subprocesses on allocated ports, captures their
output via observability.services.ingest_line, and exposes them publicly via
the reverse-proxy view. Keep these signatures stable.
"""

from __future__ import annotations

import os
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time

from django.conf import settings
from django.utils import timezone

# Module-level registry of live Popen objects keyed by deployment pk. This is
# best-effort (does not survive a server reload), so stop/health rely on the
# stored pid instead.
_PROCS: dict[int, subprocess.Popen] = {}


# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------
def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def allocate_port() -> int:
    """Return a free port in [HELM_PORT_START, HELM_PORT_END] not in use by a
    LIVE deployment and not bound on the OS."""
    from .models import Deployment

    used = set(
        Deployment.objects.filter(status=Deployment.Status.LIVE)
        .exclude(port__isnull=True)
        .values_list("port", flat=True)
    )
    for port in range(settings.HELM_PORT_START, settings.HELM_PORT_END + 1):
        if port in used:
            continue
        if _port_is_free(port):
            return port
    raise RuntimeError("No free port available in the Hull port range.")


# ---------------------------------------------------------------------------
# Per-project venv
# ---------------------------------------------------------------------------
def _venv_dir(project) -> str:
    return os.path.join(str(settings.HELM_DATA_DIR), "venvs", project.slug)


def _venv_python(project) -> str:
    vdir = _venv_dir(project)
    if os.name == "nt":
        return os.path.join(vdir, "Scripts", "python.exe")
    return os.path.join(vdir, "bin", "python")


def _clean_env(extra: dict | None = None) -> dict:
    """A child-process environment with Hull's own Django context stripped, so a
    managed app uses its OWN settings module rather than inheriting helm.settings
    / PYTHONPATH from the control-plane process."""
    env = dict(os.environ)
    for key in ("DJANGO_SETTINGS_MODULE", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(key, None)
    if extra:
        env.update(extra)
    return env


def _env_vars_for(environment) -> dict:
    """Collect this environment's EnvVar rows (key -> raw value) for deploy-time
    injection into the running app. Raw secret values are used here only — never
    rendered in a read response."""
    out: dict[str, str] = {}
    try:
        for ev in environment.env_vars.all():
            if ev.key:
                out[ev.key] = ev.value or ""
    except Exception:  # noqa: BLE001 — never let config reads break a deploy
        pass
    return out


def _ensure_venv(project) -> str:
    """Create the per-project venv once; return path to its python."""
    py = _venv_python(project)
    if not os.path.isfile(py):
        os.makedirs(os.path.dirname(_venv_dir(project)), exist_ok=True)
        subprocess.run(
            [sys.executable, "-m", "venv", _venv_dir(project)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    return py


# ---------------------------------------------------------------------------
# Source materialization
# ---------------------------------------------------------------------------
def _materialize_source(deployment, commit_sha, source_path):
    """Return the absolute path to the checked-out source for this deployment."""
    if source_path:
        return source_path

    project = deployment.project
    repo = project.local_path
    dest = os.path.join(str(settings.HELM_DATA_DIR), "deploys", str(deployment.pk))
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    ref = commit_sha or deployment.environment.branch
    # Remove a stale worktree at this path first (idempotent re-deploy).
    if os.path.exists(dest):
        subprocess.run(
            ["git", "worktree", "remove", "--force", dest],
            cwd=repo,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if os.path.exists(dest):
            import shutil

            shutil.rmtree(dest, ignore_errors=True)

    proc = subprocess.run(
        ["git", "worktree", "add", "--force", dest, ref],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git worktree add failed: {proc.stdout}")
    return dest


def _resolve_head(project, ref) -> str:
    if not getattr(project, "local_path", ""):
        return ""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", ref],
            cwd=project.local_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except Exception:  # noqa: BLE001 — never raise before the Deployment exists
        return ""
    if proc.returncode == 0:
        return proc.stdout.strip()
    return ""


def _commit_message(project, sha) -> str:
    if not sha or not getattr(project, "local_path", ""):
        return ""
    try:
        proc = subprocess.run(
            ["git", "log", "-1", "--pretty=%s", sha],
            cwd=project.local_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except Exception:  # noqa: BLE001
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


# ---------------------------------------------------------------------------
# Process control
# ---------------------------------------------------------------------------
def _kill_pid(pid: int):
    """Kill a process group by pid, gracefully then forcefully."""
    if not pid:
        return
    try:
        import psutil

        if not psutil.pid_exists(pid):
            return
    except Exception:  # noqa: BLE001
        pass

    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(pid), sig)
        except ProcessLookupError:
            return
        except Exception:  # noqa: BLE001
            # Fall back to killing the single process.
            try:
                os.kill(pid, sig)
            except Exception:  # noqa: BLE001
                return
        if sig == signal.SIGTERM:
            # Give it a moment to exit cleanly.
            for _ in range(20):
                try:
                    os.killpg(os.getpgid(pid), 0)
                except (ProcessLookupError, Exception):  # noqa: BLE001
                    return
                time.sleep(0.1)


def _tee_output(deployment, popen, log_path):
    """Daemon-thread target: read process output line by line, write to the log
    file, and stream each line to observability.services.ingest_line."""
    from observability import services as obs

    try:
        with open(log_path, "a", encoding="utf-8", errors="replace") as logf:
            for raw in iter(popen.stdout.readline, ""):
                if raw == "":
                    break
                logf.write(raw)
                logf.flush()
                line = raw.rstrip("\n")
                try:
                    obs.ingest_line(deployment, line)
                except Exception:  # noqa: BLE001 — ingest must never kill deploy
                    pass
    except Exception:  # noqa: BLE001
        pass


def _health_poll(port: int, timeout: float = 40.0, popen=None) -> bool:
    """Poll the deployment for health.

    If ``popen`` is given and the process exits before becoming healthy, fail
    immediately — this catches a failed port bind (e.g. an orphan squatting on
    the port), so we don't falsely report LIVE against someone else's process.
    """
    import requests

    deadline = time.time() + timeout
    url = f"http://127.0.0.1:{port}/"
    while time.time() < deadline:
        if popen is not None and popen.poll() is not None:
            # Process died (commonly: couldn't bind the port). Not healthy.
            return False
        try:
            resp = requests.get(url, timeout=3, allow_redirects=False)
            if resp.status_code < 500:
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def deploy(environment, *, commit_sha: str | None = None, source_path: str | None = None):
    """Build & start a Deployment for ``environment``. See stub docstring."""
    from core.models import Event
    from .models import Deployment, Environment

    project = environment.project

    if not commit_sha:
        commit_sha = _resolve_head(project, environment.branch)

    deployment = Deployment.objects.create(
        environment=environment,
        # Denormalize org from the environment (may be None for the loop).
        org=getattr(environment, "org", None),
        commit_sha=commit_sha or "",
        commit_message=_commit_message(project, commit_sha),
        status=Deployment.Status.BUILDING,
    )

    log_path = os.path.join(str(settings.HELM_LOGS_DIR), f"deploy-{deployment.pk}.log")
    deployment.log_path = log_path
    deployment.save(update_fields=["log_path"])

    Event.log(
        f"deploy started for {environment.name}",
        project=project,
        icon="deploy",
        level="info",
    )

    build_log = []

    def _append_build(text):
        build_log.append(text)
        Deployment.objects.filter(pk=deployment.pk).update(build_log="\n".join(build_log))

    try:
        # Stop the previous LIVE deployment for this environment first.
        prev = (
            environment.deployments.filter(status=Deployment.Status.LIVE)
            .exclude(pk=deployment.pk)
            .first()
        )
        if prev:
            _append_build(f"stopping previous deployment #{prev.pk}")
            stop(prev)

        # --- Compose runtime branch (additive; falls back to process) -------
        if (
            getattr(environment, "runtime", Environment.Runtime.PROCESS)
            == Environment.Runtime.COMPOSE
        ):
            from .compose import runtime as compose_rt

            if compose_rt.docker_available():
                _append_build("runtime=compose; Docker detected")
                return _deploy_compose(
                    deployment, environment, commit_sha, source_path,
                    _append_build, log_path,
                )
            _append_build(
                "runtime=compose requested but Docker unavailable — "
                "falling back to process runtime"
            )

        # Materialize source.
        source = _materialize_source(deployment, commit_sha, source_path)
        deployment.source_path = source
        deployment.save(update_fields=["source_path"])
        app_dir = os.path.join(source, project.app_subdir) if project.app_subdir else source
        _append_build(f"source: {source}\napp dir: {app_dir}")

        # Per-project venv + install.
        venv_py = _ensure_venv(project)
        _append_build(f"venv python: {venv_py}")

        install_cmd = (project.install_command or "").strip()
        if install_cmd:
            # Replace a leading "pip" with the venv pip invocation.
            parts = shlex.split(install_cmd)
            if parts and parts[0] == "pip":
                parts = [venv_py, "-m", "pip"] + parts[1:]
            # Install from whichever dir holds requirements.txt (app dir or the
            # source root), since requirements.txt may live at the repo root.
            install_cwd = app_dir
            if "-r" in parts:
                req = parts[parts.index("-r") + 1] if parts.index("-r") + 1 < len(parts) else ""
                if req and not os.path.isfile(os.path.join(app_dir, req)) and os.path.isfile(
                    os.path.join(source, req)
                ):
                    install_cwd = source
            _append_build(f"$ {' '.join(parts)}  (cwd={install_cwd})")
            proc = subprocess.run(
                parts,
                cwd=install_cwd,
                env=_clean_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            _append_build(proc.stdout)
            if proc.returncode != 0:
                raise RuntimeError(f"install failed (exit {proc.returncode})")

        # Django migrations.
        if project.framework == "django":
            _append_build("$ python manage.py migrate --noinput")
            proc = subprocess.run(
                [venv_py, "manage.py", "migrate", "--noinput"],
                cwd=app_dir,
                env=_clean_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            _append_build(proc.stdout)
            if proc.returncode != 0:
                raise RuntimeError(f"migrate failed (exit {proc.returncode})")

        # Allocate port and build the run command.
        port = allocate_port()
        _append_build(f"allocated port {port}")

        run_cmd = (project.run_command or "python -m http.server $PORT").strip()
        # Substitute $PORT textually; the env also carries PORT for apps that
        # read it from the environment.
        run_cmd_sub = run_cmd.replace("$PORT", str(port)).replace("${PORT}", str(port))
        run_parts = shlex.split(run_cmd_sub)
        if run_parts and run_parts[0] == "python":
            run_parts[0] = venv_py

        child_env = _clean_env(
            {
                "PORT": str(port),
                "HELM_SCRIPT_NAME": f"/d/{environment.pk}",
                "HELM_BASE_URL": settings.HELM_BASE_URL,
                "DJANGO_ALLOWED_HOSTS": "*",
            }
        )
        # Inject this environment's configured env-vars / secrets (process
        # runtime). These override Hull's defaults intentionally.
        child_env.update(_env_vars_for(environment))

        _append_build(f"$ {' '.join(run_parts)}  (PORT={port})")

        # Write app output straight to a log FILE (not a pipe) so the app
        # survives whatever process started it. A tailer follows the file and
        # streams lines into observability ingestion; the long-lived server can
        # adopt this deployment later via tailer.ensure_tailers().
        logf = open(log_path, "a", encoding="utf-8", errors="replace")
        popen = subprocess.Popen(
            run_parts,
            cwd=app_dir,
            env=child_env,
            stdout=logf,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        logf.close()  # child keeps its own dup of the fd
        _PROCS[deployment.pk] = popen

        from . import tailer

        tailer.start_tailer(deployment, from_start=True)

        # Health-poll (process-aware: fails fast if the process dies, e.g. a
        # failed port bind, instead of passing against an orphan squatter).
        healthy = _health_poll(port, timeout=40.0, popen=popen)
        if not healthy:
            # Process may have died; capture exit if so.
            rc = popen.poll()
            raise RuntimeError(
                f"health check failed on port {port}"
                + (f" (process exited {rc})" if rc is not None else "")
            )

        deployment.status = Deployment.Status.LIVE
        deployment.health = Deployment.Health.HEALTHY
        deployment.live_at = timezone.now()
        deployment.pid = popen.pid
        deployment.port = port
        deployment.save(
            update_fields=["status", "health", "live_at", "pid", "port"]
        )

        environment.port = port
        environment.save(update_fields=["port"])

        Event.log(
            f"deployed {environment.name} live",
            project=project,
            icon="deploy",
            level="success",
            url=deployment.public_url,
        )
        return deployment

    except Exception as exc:  # noqa: BLE001
        _append_build(f"ERROR: {exc}")
        # Tear down a half-started process if any.
        proc = _PROCS.pop(deployment.pk, None)
        if proc and proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:  # noqa: BLE001
                pass
        deployment.status = Deployment.Status.FAILED
        deployment.error = str(exc)
        deployment.save(update_fields=["status", "error"])
        Event.log(
            f"deploy failed for {environment.name}: {exc}",
            project=project,
            icon="x",
            level="error",
        )
        return deployment


def stop(deployment) -> None:
    """Terminate the deployment's process group; set status=STOPPED, stopped_at."""
    from .models import Deployment

    proc = _PROCS.pop(deployment.pk, None)
    if proc and proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:  # noqa: BLE001
            pass

    if deployment.pid:
        _kill_pid(deployment.pid)

    deployment.status = Deployment.Status.STOPPED
    deployment.stopped_at = timezone.now()
    deployment.save(update_fields=["status", "stopped_at"])


def restart(deployment):
    """Stop and re-deploy the same commit. Returns the new Deployment."""
    stop(deployment)
    return deploy(
        deployment.environment,
        commit_sha=deployment.commit_sha or None,
    )


def _deploy_compose(deployment, environment, commit_sha, source_path,
                    append_build, log_path):
    """Bring up a web+db+worker+redis Docker-Compose stack for ``environment``.

    Sets the same Deployment fields the process path does
    (status/health/port/live_at/log_path/build_log). Any failure is recorded and
    the Deployment is returned (callers never see an exception escape deploy()).
    """
    from core.models import Event
    from .models import Deployment
    from .compose import builder, runtime as compose_rt

    project = environment.project
    try:
        source = _materialize_source(deployment, commit_sha, source_path)
        deployment.source_path = source
        deployment.save(update_fields=["source_path"])
        app_dir = (
            os.path.join(source, project.app_subdir) if project.app_subdir else source
        )
        append_build(f"source: {source}\napp dir: {app_dir}")

        port = allocate_port()
        append_build(f"allocated host port {port}")

        has_dockerfile = os.path.isfile(os.path.join(app_dir, "Dockerfile"))
        container_port = builder.DEFAULT_CONTAINER_PORT
        extra_env = _env_vars_for(environment)

        compose_spec = builder.build_compose(
            project_slug=project.slug,
            env_name=environment.name,
            host_port=port,
            container_port=container_port,
            framework=getattr(project, "framework", "generic"),
            run_command=getattr(project, "run_command", ""),
            extra_env=extra_env,
            has_dockerfile=has_dockerfile,
        )
        dockerfile = None
        if not has_dockerfile:
            dockerfile = builder.generate_dockerfile(
                getattr(project, "framework", "generic"),
                app_subdir=project.app_subdir,
                install_command=getattr(project, "install_command", ""),
                container_port=container_port,
            )
            append_build("no repo Dockerfile — generated one")

        compose_path = compose_rt.write_stack_files(app_dir, compose_spec, dockerfile)
        append_build(f"wrote compose spec: {compose_path}")

        pname = compose_rt.compose_project_name(project.slug, environment.name)
        ok = compose_rt.compose_up(app_dir, compose_path, pname, append_build)
        if not ok:
            raise RuntimeError("docker compose up failed")

        healthy = _health_poll(port, timeout=60.0)
        deployment.status = Deployment.Status.LIVE
        deployment.health = (
            Deployment.Health.HEALTHY if healthy else Deployment.Health.UNKNOWN
        )
        deployment.live_at = timezone.now()
        deployment.port = port
        deployment.save(
            update_fields=["status", "health", "live_at", "port"]
        )
        environment.port = port
        environment.save(update_fields=["port"])

        Event.log(
            f"deployed {environment.name} live (compose)",
            project=project,
            icon="deploy",
            level="success",
            url=deployment.public_url,
        )
        return deployment
    except Exception as exc:  # noqa: BLE001 — never raise out of deploy()
        append_build(f"ERROR (compose): {exc}")
        deployment.status = Deployment.Status.FAILED
        deployment.error = str(exc)
        deployment.save(update_fields=["status", "error"])
        Event.log(
            f"compose deploy failed for {environment.name}: {exc}",
            project=project,
            icon="x",
            level="error",
        )
        return deployment


def rollback(environment, to_deployment):
    """Append-only rollback: deploy a prior SUCCESSFUL deployment's
    commit/source as a NEW Deployment. The old row's pk/status is never mutated.

    Returns the new Deployment. Emits a core.models.Event.log(icon='deploy').
    """
    from core.models import Event

    Event.log(
        f"rolling back {environment.name} to deployment #{to_deployment.pk} "
        f"({(to_deployment.commit_sha or '')[:8]})",
        project=environment.project,
        icon="deploy",
        level="info",
    )
    new_dep = deploy(
        environment,
        commit_sha=to_deployment.commit_sha or None,
        source_path=to_deployment.source_path or None,
    )
    return new_dep


def health_check(deployment) -> bool:
    """HTTP GET the deployment root; update health; return True if 2xx/3xx."""
    import requests

    from .models import Deployment

    if not deployment.port:
        return False
    try:
        resp = requests.get(
            f"http://127.0.0.1:{deployment.port}/",
            timeout=4,
            allow_redirects=False,
        )
        ok = resp.status_code < 500
    except Exception:  # noqa: BLE001
        ok = False

    deployment.health = (
        Deployment.Health.HEALTHY if ok else Deployment.Health.UNHEALTHY
    )
    deployment.save(update_fields=["health"])
    return ok
