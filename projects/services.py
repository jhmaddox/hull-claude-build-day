"""Project import & runtime detection.  [OWNER: Slice A agent]

Contract used by orchestration + UI. Keep these signatures stable.
"""

from __future__ import annotations

import os
import subprocess

from django.conf import settings
from django.utils.text import slugify


def _run(args, cwd=None):
    """Run a command, returning (returncode, combined_output)."""
    proc = subprocess.run(
        args,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc.returncode, proc.stdout


# --- Live import-progress stepper (PROJECTS-2) -----------------------------
# A thin, best-effort layer over the ImportStep model. Every helper swallows
# its own errors so step bookkeeping can NEVER break the import itself or the
# autonomous loop (steps are pure UI narration).


def _seed_import_steps(project):
    """Create the canonical ordered ImportStep rows for ``project`` (all
    pending). Idempotent: re-importing clears stale steps first."""
    try:
        from .models import IMPORT_STEPS, ImportStep

        project.import_steps.all().delete()
        ImportStep.objects.bulk_create(
            [
                ImportStep(
                    project=project,
                    key=key,
                    label=label,
                    order=i,
                    state=ImportStep.State.PENDING,
                )
                for i, (key, label) in enumerate(IMPORT_STEPS)
            ]
        )
    except Exception:  # noqa: BLE001 — narration must never break the import
        pass


def _set_step(project, key, state, detail=""):
    """Update one import step's state + detail line, stamping timing."""
    try:
        from django.utils import timezone

        from .models import ImportStep

        step = project.import_steps.filter(key=key).first()
        if step is None:
            return
        step.state = state
        if detail:
            step.detail = detail[:500]
        if state == ImportStep.State.RUNNING and step.started_at is None:
            step.started_at = timezone.now()
        if state in (ImportStep.State.DONE, ImportStep.State.FAILED):
            step.ended_at = timezone.now()
        step.save()
    except Exception:  # noqa: BLE001
        pass


def _fail_pending_steps(project, detail=""):
    """Mark any still-pending/running steps failed (used when import aborts)."""
    try:
        from .models import ImportStep

        for step in project.import_steps.exclude(
            state__in=[ImportStep.State.DONE, ImportStep.State.FAILED]
        ):
            _set_step(project, step.key, ImportStep.State.FAILED, detail)
    except Exception:  # noqa: BLE001
        pass


# Message shown when a repo declares no supported runtime. Kept as a module
# constant so the import gate + tests reference the exact same string.
UNSUPPORTED_RUNTIME_MESSAGE = (
    "Hull needs a docker-compose.yml, a Procfile, or a Django manage.py to "
    "deploy this repo."
)


def _find_compose_file(root: str):
    """Return the absolute path to a docker-compose file at the repo root, or
    None. Checks the canonical names in priority order."""
    for name in (
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
    ):
        candidate = os.path.join(root, name)
        if os.path.isfile(candidate):
            return candidate
    return None


def _host_port_from_mapping(value) -> "int | None":
    """Extract the published host port from one compose ``ports:`` entry.

    Handles strings ("8080:3000", "3000", "127.0.0.1:80:80", "53:53/udp") and
    dict form ({published: 8080, target: 3000}). Returns the host side, or None.
    """
    if isinstance(value, dict):
        pub = value.get("published", value.get("target"))
        try:
            return int(pub)
        except (TypeError, ValueError):
            return None
    text = str(value).strip().strip('"').strip("'")
    if not text:
        return None
    parts = text.split(":")
    # "host:container" / "ip:host:container" -> host is second-from-last;
    # bare "container" -> that single value.
    host = parts[-2] if len(parts) >= 2 else parts[0]
    host = host.split("/")[0]  # strip /tcp, /udp on bare ports
    try:
        return int(host)
    except ValueError:
        return None


def _parse_compose_web(compose_path: str) -> dict:
    """Parse a docker-compose file and extract the web service name + the host
    port it publishes.

    Returns ``{"web_service": <name>, "web_port": <int|None>}``. The web service
    is the one literally named ``web`` if present, else the first service that
    publishes a port, else the first service. ``web_port`` is the host side of
    the first ``ports:`` mapping (``"8080:3000"`` -> 8080, ``"3000"`` -> 3000),
    or None when nothing is published. Best-effort and never raises: a malformed
    or unreadable file yields ``{"web_service": None, "web_port": None}``.

    Uses PyYAML when importable; otherwise falls back to a small indentation
    parser so detection works without adding a dependency.
    """
    result = {"web_service": None, "web_port": None}
    try:
        with open(compose_path, "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return result

    services = _compose_services(text)
    if not services:
        return result

    def _host_port(svc) -> "int | None":
        ports = svc.get("ports") if isinstance(svc, dict) else None
        if not isinstance(ports, list):
            return None
        for entry in ports:
            p = _host_port_from_mapping(entry)
            if p is not None:
                return p
        return None

    if "web" in services:
        return {"web_service": "web", "web_port": _host_port(services["web"])}
    for name, svc in services.items():
        p = _host_port(svc)
        if p is not None:
            return {"web_service": name, "web_port": p}
    first = next(iter(services))
    return {"web_service": first, "web_port": None}


def _compose_services(text: str) -> dict:
    """Return ``{service_name: {"ports": [<entry>, ...]}}`` from a compose file.

    Prefers PyYAML; falls back to a minimal, order-preserving indentation parser
    that recognizes the ``services:`` block, two-space-indented service names,
    and a nested ``ports:`` list (``- "host:container"``). Returns ``{}`` on any
    failure. Only the bits ``detect_runtime`` needs (service order + ports) are
    extracted — this is detection, not a full YAML implementation.
    """
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text) or {}
        svcs = data.get("services") if isinstance(data, dict) else None
        if isinstance(svcs, dict):
            out = {}
            for name, body in svcs.items():
                ports = body.get("ports") if isinstance(body, dict) else None
                out[name] = {"ports": ports if isinstance(ports, list) else []}
            return out
    except ImportError:
        pass
    except Exception:  # noqa: BLE001 — malformed YAML -> try the fallback
        pass

    # --- dependency-free fallback ---
    services: "dict[str, dict]" = {}
    lines = text.splitlines()
    in_services = False
    services_indent = None
    current = None
    in_ports = False
    ports_indent = None

    def _indent(s: str) -> int:
        return len(s) - len(s.lstrip(" "))

    for raw in lines:
        # Strip trailing comments (not inside quotes — compose values are simple).
        line = raw.rstrip("\n")
        if not line.strip() or line.strip().startswith("#"):
            continue
        ind = _indent(line)
        stripped = line.strip()

        if not in_services:
            if stripped.rstrip() == "services:" or stripped.startswith("services:"):
                in_services = True
                services_indent = ind
            continue

        # Left the services block.
        if ind <= services_indent and stripped != "services:":
            break

        # A service name line is indented exactly one level under services and
        # ends with ":" (e.g. "  web:").
        if (
            services_indent is not None
            and ind == services_indent + 2
            and stripped.endswith(":")
        ):
            current = stripped[:-1].strip()
            services[current] = {"ports": []}
            in_ports = False
            ports_indent = None
            continue

        if current is None:
            continue

        # Enter a ports: list under the current service.
        if stripped == "ports:" or stripped.startswith("ports:"):
            in_ports = True
            ports_indent = ind
            # inline "ports: [..]" form
            rest = stripped[len("ports:"):].strip()
            if rest.startswith("["):
                items = rest.strip("[]").split(",")
                for it in items:
                    it = it.strip().strip('"').strip("'")
                    if it:
                        services[current]["ports"].append(it)
                in_ports = False
            continue

        if in_ports:
            if ind <= ports_indent:
                in_ports = False
            elif stripped.startswith("-"):
                val = stripped[1:].strip().strip('"').strip("'")
                if val:
                    services[current]["ports"].append(val)
                continue

    return services


def _procfile_web_command(root: str):
    """Return the ``web:`` command from a root Procfile, or None."""
    procfile = os.path.join(root, "Procfile")
    if not os.path.isfile(procfile):
        return None
    try:
        with open(procfile, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                stripped = line.strip()
                if stripped.lower().startswith("web:"):
                    cmd = stripped.split(":", 1)[1].strip()
                    if cmd:
                        return cmd
    except OSError:
        pass
    return None


def detect_runtime(path: str) -> dict:
    """Inspect a checked-out repo and return how to install & run it.

    Returns a dict with keys: framework, install_command, run_command,
    app_subdir. ``run_command`` MUST accept a ``$PORT`` env var / placeholder
    so deploys can bind it to an allocated port. For Django, prefer
    ``python manage.py runserver 0.0.0.0:$PORT`` (or gunicorn).

    Supported runtimes (priority order): ``compose`` (a docker-compose file is
    present — the stack declares how to run, so ``deploys`` builds/ups it),
    ``django`` (a ``manage.py``), or ``procfile`` (a ``Procfile`` with a
    ``web:`` line). A repo declaring NONE of these returns framework ``none``;
    ``import_project`` gates that to FAILED with ``UNSUPPORTED_RUNTIME_MESSAGE``.
    NO AI generation.

    For ``compose`` the returned dict additionally carries ``web_service`` and
    ``web_port`` (parsed from the compose file) so callers can surface/verify
    the published web endpoint.
    """
    root = path

    # --- Docker Compose: the repo already declares its full stack ---
    compose_path = _find_compose_file(root)
    if compose_path is not None:
        web = _parse_compose_web(compose_path)
        # Process-path fallback if Docker is absent: prefer the repo's own
        # Procfile ``web:`` command (so e.g. a Node app still runs ``node
        # server.js`` reading $PORT from the env), then a Django manage.py, then
        # a best-effort static serve. The compose runtime itself ignores
        # run_command and uses the compose spec.
        web_cmd = _procfile_web_command(root)
        if not web_cmd:
            if os.path.isfile(os.path.join(root, "manage.py")):
                web_cmd = "python manage.py runserver 0.0.0.0:$PORT"
            else:
                web_cmd = "python -m http.server $PORT"
        return {
            "framework": "compose",
            # Compose builds via its own Dockerfile(s); no Hull install step.
            "install_command": "",
            "run_command": web_cmd,
            "app_subdir": "",
            "web_service": web["web_service"],
            "web_port": web["web_port"],
        }

    # --- Django detection: manage.py at root or exactly one level down ---
    manage_dir = None  # absolute dir holding manage.py
    if os.path.isfile(os.path.join(root, "manage.py")):
        manage_dir = root
    else:
        try:
            for entry in sorted(os.listdir(root)):
                sub = os.path.join(root, entry)
                if os.path.isdir(sub) and os.path.isfile(os.path.join(sub, "manage.py")):
                    manage_dir = sub
                    break
        except OSError:
            pass

    if manage_dir is not None:
        app_subdir = os.path.relpath(manage_dir, root)
        if app_subdir == ".":
            app_subdir = ""
        # requirements.txt "near" manage.py: in the manage dir or repo root.
        if os.path.isfile(os.path.join(manage_dir, "requirements.txt")) or os.path.isfile(
            os.path.join(root, "requirements.txt")
        ):
            install_command = "pip install -r requirements.txt"
        else:
            install_command = "pip install django"
        return {
            "framework": "django",
            "install_command": install_command,
            "run_command": "python manage.py runserver 0.0.0.0:$PORT",
            "app_subdir": app_subdir,
        }

    # --- Procfile web: line ---
    procfile = os.path.join(root, "Procfile")
    if os.path.isfile(procfile):
        try:
            with open(procfile, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    stripped = line.strip()
                    if stripped.lower().startswith("web:"):
                        cmd = stripped.split(":", 1)[1].strip()
                        if cmd:
                            install_command = (
                                "pip install -r requirements.txt"
                                if os.path.isfile(os.path.join(root, "requirements.txt"))
                                else ""
                            )
                            return {
                                "framework": "procfile",
                                "install_command": install_command,
                                "run_command": cmd,
                                "app_subdir": "",
                            }
        except OSError:
            pass

    # --- No supported runtime declared: signal the gate (NO AI generation) ---
    return {
        "framework": "none",
        "install_command": "",
        "run_command": "",
        "app_subdir": "",
    }


def _unique_slug(name: str, org=None) -> str:
    """Return a slug unique within ``org`` (slugs are unique per-org, not global).

    ``org=None`` preserves the original behavior of uniqueness among org-less
    projects (the autonomous-loop path).
    """
    from .models import Project

    base = slugify(name) or "project"
    slug = base
    n = 1
    while Project.objects.filter(org=org, slug=slug).exists():
        n += 1
        slug = f"{base}-{n}"
    return slug


def _clone_args(repo_url: str, dest: str):
    """Build the git clone argument list, supporting https, file://, and bare
    local paths."""
    return ["git", "clone", repo_url, dest]


def _ensure_local_git_repo(repo_url: str) -> None:
    """If ``repo_url`` is a local directory that isn't yet a git repo,
    initialize one and commit its contents so Hull can clone it.

    This lets a plain source tree (e.g. the bundled sample app, tracked as
    normal files in Hull's own repo) be imported without shipping a nested
    .git. Idempotent and a no-op for URLs / existing repos.
    """
    if "://" in repo_url and not repo_url.startswith("file://"):
        return
    path = repo_url[len("file://"):] if repo_url.startswith("file://") else repo_url
    if not os.path.isdir(path) or os.path.isdir(os.path.join(path, ".git")):
        return
    env = {**os.environ, "GIT_AUTHOR_NAME": "Hull", "GIT_AUTHOR_EMAIL": "helm@helm.dev",
           "GIT_COMMITTER_NAME": "Hull", "GIT_COMMITTER_EMAIL": "helm@helm.dev"}
    subprocess.run(["git", "init", "-b", "main"], cwd=path, env=env,
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    subprocess.run(["git", "add", "-A"], cwd=path, env=env,
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    subprocess.run(["git", "commit", "-m", "Import baseline"], cwd=path, env=env,
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def import_project(name: str, repo_url: str, *, description: str = "", org=None):
    """Clone ``repo_url`` into settings.HELM_REPOS_DIR/<slug>, detect runtime,
    create ``staging`` (branch=default) and ``prod`` (branch=default)
    Environments, mark the Project READY, and log core.Event entries.

    May be called for a local path repo_url too (use ``file://`` or a path).
    Returns the Project. Sets Project.status=FAILED + import_log on error.

    ``org`` is keyword-only and defaults to ``None`` so the autonomous loop and
    any existing callers keep working unchanged; UI imports pass ``request.org``
    so the created Project is tagged with the acting user's active org.
    """
    from core.models import Event
    from deploys.models import Environment
    from .models import Project

    slug = _unique_slug(name, org=org)
    dest = os.path.join(str(settings.HELM_REPOS_DIR), slug)

    project = Project.objects.create(
        name=name,
        slug=slug,
        repo_url=repo_url,
        description=description,
        status=Project.Status.IMPORTING,
        local_path=dest,
        org=org,
    )

    Event.log(
        f"is importing project {name}",
        project=project,
        icon="rocket",
        level="info",
    )

    from .models import ImportStep

    _seed_import_steps(project)

    log_parts = []
    try:
        # --- Clone ---
        _set_step(project, "clone", ImportStep.State.RUNNING, f"cloning {repo_url}")
        # A plain local source tree (no .git) is initialized so it can be cloned.
        _ensure_local_git_repo(repo_url)

        # Clean any stale destination so clone is idempotent.
        if os.path.exists(dest):
            import shutil

            shutil.rmtree(dest, ignore_errors=True)

        rc, out = _run(_clone_args(repo_url, dest))
        log_parts.append(f"$ git clone {repo_url} {dest}\n{out}")
        if rc != 0:
            _set_step(
                project, "clone", ImportStep.State.FAILED, f"git clone failed (exit {rc})"
            )
            raise RuntimeError(f"git clone failed (exit {rc})")
        _set_step(project, "clone", ImportStep.State.DONE, "repository cloned")

        # Determine default branch.
        default_branch = "main"
        rc, out = _run(["git", "symbolic-ref", "--short", "HEAD"], cwd=dest)
        if rc == 0 and out.strip():
            default_branch = out.strip()
        else:
            rc2, out2 = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=dest)
            if rc2 == 0 and out2.strip() and out2.strip() != "HEAD":
                default_branch = out2.strip()

        # --- Detect runtime ---
        _set_step(project, "detect", ImportStep.State.RUNNING, "inspecting repo")
        runtime = detect_runtime(dest)
        log_parts.append(f"detected runtime: {runtime}")

        # Supported-runtime gate (PROJECTS-1): a repo declaring no
        # docker-compose.yml / Procfile / manage.py cannot be deployed. Mark
        # FAILED with a friendly message instead of guessing. NO AI generation.
        if runtime["framework"] == "none":
            project.default_branch = default_branch
            project.framework = "none"
            project.status = Project.Status.FAILED
            log_parts.append(UNSUPPORTED_RUNTIME_MESSAGE)
            project.import_log = "\n\n".join(log_parts)
            project.save()
            _set_step(
                project, "detect", ImportStep.State.FAILED, UNSUPPORTED_RUNTIME_MESSAGE
            )
            _fail_pending_steps(project, "import aborted")
            Event.log(
                f"cannot import {name}: {UNSUPPORTED_RUNTIME_MESSAGE}",
                project=project,
                icon="x",
                level="error",
            )
            return project

        _detail = runtime["framework"]
        if runtime["framework"] == "compose" and runtime.get("web_port"):
            _detail = f"compose · web on :{runtime['web_port']}"
        _set_step(project, "detect", ImportStep.State.DONE, _detail)

        # --- Verify environment (deps / build readiness) ---
        # No package install here (compose builds its own image; process runs
        # install at deploy time) — this step confirms the runtime is resolvable
        # and records what the deploy will do.
        _set_step(project, "verify", ImportStep.State.RUNNING, "checking runtime")
        _verify_detail = runtime["install_command"] or "no install step required"
        _set_step(project, "verify", ImportStep.State.DONE, _verify_detail)

        project.default_branch = default_branch
        project.framework = runtime["framework"]
        project.install_command = runtime["install_command"]
        project.run_command = runtime["run_command"]
        project.app_subdir = runtime["app_subdir"]
        project.status = Project.Status.READY
        project.import_log = "\n\n".join(log_parts)
        project.save()

        # PROJECTS-3: stamp the Environment runtime so deploys.services.deploy
        # takes the compose branch for compose repos (web+db+worker+redis as the
        # compose declares). Non-compose repos stay on the PROCESS fallback.
        env_runtime = (
            Environment.Runtime.COMPOSE
            if runtime["framework"] == "compose"
            else Environment.Runtime.PROCESS
        )

        # Create staging + prod environments.
        Environment.objects.get_or_create(
            project=project,
            name="staging",
            defaults={
                "kind": Environment.Kind.STAGING,
                "branch": default_branch,
                "runtime": env_runtime,
            },
        )
        Environment.objects.get_or_create(
            project=project,
            name="prod",
            defaults={
                "kind": Environment.Kind.PROD,
                "branch": default_branch,
                "runtime": env_runtime,
            },
        )

        # --- Provision domain ---
        # Each environment gets a stable public URL (``Environment.public_url``,
        # served by the reverse proxy at ``/d/<env_pk>/``); on the Caddy box
        # this maps to ``<slug>.apps...``. No external call here — provisioning
        # is satisfied by env creation.
        _set_step(
            project,
            "provision",
            ImportStep.State.DONE,
            "staging + prod endpoints provisioned",
        )

        # Deploy steps are advanced by the deploy phase (see
        # ``deploy_environment``), which the import flow / orchestration runs
        # after import. They stay pending until then.

        Event.log(
            f"imported project {name} ({runtime['framework']})",
            project=project,
            icon="check",
            level="success",
            url=project.get_absolute_url(),
        )
        return project

    except Exception as exc:  # noqa: BLE001 — record any failure on the project
        log_parts.append(f"ERROR: {exc}")
        project.status = Project.Status.FAILED
        project.import_log = "\n\n".join(log_parts)
        project.save(update_fields=["status", "import_log", "updated_at"])
        _fail_pending_steps(project, str(exc)[:200])
        Event.log(
            f"failed to import project {name}: {exc}",
            project=project,
            icon="x",
            level="error",
        )
        return project


# Map an environment name to its deploy step key (PROJECTS-2 stepper).
_DEPLOY_STEP_BY_ENV = {"staging": "deploy_staging", "prod": "deploy_prod"}


def deploy_environment(environment, *, commit_sha=None):
    """Deploy one environment via ``deploys.services.deploy`` while advancing the
    matching import-progress step (deploy_staging / deploy_prod).

    This is the projects-owned deploy entrypoint used by the UI/import flow so
    the live stepper reflects build/up output. It is purely additive: it wraps
    ``deploys.services.deploy`` and never changes that contract, so the
    autonomous loop (which calls ``deploys.services.deploy`` directly) is
    unaffected. Returns the Deployment (or None on failure).
    """
    from .models import ImportStep

    step_key = _DEPLOY_STEP_BY_ENV.get(environment.name)
    project = getattr(environment, "project", None)

    if step_key and project is not None:
        _set_step(project, step_key, ImportStep.State.RUNNING, f"deploying {environment.name}")

    try:
        from deploys import services as deploy_services

        dep = deploy_services.deploy(environment, commit_sha=commit_sha)
    except Exception as exc:  # noqa: BLE001
        if step_key and project is not None:
            _set_step(project, step_key, ImportStep.State.FAILED, str(exc)[:200])
        return None

    if step_key and project is not None:
        status = getattr(dep, "status", "") or ""
        # 'failed' status -> red step; anything else (live/building/queued) -> done.
        if status == "failed":
            err = getattr(dep, "error", "") or "deploy failed"
            _set_step(project, step_key, ImportStep.State.FAILED, err[:200])
        else:
            detail = f"{environment.name} {status}".strip() if status else environment.name
            port = getattr(dep, "port", None)
            if port:
                detail = f"{detail} · :{port}"
            _set_step(project, step_key, ImportStep.State.DONE, detail)
    return dep
