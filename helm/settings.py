"""
Django settings for Hull — the autonomous software operating system.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "HELM_SECRET_KEY",
    "django-insecure-aj18l2wj-y+0r0#+_p=$)saq^jyq=3hglt730!f=f_58a0b9qh",
)

DEBUG = os.environ.get("HELM_DEBUG", "1") == "1"

ALLOWED_HOSTS = ["*"]
CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("HELM_CSRF_ORIGINS", "").split(",") if o
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Hull apps
    "accounts",
    "core",
    "projects",
    "deploys",
    "agents",
    "vcs",
    "observability",
    "orchestration",
    "issues",
    "wiki",
    "oncall",
    "enterprise",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.CurrentOrgMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "helm.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.helm_globals",
            ],
        },
    },
]

WSGI_APPLICATION = "helm.wsgi.application"
ASGI_APPLICATION = "helm.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
        "OPTIONS": {"timeout": 20},
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

# ---------------------------------------------------------------------------
# Hull platform configuration
# ---------------------------------------------------------------------------

# Where Hull keeps cloned repos, worktrees, and per-deployment runtime data.
HELM_DATA_DIR = Path(os.environ.get("HELM_DATA_DIR", BASE_DIR / ".helm_data"))
HELM_REPOS_DIR = HELM_DATA_DIR / "repos"
HELM_WORKTREES_DIR = HELM_DATA_DIR / "worktrees"
HELM_LOGS_DIR = HELM_DATA_DIR / "logs"
for _d in (HELM_REPOS_DIR, HELM_WORKTREES_DIR, HELM_LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Port range allocated to managed app deployments.
HELM_PORT_START = int(os.environ.get("HELM_PORT_START", "9101"))
HELM_PORT_END = int(os.environ.get("HELM_PORT_END", "9199"))

# Public base URL of the control plane (used to build deployment proxy URLs).
HELM_BASE_URL = os.environ.get("HELM_BASE_URL", "http://localhost:8000")

# User-facing product brand (the code/package/env names stay "helm"/"HELM_*").
# Rename the product here in one place.
HELM_PRODUCT_NAME = os.environ.get("HELM_PRODUCT_NAME", "Hull")
HELM_PRODUCT_TAGLINE = os.environ.get(
    "HELM_PRODUCT_TAGLINE", "The autonomous software operating system"
)

# Command used to spawn autonomous Claude agents (headless).
HELM_CLAUDE_BIN = os.environ.get("HELM_CLAUDE_BIN", "claude")
HELM_AGENT_MODEL = os.environ.get("HELM_AGENT_MODEL", "claude-opus-4-8")

# Temporal — orchestration backend. If unreachable, Hull falls back to an
# in-process threaded runner so the product still works without the server.
HELM_TEMPORAL_HOST = os.environ.get("HELM_TEMPORAL_HOST", "localhost:7233")
HELM_TEMPORAL_NAMESPACE = os.environ.get("HELM_TEMPORAL_NAMESPACE", "default")
HELM_TEMPORAL_TASK_QUEUE = os.environ.get("HELM_TEMPORAL_TASK_QUEUE", "helm")
HELM_USE_TEMPORAL = os.environ.get("HELM_USE_TEMPORAL", "0") == "1"
