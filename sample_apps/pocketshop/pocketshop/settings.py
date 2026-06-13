"""
Django settings for PocketShop.

A small standalone storefront used as the "legacy app" that Hull imports,
deploys, monitors, and auto-fixes. It is designed to run behind Hull's
reverse proxy at a subpath (e.g. /d/<env_pk>/), so it honors HELM_SCRIPT_NAME.
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Security / debug -------------------------------------------------------
SECRET_KEY = os.environ.get(
    "POCKETSHOP_SECRET_KEY",
    "django-insecure-pocketshop-demo-key-not-for-production",
)
DEBUG = os.environ.get("POCKETSHOP_DEBUG", "1") == "1"

# Hull serves this app behind a reverse proxy with arbitrary host headers.
ALLOWED_HOSTS = ["*"]

# --- Reverse-proxy subpath support (Hull) -----------------------------------
# When Hull serves us behind /d/<env_pk>/ it sets HELM_SCRIPT_NAME.
HELM_SCRIPT_NAME = os.environ.get("HELM_SCRIPT_NAME", "")
if HELM_SCRIPT_NAME:
    FORCE_SCRIPT_NAME = HELM_SCRIPT_NAME

# CSRF: trust the public base URL Hull exposes us at, if provided.
HELM_BASE_URL = os.environ.get("HELM_BASE_URL", "")
CSRF_TRUSTED_ORIGINS = []
if HELM_BASE_URL:
    # Strip any path component; CSRF_TRUSTED_ORIGINS wants scheme://host[:port]
    from urllib.parse import urlsplit

    parts = urlsplit(HELM_BASE_URL)
    if parts.scheme and parts.netloc:
        CSRF_TRUSTED_ORIGINS.append(f"{parts.scheme}://{parts.netloc}")

# --- Applications -----------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "django.contrib.sessions",
    "django.contrib.messages",
    "store",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "pocketshop.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.messages.context_processors.messages",
                "store.context.cart_summary",
            ],
        },
    },
]

WSGI_APPLICATION = "pocketshop.wsgi.application"

# --- Database ---------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

# --- Static files (whitenoise) ----------------------------------------------
# STATIC_URL must include the reverse-proxy script prefix so {% static %}
# resolves correctly when Hull serves us under /d/<env_pk>/. Django does NOT
# apply FORCE_SCRIPT_NAME to STATIC_URL, so we prepend it ourselves.
STATIC_URL = (HELM_SCRIPT_NAME.rstrip("/") if HELM_SCRIPT_NAME else "") + "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}
# Serve static directly from source dirs too, so a fresh `runserver` (no
# collectstatic) still shows styles.
WHITENOISE_USE_FINDERS = True

# --- Sessions (cart lives in the session) -----------------------------------
SESSION_ENGINE = "django.contrib.sessions.backends.db"

# --- i18n -------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
