#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_SOURCE="$PROJECT_ROOT/deploy/qr-system.service"
UNIT_TARGET="$HOME/.config/systemd/user/qr-system.service"
HEALTH_URL="${HEALTH_URL:-https://127.0.0.1/api/health}"
GUNICORN_BIN="${GUNICORN_BIN:-$HOME/.local/bin/gunicorn}"
PYTEST_BIN="${PYTEST_BIN:-$HOME/.local/bin/pytest}"

log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

health_is_ok() {
    curl -ksSf --max-time 5 "$HEALTH_URL" 2>/dev/null | grep -q '"status":"ok"'
}

restore_manual_gunicorn() {
    if systemctl --user is-active --quiet qr-system.service; then
        return
    fi
    if pgrep -x gunicorn >/dev/null; then
        return
    fi
    log "systemd unavailable; restoring Gunicorn manually"
    cd "$PROJECT_ROOT"
    nohup "$GUNICORN_BIN" -c gunicorn.conf.py server:app > logs/gunicorn.log 2>&1 &
}

install_user_service() {
    install -D -m 0644 "$UNIT_SOURCE" "$UNIT_TARGET"
    systemctl --user daemon-reload
    systemctl --user enable qr-system.service >/dev/null
}

reload_application() {
    if systemctl --user is-active --quiet qr-system.service; then
        systemctl --user reload qr-system.service
        return
    fi

    local legacy_pid
    legacy_pid="$(pgrep -o -x gunicorn || true)"
    if [[ -n "$legacy_pid" ]]; then
        log "stopping legacy Gunicorn master $legacy_pid"
        kill -TERM "$legacy_pid"
        for _ in {1..30}; do
            kill -0 "$legacy_pid" 2>/dev/null || break
            sleep 1
        done
    fi

    if ! systemctl --user start qr-system.service; then
        restore_manual_gunicorn
        return 1
    fi
}

cd "$PROJECT_ROOT"

if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
    echo "Deployment refused: Git worktree is not clean" >&2
    git status --short >&2
    exit 1
fi

commit="$(git rev-parse HEAD)"
log "validating commit $commit"
python3 scripts/check_secrets.py
"$GUNICORN_BIN" --check-config -c gunicorn.conf.py server:app

if [[ "${1:-}" == "--check-only" ]]; then
    log "deployment preflight passed"
    exit 0
fi

log "running complete test suite"
"$PYTEST_BIN" -q

log "running frontend unit suite"
npm run test:unit

log "running critical browser suite"
npm run test:e2e

log "backing up production database"
bash scripts/backup-db.sh

log "running production database migrations"
python3 -c "from dotenv import load_dotenv; load_dotenv('.env'); from modules.migrations import run_migrations; run_migrations()"

rollback_dir="$(mktemp -d "$PROJECT_ROOT/data/deploy-rollback.XXXXXX")"
trap 'rm -rf "$rollback_dir"' EXIT
if [[ -d public/static ]]; then
    cp -a public/static "$rollback_dir/static"
fi

log "building frontend"
npm run build

log "installing authoritative user service"
install_user_service
if ! reload_application; then
    [[ -d "$rollback_dir/static" ]] && rm -rf public/static && cp -a "$rollback_dir/static" public/static
    echo "Deployment failed: application service could not start" >&2
    exit 1
fi

for _ in {1..20}; do
    if health_is_ok; then
        printf '%s\n' "$commit" > .deployed_commit
        log "deployment succeeded: $commit"
        exit 0
    fi
    sleep 1
done

[[ -d "$rollback_dir/static" ]] && rm -rf public/static && cp -a "$rollback_dir/static" public/static
restore_manual_gunicorn
echo "Deployment failed: health check did not become ready" >&2
exit 1
