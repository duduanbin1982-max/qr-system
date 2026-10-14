#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

usage() {
    cat <<'EOF'
Usage:
  bash /path/to/current-production/scripts/deploy-code-only.sh \
    --project-root PATH --tool-root TARGET_WORKTREE --expected-before SHA \
    --target-commit SHA --deployment-key KEY --check-only
  bash /path/to/current-production/scripts/deploy-code-only.sh \
    --project-root PATH --tool-root TARGET_WORKTREE --expected-before SHA \
    --target-commit SHA --deployment-key KEY --execute

The code-only path never runs database migrations, attachment migrations, or
frontend builds/publication. The launcher and all release controls must come
from the current production checkout at --expected-before. The separate release
tool checkout must be clean and exactly at --target-commit. --execute is an
explicit production write.
EOF
}

PROJECT_ROOT=""
TOOL_ROOT=""
EXPECTED_BEFORE=""
TARGET_COMMIT=""
DEPLOYMENT_KEY=""
MODE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --project-root) PROJECT_ROOT="${2:?missing --project-root value}"; shift 2 ;;
        --tool-root) TOOL_ROOT="${2:?missing --tool-root value}"; shift 2 ;;
        --expected-before) EXPECTED_BEFORE="${2:?missing --expected-before value}"; shift 2 ;;
        --target-commit) TARGET_COMMIT="${2:?missing --target-commit value}"; shift 2 ;;
        --deployment-key) DEPLOYMENT_KEY="${2:?missing --deployment-key value}"; shift 2 ;;
        --check-only|--execute)
            if [[ -n "$MODE" ]]; then usage >&2; exit 2; fi
            MODE="$1"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if [[ -z "$PROJECT_ROOT" || -z "$TOOL_ROOT" || -z "$EXPECTED_BEFORE" || -z "$TARGET_COMMIT" || -z "$DEPLOYMENT_KEY" || -z "$MODE" ]]; then
    usage >&2
    exit 2
fi
if [[ ! "$DEPLOYMENT_KEY" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "Deployment key contains unsupported characters" >&2
    exit 2
fi
if [[ ${#DEPLOYMENT_KEY} -gt 128 ]]; then
    echo "Deployment key must be no longer than 128 characters" >&2
    exit 2
fi

SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
PROJECT_ROOT="$(realpath -e "$PROJECT_ROOT")"
TOOL_ROOT="$(realpath -e "$TOOL_ROOT")"
if [[ "$SCRIPT_ROOT" != "$PROJECT_ROOT" ]]; then
    echo "Deployment refused: code-only launcher must come from the current production checkout" >&2
    exit 1
fi
if [[ "$TOOL_ROOT" == "$PROJECT_ROOT" ]]; then
    echo "Deployment refused: target tool checkout must be separate from production" >&2
    exit 1
fi
DB_PATH="$PROJECT_ROOT/data/production.db"
BACKUP_DIR="$PROJECT_ROOT/data/backups"
DEPLOYMENT_DIR="$PROJECT_ROOT/data/deployments"
MANIFEST_PATH="$DEPLOYMENT_DIR/$DEPLOYMENT_KEY.json"
DEPLOYMENT_LOG="$DEPLOYMENT_DIR/$DEPLOYMENT_KEY.log"
WRITE_FENCE_PATH="$DEPLOYMENT_DIR/write-fence.json"
BACKUP_METADATA="$BACKUP_DIR/backup_${DEPLOYMENT_KEY}.json"
RELEASE_BACKUP="$BACKUP_DIR/release_${DEPLOYMENT_KEY}.tar.gz"
HEALTH_URL="${HEALTH_URL:-https://127.0.0.1/api/health}"
GUNICORN_BIN="${GUNICORN_BIN:-$HOME/.local/bin/gunicorn}"
PYTEST_BIN="${PYTEST_BIN:-$HOME/.local/bin/pytest}"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/qr-code-only-${DEPLOYMENT_KEY}.XXXXXX")"
TEST_WORKTREE="$TMP_DIR/target-worktree"
TRUST_ROOT="$TMP_DIR/trusted-controls"
install -d -m 0700 "$TRUST_ROOT/scripts"
for control in code_only_release.py deployment_manifest.py rollback-deployment.sh backup-db.sh; do
    install -m 0700 "$PROJECT_ROOT/scripts/$control" "$TRUST_ROOT/scripts/$control"
done
deployment_manifest="$TRUST_ROOT/scripts/deployment_manifest.py"
code_only_release="$TRUST_ROOT/scripts/code_only_release.py"
rollback_script="$TRUST_ROOT/scripts/rollback-deployment.sh"
backup_script="$TRUST_ROOT/scripts/backup-db.sh"
fence_owned=false
service_stopped=false
manifest_started=false
manifest_prepared=false
baseline_captured=false
rollback_in_progress=false

cleanup() {
    local cleanup_status=$?
    if [[ -n "$TEST_WORKTREE" && -d "$TEST_WORKTREE" ]]; then
        case "$TEST_WORKTREE" in
            "$TMP_DIR"/target-worktree)
                git -C "$TOOL_ROOT" worktree remove --force "$TEST_WORKTREE" >/dev/null 2>&1 || true
                ;;
            *) echo "Refusing to remove unexpected test worktree path: $TEST_WORKTREE" >&2 ;;
        esac
    fi
    if [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]]; then
        case "$TMP_DIR" in
            "${TMPDIR:-/tmp}"/qr-code-only-*) rm -rf -- "$TMP_DIR" ;;
            *) echo "Refusing to remove unexpected temporary path: $TMP_DIR" >&2 ;;
        esac
    fi
    return "$cleanup_status"
}
trap cleanup EXIT

log() {
    printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

record_status() {
    local args=(update --manifest "$MANIFEST_PATH" --status "$1" --detail "$2")
    if [[ -n "${3:-}" ]]; then
        args+=(--database-version "$3")
    fi
    python3 "$deployment_manifest" "${args[@]}"
}

health_matches() {
    local expected_commit="$1"
    local expected_fence="$2"
    local expected_key="$3"
    local payload
    payload="$(curl -ksSf --max-time 5 "$HEALTH_URL" 2>/dev/null)" || return 1
    printf '%s' "$payload" | python3 -c \
        'import json,sys; p=json.load(sys.stdin); commit=sys.argv[1]; fenced=sys.argv[2] == "true"; key=sys.argv[3]; ok=(p.get("status")=="ok" and p.get("db")=="connected" and p.get("commit")==commit and p.get("write_fenced") is fenced); ok=ok and ((p.get("deployment_key")==key) if fenced else not p.get("deployment_key")); raise SystemExit(0 if ok else 1)' \
        "$expected_commit" "$expected_fence" "$expected_key"
}

wait_for_health() {
    local expected_commit="$1"
    local expected_fence="$2"
    local expected_key="$3"
    for _ in {1..30}; do
        if health_matches "$expected_commit" "$expected_fence" "$expected_key"; then
            return 0
        fi
        sleep 1
    done
    return 1
}

stop_service() {
    systemctl --user stop qr-system.service
    if systemctl --user is-active --quiet qr-system.service; then
        echo "qr-system.service did not stop" >&2
        return 1
    fi
    service_stopped=true
}

safe_abort_before_switch() {
    if [[ "$baseline_captured" != true ]]; then
        return 1
    fi
    local current_commit marker_commit
    current_commit="$(git -C "$PROJECT_ROOT" rev-parse HEAD)"
    if [[ -L "$PROJECT_ROOT/.deployed_commit" || ! -f "$PROJECT_ROOT/.deployed_commit" ]]; then
        return 1
    fi
    marker_commit="$(tr -d '[:space:]' < "$PROJECT_ROOT/.deployed_commit")"
    if [[ "$current_commit" != "$EXPECTED_BEFORE" || "$marker_commit" != "$EXPECTED_BEFORE" ]]; then
        return 1
    fi
    if ! systemctl --user start qr-system.service; then
        return 1
    fi
    service_stopped=false
    if ! wait_for_health "$EXPECTED_BEFORE" true "$DEPLOYMENT_KEY"; then
        stop_service || true
        return 1
    fi
    if ! python3 "$deployment_manifest" authorize-code-only-abort \
        --manifest "$MANIFEST_PATH" \
        --database "$DB_PATH" \
        --project-root "$PROJECT_ROOT" \
        --current-commit "$current_commit"; then
        stop_service || true
        return 1
    fi
    if ! python3 "$deployment_manifest" release-fence \
        --manifest "$MANIFEST_PATH" --mode abort; then
        stop_service || true
        return 1
    fi
    fence_owned=false
    return 0
}

rollback_on_error() {
    local exit_code=$?
    local failed_line="${BASH_LINENO[0]:-unknown}"
    trap - ERR
    if [[ "$rollback_in_progress" == true ]]; then
        exit "$exit_code"
    fi
    rollback_in_progress=true
    set +e
    log "code-only deployment failed at line $failed_line with exit $exit_code"
    if [[ "$fence_owned" != true && -e "$WRITE_FENCE_PATH" ]]; then
        fence_key="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8")).get("deployment_key", ""))' "$WRITE_FENCE_PATH" 2>/dev/null || true)"
        if [[ "$fence_key" == "$DEPLOYMENT_KEY" || -z "$fence_key" ]]; then
            # A malformed fence is fail-closed and must be treated as owned.
            fence_owned=true
        fi
    fi
    if [[ "$manifest_started" == true ]]; then
        record_status deployment_failed \
            "deploy-code-only.sh failed at line $failed_line with exit $exit_code" || true
    fi
    if [[ "$fence_owned" == true ]]; then
        if [[ "$service_stopped" != true ]]; then
            stop_service || true
        fi
        if [[ "$manifest_prepared" == true && "$baseline_captured" == true ]]; then
            if safe_abort_before_switch; then
                log "deployment safely aborted; original service is healthy and write fence was released after durable verification"
            else
                local current_commit
                current_commit="$(git -C "$PROJECT_ROOT" rev-parse HEAD 2>/dev/null)"
                if [[ "$current_commit" != "$EXPECTED_BEFORE" ]]; then
                    log "attempting code-only rollback; production data will not be restored or overwritten"
                    QR_PROJECT_ROOT="$PROJECT_ROOT" \
                    DB_PATH="$DB_PATH" \
                    DEPLOYMENT_MANIFEST_TOOL_SOURCE="$deployment_manifest" \
                        bash "$rollback_script" "$MANIFEST_PATH"
                    local rollback_code=$?
                    if [[ $rollback_code -eq 0 ]]; then
                        fence_owned=false
                        service_stopped=false
                        log "code-only rollback completed and passed fenced health acceptance"
                    else
                        systemctl --user stop qr-system.service >/dev/null 2>&1 || true
                        log "code-only rollback failed; service remains stopped and the write fence is retained"
                    fi
                else
                    systemctl --user stop qr-system.service >/dev/null 2>&1 || true
                    log "safe abort could not be verified; service remains stopped and the write fence is retained"
                fi
            fi
        else
            systemctl --user stop qr-system.service >/dev/null 2>&1 || true
            log "backup or invariant baseline is incomplete; service remains stopped and the write fence is retained for manual recovery"
        fi
    fi
    exit "$exit_code"
}

run_preflight() {
    python3 "$code_only_release" preflight \
        --tool-root "$TOOL_ROOT" \
        --project-root "$PROJECT_ROOT" \
        --database "$DB_PATH" \
        --before-commit "$EXPECTED_BEFORE" \
        --target-commit "$TARGET_COMMIT"
}

run_release_checks() {
    local snapshot_db="$TMP_DIR/production-snapshot.db"
    python3 -c 'import sqlite3,sys; source=sqlite3.connect("file:"+sys.argv[1]+"?mode=ro", uri=True); target=sqlite3.connect(sys.argv[2]); source.backup(target); target.close(); source.close()' \
        "$DB_PATH" "$snapshot_db"
    git -C "$TOOL_ROOT" worktree add --quiet --detach "$TEST_WORKTREE" "$TARGET_COMMIT"
    (
        cd "$TEST_WORKTREE"
        python3 scripts/check_secrets.py
        SECRET_KEY="code-only-preflight-not-a-production-secret" \
        DEPLOYMENT_WRITE_FENCE_PATH="$TMP_DIR/no-write-fence.json" \
        DB_PATH="$snapshot_db" "$GUNICORN_BIN" --check-config \
            -c "$TEST_WORKTREE/gunicorn.conf.py" server:app
        SECRET_KEY="code-only-preflight-not-a-production-secret" \
        DEPLOYMENT_WRITE_FENCE_PATH="$TMP_DIR/no-write-fence.json" \
        DB_PATH="$snapshot_db" "$PYTEST_BIN" -q
    )
}

preflight_output="$(run_preflight)"
printf '%s\n' "$preflight_output"
if ! health_matches "$EXPECTED_BEFORE" false ""; then
    echo "Deployment refused: current production service is not healthy, unfenced, and on the expected commit" >&2
    exit 1
fi
if ! systemctl --user is-active --quiet qr-system.service; then
    echo "Deployment refused: qr-system.service must be active before a controlled release" >&2
    exit 1
fi
if [[ "$MODE" == "--check-only" ]]; then
    run_release_checks
    log "code-only deployment preflight passed; no production files, fence, or service state changed"
    exit 0
fi

run_release_checks
preflight_output="$(run_preflight)"
database_version="$(printf '%s' "$preflight_output" | python3 -c 'import json,sys; print(json.load(sys.stdin)["database"]["user_version"])')"
if ! health_matches "$EXPECTED_BEFORE" false "" \
    || ! systemctl --user is-active --quiet qr-system.service; then
    echo "Deployment refused: production health or service state changed during release checks" >&2
    exit 1
fi
for protected_path in \
    "$PROJECT_ROOT/data" "$BACKUP_DIR" "$DEPLOYMENT_DIR" \
    "$MANIFEST_PATH" "$DEPLOYMENT_LOG" "$BACKUP_METADATA" \
    "$RELEASE_BACKUP" "$WRITE_FENCE_PATH"; do
    if [[ -L "$protected_path" ]]; then
        echo "Deployment refused: evidence/state path is a symlink: $protected_path" >&2
        exit 1
    fi
done
if [[ -e "$MANIFEST_PATH" || -e "$DEPLOYMENT_LOG" || -e "$BACKUP_METADATA" || -e "$RELEASE_BACKUP" || -e "$WRITE_FENCE_PATH" ]]; then
    echo "Deployment refused: idempotency-key evidence or write fence already exists" >&2
    exit 1
fi
install -d -m 0700 "$BACKUP_DIR" "$DEPLOYMENT_DIR"
if ! ( set -o noclobber; : > "$DEPLOYMENT_LOG" ) 2>/dev/null; then
    echo "Deployment refused: deployment log already exists" >&2
    exit 1
fi
exec > >(tee -a "$DEPLOYMENT_LOG") 2>&1
trap rollback_on_error ERR

log "starting controlled code-only deployment key=$DEPLOYMENT_KEY target=$TARGET_COMMIT"
python3 "$deployment_manifest" begin-code-only \
    --output "$MANIFEST_PATH" \
    --deployment-key "$DEPLOYMENT_KEY" \
    --before-commit "$EXPECTED_BEFORE" \
    --target-commit "$TARGET_COMMIT" \
    --source-database-version "$database_version" \
    --target-database-version "$database_version" \
    --write-fence "$WRITE_FENCE_PATH"
manifest_started=true

python3 "$deployment_manifest" acquire-fence \
    --path "$WRITE_FENCE_PATH" \
    --deployment-key "$DEPLOYMENT_KEY" \
    --target-commit "$TARGET_COMMIT"
fence_owned=true
python3 "$deployment_manifest" record-code-only-fence --manifest "$MANIFEST_PATH"
if ! wait_for_health "$EXPECTED_BEFORE" true "$DEPLOYMENT_KEY"; then
    echo "Deployment refused: current service did not acknowledge the write fence" >&2
    false
fi

log "stopping application after it acknowledged the write fence"
stop_service
log "creating and verifying immutable final database and attachment backups"
PRESERVE_EXISTING_BACKUPS=1 \
BACKUP_TIMESTAMP="$DEPLOYMENT_KEY" \
BACKUP_METADATA_FILE="$BACKUP_METADATA" \
DEPLOYMENT_MANIFEST_TOOL_SOURCE="$deployment_manifest" \
QR_PROJECT_ROOT="$PROJECT_ROOT" \
DB_PATH="$DB_PATH" \
BACKUP_DIR="$BACKUP_DIR" \
    bash "$backup_script"

release_backup_temporary="$RELEASE_BACKUP.partial.$$"
if [[ -d "$PROJECT_ROOT/public/static" ]]; then
    tar -czf "$release_backup_temporary" -C "$PROJECT_ROOT" public/static
else
    tar -czf "$release_backup_temporary" --files-from /dev/null
fi
tar -tzf "$release_backup_temporary" >/dev/null
ln "$release_backup_temporary" "$RELEASE_BACKUP"
rm -f "$release_backup_temporary"
chmod 0600 "$RELEASE_BACKUP"

python3 "$deployment_manifest" prepare \
    --scope code_only \
    --output "$MANIFEST_PATH" \
    --backup-metadata "$BACKUP_METADATA" \
    --release-backup "$RELEASE_BACKUP" \
    --deployment-key "$DEPLOYMENT_KEY" \
    --before-commit "$EXPECTED_BEFORE" \
    --target-commit "$TARGET_COMMIT" \
    --target-database-version "$database_version" \
    --write-fence "$WRITE_FENCE_PATH"
manifest_prepared=true
python3 "$deployment_manifest" capture-code-only-state \
    --manifest "$MANIFEST_PATH" \
    --database "$DB_PATH" \
    --project-root "$PROJECT_ROOT"
baseline_captured=true
record_status backup_verified \
    "final database, attachment, and frontend preservation backups verified; cleanup skipped; code-only fingerprints captured" \
    "$database_version"

log "switching only the production code checkout"
git -C "$PROJECT_ROOT" switch --detach "$TARGET_COMMIT"
python3 "$deployment_manifest" write-commit-marker \
    --project-root "$PROJECT_ROOT" \
    --expected-current "$EXPECTED_BEFORE" \
    --commit "$TARGET_COMMIT"
record_status starting "code switched and deployed commit marker synchronized; starting service behind write fence" "$database_version"
systemctl --user start qr-system.service
service_stopped=false

if ! wait_for_health "$TARGET_COMMIT" true "$DEPLOYMENT_KEY"; then
    echo "Deployment failed: target service did not pass fenced health acceptance" >&2
    false
fi
python3 "$deployment_manifest" verify-code-only-state \
    --manifest "$MANIFEST_PATH" \
    --database "$DB_PATH" \
    --project-root "$PROJECT_ROOT"
record_status accepted_fenced \
    "target commit, health, schema V$database_version, and unchanged business/frontend fingerprints accepted while writes remained fenced" \
    "$database_version"
python3 "$deployment_manifest" authorize-release --manifest "$MANIFEST_PATH"
python3 "$deployment_manifest" release-fence --manifest "$MANIFEST_PATH" --mode deployment
fence_owned=false
log "code-only deployment succeeded at $TARGET_COMMIT; database, attachments, and frontend were not migrated or published"
