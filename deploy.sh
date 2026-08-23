#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_SOURCE="$PROJECT_ROOT/deploy/qr-system.service"
UNIT_TARGET="$HOME/.config/systemd/user/qr-system.service"
DB_PATH="${DB_PATH:-$PROJECT_ROOT/data/production.db}"
BACKUP_DIR="${BACKUP_DIR:-$PROJECT_ROOT/data/backups}"
DEPLOYMENT_DIR="${DEPLOYMENT_DIR:-$PROJECT_ROOT/data/deployments}"
HEALTH_URL="${HEALTH_URL:-https://127.0.0.1/api/health}"
GUNICORN_BIN="${GUNICORN_BIN:-$HOME/.local/bin/gunicorn}"
PYTEST_BIN="${PYTEST_BIN:-$HOME/.local/bin/pytest}"
ROLLBACK_SCRIPT="$PROJECT_ROOT/scripts/rollback-deployment.sh"
MANIFEST_TOOL="$PROJECT_ROOT/scripts/deployment_manifest.py"
deployment_manifest=""
rollback_armed=false
service_stopped=false

log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

health_is_ok() {
    curl -ksSf --max-time 5 "$HEALTH_URL" 2>/dev/null \
        | python3 -c 'import json,sys; raise SystemExit(json.load(sys.stdin).get("status") != "ok")'
}

install_user_service() {
    install -D -m 0644 "$UNIT_SOURCE" "$UNIT_TARGET"
    systemctl --user daemon-reload
    systemctl --user enable qr-system.service >/dev/null
}

atomic_write_deployed_commit() {
    local commit="$1"
    local temporary="$PROJECT_ROOT/.deployed_commit.tmp.$$"
    printf '%s\n' "$commit" > "$temporary"
    chmod 0600 "$temporary"
    mv -f "$temporary" "$PROJECT_ROOT/.deployed_commit"
}

record_manifest_status() {
    local status="$1"
    local detail="$2"
    local database_version="${3:-}"
    local args=(update --manifest "$deployment_manifest" --status "$status" --detail "$detail")
    if [[ -n "$database_version" ]]; then
        args+=(--database-version "$database_version")
    fi
    python3 "$MANIFEST_TOOL" "${args[@]}"
}

rollback_on_error() {
    local exit_code=$?
    local failed_line="${BASH_LINENO[0]:-unknown}"
    trap - ERR
    if [[ "$rollback_armed" == true && -n "$deployment_manifest" ]]; then
        set +e
        log "deployment failed at line $failed_line; starting verified rollback"
        record_manifest_status failed "deploy.sh failed at line $failed_line with exit $exit_code"
        bash "$ROLLBACK_SCRIPT" "$deployment_manifest"
        local rollback_code=$?
        if [[ $rollback_code -ne 0 ]]; then
            log "automatic rollback failed; manual recovery is required"
        fi
        exit "$exit_code"
    fi
    if [[ "$service_stopped" == true ]]; then
        set +e
        log "deployment preparation failed at line $failed_line; restoring deployed code"
        if [[ -n "${before_commit:-}" && "$before_commit" =~ ^[0-9a-f]{40}$ ]]; then
            git -C "$PROJECT_ROOT" switch --detach "$before_commit"
            atomic_write_deployed_commit "$before_commit"
        fi
        systemctl --user start qr-system.service
    fi
    exit "$exit_code"
}

trap rollback_on_error ERR

cd "$PROJECT_ROOT"

if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
    echo "Deployment refused: Git worktree is not clean" >&2
    git status --short >&2
    exit 1
fi

commit="$(git rev-parse --verify HEAD)"
if [[ ! "$commit" =~ ^[0-9a-f]{40}$ ]]; then
    echo "Deployment refused: target commit is invalid" >&2
    exit 1
fi
log "validating commit $commit"
python3 scripts/check_secrets.py
"$GUNICORN_BIN" --check-config -c gunicorn.conf.py server:app

if [[ "${1:-}" == "--check-only" ]]; then
    log "deployment preflight passed"
    exit 0
fi

if [[ ! -f .deployed_commit ]]; then
    echo "Deployment refused: .deployed_commit is missing" >&2
    exit 1
fi
before_commit="$(tr -d '[:space:]' < .deployed_commit)"
if [[ ! "$before_commit" =~ ^[0-9a-f]{40}$ ]]; then
    echo "Deployment refused: .deployed_commit is invalid" >&2
    exit 1
fi
git cat-file -e "$before_commit^{commit}"

log "running complete test suite"
"$PYTEST_BIN" -q

log "installing locked frontend dependencies"
npm ci --ignore-scripts --no-audit --no-fund

log "ensuring Playwright Chromium runtime"
bash scripts/install-playwright-runtime.sh

log "running frontend unit suite"
npm run test:unit

log "running critical browser suite"
npm run test:e2e

target_database_version="$(python3 -c "from modules.bootstrap import load_environment; load_environment(); from modules.migrations import LATEST_VERSION; print(LATEST_VERSION)")"
if [[ ! "$target_database_version" =~ ^[0-9]+$ ]]; then
    echo "Deployment refused: target database version is invalid" >&2
    exit 1
fi

deployment_key="${DEPLOYMENT_KEY:-deploy-$(date +%Y%m%d-%H%M%S)-${commit:0:8}}"
if [[ ! "$deployment_key" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "Deployment refused: DEPLOYMENT_KEY contains unsupported characters" >&2
    exit 1
fi
install -d -m 0700 "$BACKUP_DIR" "$DEPLOYMENT_DIR"
deployment_manifest="$DEPLOYMENT_DIR/$deployment_key.json"
backup_metadata="$BACKUP_DIR/backup_${deployment_key}.json"
release_backup="$BACKUP_DIR/release_${deployment_key}.tar.gz"

log "stopping application for the final consistent backup"
systemctl --user stop qr-system.service
service_stopped=true

log "creating and verifying production database and attachment backups"
QR_PROJECT_ROOT="$PROJECT_ROOT" DB_PATH="$DB_PATH" BACKUP_DIR="$BACKUP_DIR" \
    BACKUP_METADATA_FILE="$backup_metadata" bash scripts/backup-db.sh
if [[ -d public/static ]]; then
    tar -czf "$release_backup" -C "$PROJECT_ROOT" public/static
else
    tar -czf "$release_backup" --files-from /dev/null
fi
chmod 0600 "$release_backup"
python3 "$MANIFEST_TOOL" prepare \
    --output "$deployment_manifest" \
    --backup-metadata "$backup_metadata" \
    --release-backup "$release_backup" \
    --deployment-key "$deployment_key" \
    --before-commit "$before_commit" \
    --target-commit "$commit" \
    --target-database-version "$target_database_version"
rollback_armed=true
record_manifest_status service_stopped "service stopped and final backup verified"

log "copying legacy employee documents into managed attachment storage"
bash scripts/migrate-employee-documents.sh

log "running production database migrations"
python3 -c "from modules.bootstrap import load_environment; load_environment(); from modules.migrations import run_migrations; run_migrations()"
schema_version="$(python3 -c "from modules.bootstrap import load_environment; load_environment(); from modules.db import verify_schema; print(verify_schema())")"
if [[ "$schema_version" != "$target_database_version" ]]; then
    echo "Deployment failed: migrated schema version does not match target" >&2
    false
fi
record_manifest_status migrated "database migration and read-only schema verification passed" "$schema_version"

log "building and atomically publishing frontend"
bash scripts/publish-frontend.sh

log "installing authoritative user service"
install_user_service
atomic_write_deployed_commit "$commit"
record_manifest_status starting "deployment marker synchronized; starting service" "$schema_version"
systemctl --user start qr-system.service

for _ in {1..20}; do
    if health_is_ok; then
        record_manifest_status succeeded "schema and health acceptance passed" "$schema_version"
        rollback_armed=false
        service_stopped=false
        log "deployment succeeded: $commit"
        exit 0
    fi
    sleep 1
done

echo "Deployment failed: health check did not become ready" >&2
false
