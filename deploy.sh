#!/bin/bash
# ============================================================
# QR System — Manual Deploy Script (with test gate)
# Usage: ./deploy.sh [--skip-tests]
# ============================================================
set -e
cd /home/dubin/qr-system

SKIP_TESTS=0
if [ "$1" = "--skip-tests" ]; then SKIP_TESTS=1; fi

echo ">>> Pulling latest code..."
git pull deploy master

if [ $SKIP_TESTS -eq 0 ]; then
    echo ">>> Running tests..."
    export SECRET_KEY="deploy-test-key"
    export ENABLE_SWAGGER="false"
    if python3 -m pytest tests/ -v --tb=short; then
        echo ">>> Tests PASSED ✓"
    else
        echo ">>> Tests FAILED ✗ — aborting deploy"
        exit 1
    fi
else
    echo ">>> Tests SKIPPED"
fi

echo ">>> Building frontend and restarting service..."
bash scripts/build.sh --restart
sleep 2

echo ">>> Smoke test..."
if curl -sk --max-time 5 https://127.0.0.1:3000/api/health | grep -q '"status":"ok"'; then
    echo ">>> Deploy SUCCESS ✓"
else
    echo ">>> Smoke test FAILED ✗"
    systemctl --user status qr-system.service --no-pager
fi
