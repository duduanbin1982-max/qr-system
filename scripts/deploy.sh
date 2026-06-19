#!/bin/bash
# QR System — Auto Deploy Script
set -e

cd /home/dubin/qr-system
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Deploy started"

# Pull latest
git pull deploy master 2>&1

# Build frontend
cd frontend
npm run build 2>&1
cd ..

# Clear pycache
find modules -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# Reload service
systemctl --user reload qr-system.service 2>&1 || systemctl --user restart qr-system.service 2>&1

# Health check
sleep 3
HTTP=$(curl -sk -o /dev/null -w '%{http_code}' https://127.0.0.1/ 2>/dev/null)
if [ "$HTTP" = "200" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Deploy OK (HTTP $HTTP)"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Deploy WARN (HTTP $HTTP)" >&2
fi
