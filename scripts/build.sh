#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

npm run build
test -s public/static/index.html

if [[ "${1:-}" == "--restart" ]]; then
    systemctl --user reload-or-restart qr-system.service
fi
