#!/bin/bash
set -e

APP_DIR="/var/www/mediavault"
SERVICE_NAME="mediavault"

echo "=== MediaVault Deployment Script ==="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (use sudo)"
    exit 1
fi

# Install system dependencies
echo "Installing system dependencies..."
apt-get update
apt-get install -y python3 python3-pip python3-venv nginx

# Create app directory
echo "Creating application directory..."
mkdir -p "$APP_DIR"
mkdir -p "$APP_DIR/uploads"

# Copy application files (excluding git, cache, and test files)
echo "Copying application files..."
rsync -av --exclude='.git' \
      --exclude='__pycache__' \
      --exclude='*.pyc' \
      --exclude='.pytest_cache' \
      --exclude='*.log' \
      --exclude='videodb.sqlite' \
      --exclude='.env*' \
      --exclude='node_modules' \
      . "$APP_DIR/"

# Create virtual environment
echo "Setting up Python virtual environment..."
cd "$APP_DIR"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Create .env file if it doesn't exist
if [ ! -f "$APP_DIR/.env" ]; then
    echo "Creating .env file..."
    cp "$APP_DIR/.env.example" "$APP_DIR/.env" 2>/dev/null || true
    echo "SECRET_KEY=$(python3 -c 'import os; print(os.urandom(32).hex())')" >> "$APP_DIR/.env"
    echo "ALLOWED_EMAILS=" >> "$APP_DIR/.env"
    echo "Please edit $APP_DIR/.env with your configuration"
fi

# Set permissions
echo "Setting permissions..."
chown -R www-data:www-data "$APP_DIR"
chmod -R 755 "$APP_DIR"
chmod -R 755 "$APP_DIR/uploads"

# Install systemd service
echo "Installing systemd service..."
cp "$APP_DIR/deployment/mediavault.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

# Install nginx config
echo "Installing nginx configuration..."
cp "$APP_DIR/deployment/mediavault.conf" /etc/nginx/sites-available/
ln -sf /etc/nginx/sites-available/mediavault.conf /etc/nginx/sites-enabled/
nginx -t

# Start services
echo "Starting services..."
systemctl restart "$SERVICE_NAME"
systemctl restart nginx

echo ""
echo "=== Deployment Complete ==="
echo "Service status: systemctl status $SERVICE_NAME"
echo "Nginx status: systemctl status nginx"
echo "View logs: journalctl -u $SERVICE_NAME -f"
