#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_ROOT="$HOME/.local/playwright-debs/root"
DOWNLOAD_DIR="$(mktemp -d)"
trap 'rm -rf "$DOWNLOAD_DIR"' EXIT

cd "$PROJECT_ROOT"
npx playwright install chromium

mkdir -p "$RUNTIME_ROOT"
cd "$DOWNLOAD_DIR"
apt-get download \
    libatk1.0-0t64 \
    libatk-bridge2.0-0t64 \
    libatspi2.0-0t64 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2t64 \
    libxi6 \
    libxrender1
find . -maxdepth 1 -type f -name '*.deb' -exec dpkg-deb -x {} "$RUNTIME_ROOT" \;

echo "Playwright Chromium and user-level runtime libraries are ready."
