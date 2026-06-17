#!/bin/bash
# QR System - Automated Build Script
set -e
cd "$(dirname "$0")/.."

echo "=== Building Frontend ==="
cd frontend && npm run build 2>&1 | tail -3
cd ..

echo "=== Syncing index-v3.html ==="
if [ -f public/static/index.html ]; then
    cp -f public/static/index.html public/index-v3.html
    echo "index-v3.html synced"
else
    echo "WARNING: public/static/index.html not found!"
fi

echo "=== Generated assets ==="
ls -la public/static/assets/ 2>/dev/null || echo "(no assets)"

if [ "$1" = "--restart" ]; then
    echo "=== Restarting Service ==="
    systemctl --user restart qr-system
    sleep 1
    systemctl --user is-active qr-system && echo "Service active" || echo "Service FAILED"
fi

echo "=== Build Complete ==="
