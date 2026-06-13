"""Docker-Compose runtime helpers.

Detects Docker availability and runs a generated (or repo-provided) compose
stack. Everything here is best-effort: if Docker is missing the caller falls
back to the subprocess runtime, so the autonomous loop / CI box stays green.
"""

from __future__ import annotations

import os
import shutil
import subprocess


def docker_available() -> bool:
    """True only if a working ``docker`` CLI with compose support is reachable."""
    if shutil.which("docker") is None:
        return False
    try:
        proc = subprocess.run(
            ["docker", "compose", "version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        )
        return proc.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _detect_dockerfile(app_dir: str) -> str | None:
    cand = os.path.join(app_dir, "Dockerfile")
    return "Dockerfile" if os.path.isfile(cand) else None


def write_stack_files(app_dir: str, compose_spec: str, dockerfile: str | None) -> str:
    """Write the generated compose file (and Dockerfile if generated) into the
    app dir. Returns the path to the compose file."""
    compose_path = os.path.join(app_dir, "hull-compose.yml")
    with open(compose_path, "w", encoding="utf-8") as f:
        f.write(compose_spec)
    if dockerfile is not None and not os.path.isfile(os.path.join(app_dir, "Dockerfile")):
        with open(os.path.join(app_dir, "Dockerfile"), "w", encoding="utf-8") as f:
            f.write(dockerfile)
    return compose_path


def compose_up(app_dir: str, compose_path: str, project_name: str, log_append) -> bool:
    """Build + bring the stack up detached. Returns True on success.

    ``log_append`` is a callable used to stream build output into the build log.
    """
    cmd = [
        "docker", "compose", "-f", compose_path, "-p", project_name,
        "up", "-d", "--build",
    ]
    log_append(f"$ {' '.join(cmd)}")
    try:
        proc = subprocess.run(
            cmd,
            cwd=app_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=900,
        )
        log_append(proc.stdout)
        return proc.returncode == 0
    except Exception as exc:  # noqa: BLE001
        log_append(f"compose up error: {exc}")
        return False


def compose_down(compose_path: str, project_name: str) -> None:
    """Tear down a stack (best effort)."""
    try:
        subprocess.run(
            ["docker", "compose", "-f", compose_path, "-p", project_name, "down", "-v"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=300,
        )
    except Exception:  # noqa: BLE001
        pass


def compose_project_name(project_slug: str, env_name: str) -> str:
    return f"hull-{project_slug}-{env_name}".replace("/", "-").lower()
