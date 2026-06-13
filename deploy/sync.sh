#!/usr/bin/env bash
# Lightweight code sync to the live EC2 box for small fixes: rsync code,
# collectstatic, restart gunicorn. Does NOT reinstall deps, touch the DB, or
# reconfigure Caddy (use deploy/push.sh for a full provision). Fast iteration.
#
#   ./deploy/sync.sh ubuntu@54.185.134.217 .helm_data/hull-demo.pem
set -euo pipefail

REMOTE="${1:?usage: sync.sh user@host [ssh-key]}"
KEY="${2:-}"
SSH_OPTS="-o StrictHostKeyChecking=accept-new"
[ -n "$KEY" ] && SSH_OPTS="$SSH_OPTS -i $KEY"
DIR="helm"

here="$(cd "$(dirname "$0")/.." && pwd)"; cd "$here"

echo "▸ rsync code -> ${REMOTE}:~/${DIR}"
rsync -az \
  --exclude '.venv/' --exclude '.helm_data/' --exclude '*.sqlite3*' \
  --exclude '__pycache__/' --exclude '.git/' --exclude 'staticfiles/' \
  --exclude 'node_modules/' --exclude '*.log' --exclude '.env' \
  -e "ssh ${SSH_OPTS}" ./ "${REMOTE}:${DIR}/"

echo "▸ migrate (no-op if none) + collectstatic + restart"
ssh ${SSH_OPTS} "${REMOTE}" "cd ~/${DIR} && source .venv/bin/activate && set -a && source .env && set +a && \
  python manage.py migrate --noinput && python manage.py collectstatic --noinput >/dev/null && \
  sudo systemctl restart helm && echo restarted"
echo "✅ synced to https://hull.dev-reservclaims.com"
