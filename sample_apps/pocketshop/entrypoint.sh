#!/usr/bin/env sh
# PocketShop production-style entrypoint.
#
# One command brings up a fresh, seeded, styled instance on $PORT:
#   1. apply migrations (idempotent; migration 0002 seeds the catalog)
#   2. optionally collectstatic (WhiteNoise also serves from source via
#      WHITENOISE_USE_FINDERS, so this is optional — controlled by
#      POCKETSHOP_COLLECTSTATIC=1)
#   3. serve on 0.0.0.0:$PORT (gunicorn if available, else Django runserver)
#
# Works both inside the Docker image and as a plain process on a host with the
# deps installed. Keeps the plain-process run path (README "Run it") working.
set -e

PORT="${PORT:-8000}"

echo "[entrypoint] applying migrations (idempotent; seeds catalog)..."
python manage.py migrate --noinput

if [ "${POCKETSHOP_COLLECTSTATIC:-0}" = "1" ]; then
  echo "[entrypoint] collecting static files..."
  python manage.py collectstatic --noinput
else
  echo "[entrypoint] skipping collectstatic (WhiteNoise serves from source via WHITENOISE_USE_FINDERS)"
fi

echo "[entrypoint] starting PocketShop on 0.0.0.0:${PORT}"
if command -v gunicorn >/dev/null 2>&1; then
  exec gunicorn pocketshop.wsgi:application \
    --bind "0.0.0.0:${PORT}" \
    --workers "${WEB_CONCURRENCY:-2}" \
    --access-logfile - \
    --error-logfile -
else
  echo "[entrypoint] gunicorn not found; falling back to Django runserver"
  exec python manage.py runserver "0.0.0.0:${PORT}"
fi
