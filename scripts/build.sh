#!/bin/bash
# QR System - Automated Build Script
# Usage: bash scripts/build.sh [--restart]
set -e
cd "$(dirname "$0")/.."

echo "=== Building Frontend ==="
cd frontend && npm run build 2>&1 | tail -3
cd ..

NEW_JS=$(ls public/static/assets/*.js 2>/dev/null | head -1 | xargs basename)
OLD_JS=$(grep -oP '/static/assets/index-\w+\.js' public/index-v3.html 2>/dev/null | head -1 | xargs basename)

if [ -n "$NEW_JS" ] && [ "$NEW_JS" != "$OLD_JS" ]; then
    sed -i "s|$OLD_JS|$NEW_JS|g" public/index-v3.html
    echo "Hash updated: $OLD_JS -> $NEW_JS"
else
    echo "Hash unchanged: $NEW_JS"
fi

if [ "$1" = "--restart" ]; then
    echo "=== Restarting Service ==="
    echo 'niDAyede3.14' | sudo -S systemctl restart qr-system
    sleep 1
    systemctl is-active qr-system && echo "Service active" || echo "Service FAILED"
fi

echo "=== Build Complete ==="
