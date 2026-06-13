#!/usr/bin/env bash
# Provision a fresh Ubuntu 22.04+ VM to run the Helm control plane with public
# URLs. Idempotent. Run as a sudo-capable user.
#
#   export ANTHROPIC_API_KEY=sk-ant-...      # required: agents run `claude -p`
#   export HELM_DOMAIN=helm.example.com      # optional: a domain -> auto TLS
#   export HELM_REPO=https://github.com/you/helm.git   # this repo (public)
#   curl -fsSL .../deploy/bootstrap.sh | bash   (or scp + run)
set -euo pipefail

HELM_DIR="${HELM_DIR:-$HOME/helm}"
HELM_REPO="${HELM_REPO:?set HELM_REPO to the public git URL of this repo}"
: "${ANTHROPIC_API_KEY:?set ANTHROPIC_API_KEY so remediation agents can run}"
HELM_DOMAIN="${HELM_DOMAIN:-}"
PUBLIC_IP="$(curl -fsSL https://api.ipify.org || echo 127.0.0.1)"
# Fall back to a sslip.io hostname (auto-resolves to the IP) so Caddy can still
# get TLS without owning a domain.
HELM_HOST="${HELM_DOMAIN:-${PUBLIC_IP}.sslip.io}"

echo "▸ Installing system packages"
sudo apt-get update -y
sudo apt-get install -y git curl build-essential python3.11 python3.11-venv \
  python3.11-dev debian-keyring debian-archive-keyring apt-transport-https

echo "▸ Installing uv"
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

echo "▸ Installing Node + Claude Code CLI (for headless agents)"
if ! command -v node >/dev/null; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
  sudo apt-get install -y nodejs
fi
sudo npm install -g @anthropic-ai/claude-code || npm install -g @anthropic-ai/claude-code

echo "▸ Installing Temporal CLI (dev server)"
curl -fsSL https://temporal.download/cli.sh | sh || true
export PATH="$HOME/.temporalio/bin:$PATH"

echo "▸ Installing Caddy (TLS reverse proxy)"
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
  sudo apt-get update -y && sudo apt-get install -y caddy
fi

echo "▸ Cloning Helm into $HELM_DIR"
if [ -d "$HELM_DIR/.git" ]; then git -C "$HELM_DIR" pull --ff-only; else git clone "$HELM_REPO" "$HELM_DIR"; fi
cd "$HELM_DIR"

echo "▸ Python env + deps"
uv venv --python 3.11 .venv
source .venv/bin/activate
uv pip install -r requirements.txt

echo "▸ Writing environment file"
cat > "$HELM_DIR/.env" <<EOF
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
HELM_SECRET_KEY=$(python -c 'import secrets;print(secrets.token_urlsafe(48))')
HELM_DEBUG=0
HELM_BASE_URL=https://${HELM_HOST}
HELM_CSRF_ORIGINS=https://${HELM_HOST}
HELM_USE_TEMPORAL=0
HELM_AUTO_REMEDIATE=1
HELM_AUTO_MERGE=1
EOF

echo "▸ Migrate + collectstatic"
set -a; source "$HELM_DIR/.env"; set +a
python manage.py migrate --noinput
python manage.py collectstatic --noinput

echo "▸ Installing systemd service"
sudo tee /etc/systemd/system/helm.service >/dev/null <<EOF
[Unit]
Description=Helm control plane
After=network.target
[Service]
WorkingDirectory=${HELM_DIR}
EnvironmentFile=${HELM_DIR}/.env
Environment=PATH=${HELM_DIR}/.venv/bin:${HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=${HELM_DIR}/.venv/bin/gunicorn helm.wsgi:application --bind 127.0.0.1:8000 --workers 3 --threads 4 --timeout 120
Restart=always
User=${USER}
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now helm

echo "▸ Configuring Caddy for https://${HELM_HOST}"
sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
${HELM_HOST} {
    encode gzip
    reverse_proxy 127.0.0.1:8000
}
EOF
sudo systemctl restart caddy

echo
echo "✅ Helm is live:  https://${HELM_HOST}"
echo "   Kick the demo:  cd ${HELM_DIR} && source .venv/bin/activate && set -a && source .env && set +a && python manage.py helm_demo --break"
