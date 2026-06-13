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


def detect_runtime(path: str) -> dict:
    """Inspect a checked-out repo and return how to install & run it.

    Returns a dict with keys: framework, install_command, run_command,
    app_subdir. ``run_command`` MUST accept a ``$PORT`` env var / placeholder
    so deploys can bind it to an allocated port. For Django, prefer
    ``python manage.py runserver 0.0.0.0:$PORT`` (or gunicorn). Detect Django
    by presence of manage.py; otherwise inspect Procfile / package.json.
    """
    root = path

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

    # --- generic fallback ---
    install_command = (
        "pip install -r requirements.txt"
        if os.path.isfile(os.path.join(root, "requirements.txt"))
        else ""
    )
    return {
        "framework": "generic",
        "install_command": install_command,
        "run_command": "python -m http.server $PORT",
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

    log_parts = []
    try:
        # A plain local source tree (no .git) is initialized so it can be cloned.
        _ensure_local_git_repo(repo_url)

        # Clean any stale destination so clone is idempotent.
        if os.path.exists(dest):
            import shutil

            shutil.rmtree(dest, ignore_errors=True)

        rc, out = _run(_clone_args(repo_url, dest))
        log_parts.append(f"$ git clone {repo_url} {dest}\n{out}")
        if rc != 0:
            raise RuntimeError(f"git clone failed (exit {rc})")

        # Determine default branch.
        default_branch = "main"
        rc, out = _run(["git", "symbolic-ref", "--short", "HEAD"], cwd=dest)
        if rc == 0 and out.strip():
            default_branch = out.strip()
        else:
            rc2, out2 = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=dest)
            if rc2 == 0 and out2.strip() and out2.strip() != "HEAD":
                default_branch = out2.strip()

        # Detect runtime.
        runtime = detect_runtime(dest)
        log_parts.append(f"detected runtime: {runtime}")

        project.default_branch = default_branch
        project.framework = runtime["framework"]
        project.install_command = runtime["install_command"]
        project.run_command = runtime["run_command"]
        project.app_subdir = runtime["app_subdir"]
        project.status = Project.Status.READY
        project.import_log = "\n\n".join(log_parts)
        project.save()

        # Create staging + prod environments.
        Environment.objects.get_or_create(
            project=project,
            name="staging",
            defaults={"kind": Environment.Kind.STAGING, "branch": default_branch},
        )
        Environment.objects.get_or_create(
            project=project,
            name="prod",
            defaults={"kind": Environment.Kind.PROD, "branch": default_branch},
        )

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
        Event.log(
            f"failed to import project {name}: {exc}",
            project=project,
            icon="x",
            level="error",
        )
        return project
