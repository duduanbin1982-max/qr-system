#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_LIB_DIR="$HOME/.local/playwright-debs/root/usr/lib/x86_64-linux-gnu"

if [[ -d "$USER_LIB_DIR" ]]; then
    export LD_LIBRARY_PATH="$USER_LIB_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi

cd "$PROJECT_ROOT"
exec npx playwright test --config playwright.config.js "$@"
