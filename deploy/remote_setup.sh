#!/usr/bin/env bash
# Provision Helm ON the VM, assuming the code already lives in $HELM_DIR and an
# env file is present at $HELM_DIR/.env. Idempotent. Invoked by deploy/push.sh.
set -euo pipefail

HELM_DIR="${HELM_DIR:-$HOME/helm}"
cd "$HELM_DIR"
set -a; [ -f .env ] && source .env; set +a
: "${ANTHROPIC_API_KEY:?‌.env must define ANTHROPIC_API_KEY}"

PUBLIC_IP="$(curl -fsSL https://api.ipify.org || echo 127.0.0.1)"
HELM_HOST="${HELM_DOMAIN:-${PUBLIC_IP}.sslip.io}"

echo "▸ System packages"
sudo apt-get update -y
sudo apt-get install -y git curl build-essential python3.11 python3.11-venv python3.11-dev

command -v uv >/dev/null || { curl -LsSf https://astral.sh/uv/install.sh | sh; }
export PATH="$HOME/.local/bin:$PATH"

echo "▸ Node + Claude Code CLI"
command -v node >/dev/null || { curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -; sudo apt-get install -y nodejs; }
command -v claude >/dev/null || sudo npm install -g @anthropic-ai/claude-code

echo "▸ Caddy"
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update -y && sudo apt-get install -y caddy
fi

echo "▸ Python env + deps"
uv venv --python 3.11 .venv
source .venv/bin/activate
uv pip install -r requirements.txt

# Make sure the public URL is reflected in env for CSRF + proxy link building.
grep -q '^HELM_BASE_URL=' .env || echo "HELM_BASE_URL=https://${HELM_HOST}" >> .env
grep -q '^HELM_CSRF_ORIGINS=' .env || echo "HELM_CSRF_ORIGINS=https://${HELM_HOST}" >> .env
set -a; source .env; set +a

echo "▸ Migrate + collectstatic"
python manage.py migrate --noinput
python manage.py collectstatic --noinput

echo "▸ systemd service"
sudo tee /etc/systemd/system/helm.service >/dev/null <<EOF
[Unit]
Description=Helm control plane
After=network.target
[Service]
WorkingDirectory=${HELM_DIR}
EnvironmentFile=${HELM_DIR}/.env
Environment=PATH=${HELM_DIR}/.venv/bin:${HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=${HELM_DIR}/.venv/bin/gunicorn helm.wsgi:application --bind 127.0.0.1:8000 --workers 3 --threads 6 --timeout 180
Restart=always
User=${USER}
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable helm
sudo systemctl restart helm

echo "▸ Caddy reverse proxy for https://${HELM_HOST}"
sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
${HELM_HOST} {
    encode gzip
    reverse_proxy 127.0.0.1:8000
}
EOF
sudo systemctl restart caddy

sleep 3
echo
echo "✅ Helm live at: https://${HELM_HOST}"
echo "   Demo:  cd ${HELM_DIR} && source .venv/bin/activate && set -a && source .env && set +a && python manage.py helm_demo --break --reset"
