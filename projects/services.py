"""Project import & runtime detection.  [OWNER: Slice A agent]

Contract used by orchestration + UI. Keep these signatures stable.
"""

from __future__ import annotations


def detect_runtime(path: str) -> dict:
    """Inspect a checked-out repo and return how to install & run it.

    Returns a dict with keys: framework, install_command, run_command,
    app_subdir. ``run_command`` MUST accept a ``$PORT`` env var / placeholder
    so deploys can bind it to an allocated port. For Django, prefer
    ``python manage.py runserver 0.0.0.0:$PORT`` (or gunicorn). Detect Django
    by presence of manage.py; otherwise inspect Procfile / package.json.
    """
    raise NotImplementedError


def import_project(name: str, repo_url: str, *, description: str = ""):
    """Clone ``repo_url`` into settings.HELM_REPOS_DIR/<slug>, detect runtime,
    create ``staging`` (branch=default) and ``prod`` (branch=default)
    Environments, mark the Project READY, and log core.Event entries.

    May be called for a local path repo_url too (use ``file://`` or a path).
    Returns the Project. Sets Project.status=FAILED + import_log on error.
    """
    raise NotImplementedError
