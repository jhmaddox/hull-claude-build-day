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
sudo apt-get install -y git curl build-essential
# uv provides Python 3.11 (Ubuntu 22.04 has no python3.11 apt package).
command -v uv >/dev/null || { curl -LsSf https://astral.sh/uv/install.sh | sh; }
export PATH="$HOME/.local/bin:$PATH"
uv python install 3.11

echo "▸ Node + Claude Code CLI"
command -v node >/dev/null || { curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -; sudo apt-get install -y nodejs; }
command -v claude >/dev/null || sudo npm install -g @anthropic-ai/claude-code

echo "▸ Docker (for Docker-Compose env deploys)"
command -v docker >/dev/null || { curl -fsSL https://get.docker.com | sudo sh; }
sudo usermod -aG docker "$USER" || true
sudo systemctl enable --now docker || true

echo "▸ Caddy"
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update -y && sudo apt-get install -y caddy
fi

echo "▸ Python env + deps"
uv venv --python 3.11 --clear .venv
source .venv/bin/activate
uv pip install -r requirements.txt

# Make sure the public URL is reflected in env for CSRF + proxy link building.
grep -q '^HELM_BASE_URL=' .env || echo "HELM_BASE_URL=https://${HELM_HOST}" >> .env
grep -q '^HELM_CSRF_ORIGINS=' .env || echo "HELM_CSRF_ORIGINS=https://${HELM_HOST}" >> .env
set -a; source .env; set +a

echo "▸ Fresh DB + migrate + collectstatic (demo box: clean multitenant schema)"
# Demo box — start from a clean DB so the new multitenant schema applies cleanly
# (no leftover v1 rows). Set HELM_KEEP_DB=1 to preserve.
[ "${HELM_KEEP_DB:-0}" = "1" ] || rm -f db.sqlite3
python manage.py migrate --noinput
python manage.py collectstatic --noinput

echo "▸ Seed a demo login (demo / demo12345, org 'Acme Inc')"
python manage.py shell -c "
from django.contrib.auth.models import User
from accounts.models import Org, Membership
u,_=User.objects.get_or_create(username='demo', defaults={'email':'demo@hull.dev'})
u.set_password('demo12345'); u.is_staff=True; u.is_superuser=True; u.save()
org,_=Org.objects.get_or_create(slug='acme', defaults={'name':'Acme Inc'})
Membership.objects.get_or_create(org=org, user=u, defaults={'role':'owner'})
print('seeded demo/acme')
"

echo "▸ systemd service"
sudo tee /etc/systemd/system/helm.service >/dev/null <<EOF
[Unit]
Description=Helm control plane
After=network.target
[Service]
WorkingDirectory=${HELM_DIR}
EnvironmentFile=${HELM_DIR}/.env
Environment=PATH=${HELM_DIR}/.venv/bin:${HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=${HELM_DIR}/.venv/bin/gunicorn helm.wsgi:application --bind 127.0.0.1:8000 --workers 1 --threads 8 --timeout 180
Restart=always
User=${USER}
[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable helm
sudo systemctl restart helm

echo "▸ Caddy: control plane + on-demand TLS for app domains"
# Control-plane host gets a normal cert. Every other host (the per-deployment
# *.apps.<domain> hostnames) gets an ON-DEMAND cert, gated by Hull's
# /deploys/tls/ask allowlist (only active Domains are approved). All hosts proxy
# to Hull on :8000; Hull's HostProxyMiddleware routes by Host to the right
# deployment. DNS wildcard *.apps.<domain> must point at this box.
sudo tee /etc/caddy/Caddyfile >/dev/null <<EOF
{
    on_demand_tls {
        # Trailing slash REQUIRED: Django APPEND_SLASH 301-redirects the
        # slashless URL, and Caddy refuses to follow redirects on the ask check.
        ask http://127.0.0.1:8000/deploys/tls/ask/
    }
}

${HELM_HOST} {
    encode gzip
    reverse_proxy 127.0.0.1:8000
}

https:// {
    tls {
        on_demand
    }
    encode gzip
    reverse_proxy 127.0.0.1:8000
}
EOF
sudo systemctl restart caddy

sleep 3
echo
echo "✅ Helm live at: https://${HELM_HOST}"
echo "   Demo:  cd ${HELM_DIR} && source .venv/bin/activate && set -a && source .env && set +a && python manage.py helm_demo --break --reset"
