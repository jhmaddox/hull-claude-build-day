"""Dependency-free Docker-Compose stack builder.

Emits a docker-compose spec + Dockerfile for a four-service stack:

    web      — the app (repo Dockerfile if present, else generated for the
               detected framework). Publishes ``<host_port>:<container_port>``
               so Hull's existing /d/<env_pk>/ proxy + health_check keep working.
    db       — postgres
    worker   — the web image running the project's worker/run command
    redis    — redis

DATABASE_URL (-> in-stack ``db``) and REDIS_URL (-> in-stack ``redis``) are
injected into both ``web`` and ``worker``.

Plain string templating only — NO PyYAML, no third-party deps. This module must
import on a Docker-absent box (the autonomous-loop / CI machine).
"""

from __future__ import annotations

# Container-internal port the app listens on inside the stack.
DEFAULT_CONTAINER_PORT = 8000

POSTGRES_IMAGE = "postgres:16-alpine"
REDIS_IMAGE = "redis:7-alpine"

# Credentials for the in-stack database. These never leave the compose network.
_DB_NAME = "app"
_DB_USER = "app"
_DB_PASSWORD = "app"


def _indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join((pad + line) if line else line for line in text.splitlines())


def database_url(host: str = "db", port: int = 5432) -> str:
    return f"postgres://{_DB_USER}:{_DB_PASSWORD}@{host}:{port}/{_DB_NAME}"


def redis_url(host: str = "redis", port: int = 6379) -> str:
    return f"redis://{host}:{port}/0"


def generate_dockerfile(framework: str = "generic", *, app_subdir: str = "",
                        install_command: str = "", container_port: int = DEFAULT_CONTAINER_PORT) -> str:
    """Return a generated Dockerfile string for the detected framework.

    Used only when the repo does not already ship its own Dockerfile.
    """
    framework = (framework or "generic").lower()
    workdir = "/app"
    install = (install_command or "").strip()

    if framework in ("django", "flask", "fastapi", "python", "generic"):
        if not install:
            install = "pip install --no-cache-dir -r requirements.txt"
        return (
            "FROM python:3.11-slim\n"
            f"WORKDIR {workdir}\n"
            "ENV PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1\n"
            "COPY . .\n"
            f"RUN {install} || true\n"
            f"EXPOSE {container_port}\n"
        )
    if framework in ("node", "next", "nextjs", "express"):
        return (
            "FROM node:20-slim\n"
            f"WORKDIR {workdir}\n"
            "COPY . .\n"
            "RUN npm install --no-audit --no-fund || true\n"
            f"EXPOSE {container_port}\n"
        )
    # Fallback generic image.
    return (
        "FROM python:3.11-slim\n"
        f"WORKDIR {workdir}\n"
        "COPY . .\n"
        f"EXPOSE {container_port}\n"
    )


def _run_command(framework: str, run_command: str, container_port: int) -> str:
    cmd = (run_command or "").strip()
    if cmd:
        return cmd.replace("$PORT", str(container_port)).replace(
            "${PORT}", str(container_port)
        )
    fw = (framework or "generic").lower()
    if fw == "django":
        return f"gunicorn --bind 0.0.0.0:{container_port} wsgi:application"
    if fw in ("flask", "fastapi"):
        return f"gunicorn --bind 0.0.0.0:{container_port} app:app"
    return f"python -m http.server {container_port}"


def _worker_command(worker_command: str, framework: str) -> str:
    cmd = (worker_command or "").strip()
    if cmd:
        return cmd
    fw = (framework or "generic").lower()
    if fw == "django":
        return "python manage.py rqworker || python -c \"import time; time.sleep(31536000)\""
    # Default: a no-op long sleep so the worker container stays up even if the
    # project has no dedicated worker command.
    return "python -c \"import time; time.sleep(31536000)\""


def _env_block(pairs: dict) -> str:
    """Render a compose ``environment:`` mapping (KEY: "value")."""
    lines = []
    for key, value in pairs.items():
        sval = str(value).replace('"', '\\"')
        lines.append(f'{key}: "{sval}"')
    return "\n".join(lines)


def build_compose(
    *,
    project_slug: str,
    env_name: str,
    host_port: int,
    container_port: int = DEFAULT_CONTAINER_PORT,
    framework: str = "generic",
    run_command: str = "",
    worker_command: str = "",
    extra_env: dict | None = None,
    has_dockerfile: bool = True,
    dockerfile: str = "Dockerfile",
) -> str:
    """Return a docker-compose spec string for the four-service stack.

    ``host_port`` comes from ``allocate_port()`` so the proxy + health_check
    keep working. ``extra_env`` (EnvVar rows) is merged into web + worker.
    """
    stack = f"{project_slug}-{env_name}".replace("/", "-")

    web_run = _run_command(framework, run_command, container_port)
    worker_run = _worker_command(worker_command, framework)

    base_env = {
        "DATABASE_URL": database_url(),
        "REDIS_URL": redis_url(),
        "PORT": str(container_port),
        # Environment identity, injected into every deployment so apps can show
        # which environment they're running in (staging vs prod, etc.).
        "HELM_ENV": env_name,
        "HELM_PROJECT": project_slug,
    }
    for k, v in (extra_env or {}).items():
        base_env[k] = v

    web_env = _indent(_env_block(base_env), 6)
    worker_env = _indent(_env_block(base_env), 6)

    build_block = (
        "    build:\n"
        "      context: .\n"
        f"      dockerfile: {dockerfile}\n"
    )

    spec = f"""# Generated by Hull for {stack}
name: {stack}
services:
  web:
{build_block}    image: {stack}-web
    command: {web_run}
    ports:
      - "{host_port}:{container_port}"
    environment:
{web_env}
    depends_on:
      - db
      - redis
    restart: unless-stopped

  worker:
    image: {stack}-web
    command: {worker_run}
    environment:
{worker_env}
    depends_on:
      - db
      - redis
    restart: unless-stopped

  db:
    image: {POSTGRES_IMAGE}
    environment:
      POSTGRES_DB: "{_DB_NAME}"
      POSTGRES_USER: "{_DB_USER}"
      POSTGRES_PASSWORD: "{_DB_PASSWORD}"
    volumes:
      - {stack}-db-data:/var/lib/postgresql/data
    restart: unless-stopped

  redis:
    image: {REDIS_IMAGE}
    restart: unless-stopped

volumes:
  {stack}-db-data:
"""
    return spec


# Backwards / convenience alias.
def build_compose_spec(*args, **kwargs) -> str:
    return build_compose(*args, **kwargs)
