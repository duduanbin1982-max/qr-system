#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

bash scripts/publish-frontend.sh

if [[ "${1:-}" == "--restart" ]]; then
    python3 -c "from dotenv import load_dotenv; load_dotenv('.env'); from modules.db import init_db; init_db()"
    python3 -c "from dotenv import load_dotenv; load_dotenv('.env'); import sqlite3; from modules.db import DB_PATH; from modules.migrations import LATEST_VERSION; db=sqlite3.connect(DB_PATH); version=db.execute('PRAGMA user_version').fetchone()[0]; db.close(); assert version == LATEST_VERSION, f'database migration incomplete: {version} != {LATEST_VERSION}'; print(f'database schema version: {version}')"
    systemctl --user restart qr-system.service
fi
