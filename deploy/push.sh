#!/usr/bin/env bash
# Push the LOCAL Helm tree to a VM and provision it (no GitHub needed).
#
#   ./deploy/push.sh user@host [ssh-key-path]
#
# Requires a local .env.helm.local containing ANTHROPIC_API_KEY (and optionally
# HELM_DOMAIN=...). Everything else is generated on the VM.
set -euo pipefail

REMOTE="${1:?usage: push.sh user@host [ssh-key]}"
KEY="${2:-}"
SSH_OPTS="-o StrictHostKeyChecking=accept-new"
[ -n "$KEY" ] && SSH_OPTS="$SSH_OPTS -i $KEY"
HELM_DIR_REMOTE="helm"

here="$(cd "$(dirname "$0")/.." && pwd)"
cd "$here"

[ -f .env.helm.local ] || { echo "missing .env.helm.local (ANTHROPIC_API_KEY=...)"; exit 1; }

echo "▸ rsync code -> ${REMOTE}:~/${HELM_DIR_REMOTE}"
rsync -az --delete \
  --exclude '.venv/' --exclude '.helm_data/' --exclude '*.sqlite3*' \
  --exclude '__pycache__/' --exclude '.git/' --exclude 'staticfiles/' \
  --exclude 'node_modules/' --exclude '*.log' \
  -e "ssh ${SSH_OPTS}" ./ "${REMOTE}:${HELM_DIR_REMOTE}/"

echo "▸ build remote .env"
SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')"
{
  cat .env.helm.local
  echo "HELM_SECRET_KEY=${SECRET}"
  echo "HELM_DEBUG=0"
  echo "HELM_USE_TEMPORAL=0"
  echo "HELM_AUTO_REMEDIATE=1"
  echo "HELM_AUTO_MERGE=1"
  [ -n "${HELM_DOMAIN:-}" ] && echo "HELM_DOMAIN=${HELM_DOMAIN}"
} | ssh ${SSH_OPTS} "${REMOTE}" "cat > ${HELM_DIR_REMOTE}/.env && chmod 600 ${HELM_DIR_REMOTE}/.env"

echo "▸ provision on VM"
ssh ${SSH_OPTS} "${REMOTE}" "HELM_DIR=\$HOME/${HELM_DIR_REMOTE} bash \$HOME/${HELM_DIR_REMOTE}/deploy/remote_setup.sh"
