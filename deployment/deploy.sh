#!/bin/bash
# Install or refresh the MediaVault application on a host that already runs
# the workspace guard. nginx is owned by the workspace deployment; this script
# only builds the Python app and its systemd unit.
set -e

APP_DIR="${APP_DIR:-/srv/media_vault}"
SERVICE_NAME="mediavault"

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (use sudo)" >&2
    exit 1
fi

if [ ! -f "$APP_DIR/.env.local" ]; then
    echo "Missing $APP_DIR/.env.local; copy deployment/.env.production.example and edit it." >&2
    exit 1
fi

mkdir -p "$APP_DIR"
rsync -av --delete \
    --exclude='.git' \
    --exclude='.venv' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache' \
    --exclude='*.log' \
    --exclude='logs' \
    --exclude='uploads' \
    --exclude='videodb.sqlite' \
    --exclude='.env*' \
    ./ "$APP_DIR/"

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

chown -R www-data:www-data "$APP_DIR"

install -m 644 "$APP_DIR/deployment/mediavault.service" "/etc/systemd/system/$SERVICE_NAME.service"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo "MediaVault is listening on 127.0.0.1:5050."
echo "nginx must gate /mediavault/ through the guard and forward X-Auth-User."
