#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
usage() {
    cat <<'EOF'
Usage: deploy-backend-frontend-static.sh --project-root PATH --tool-root PATH
  [--launcher-root PATH] --expected-before SHA --target-commit SHA
  --deployment-key KEY --check-only|--execute
Publishes backend code and a locked public/static build. Database and attachment
migrations are prohibited. Backups and fingerprints are retained. Rollback
restores code/static only and never restores database or attachment data.
EOF
}
PROJECT_ROOT="" TOOL_ROOT="" LAUNCHER_ROOT="" EXPECTED_BEFORE="" TARGET_COMMIT="" DEPLOYMENT_KEY="" MODE=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --project-root) PROJECT_ROOT="${2:?}"; shift 2 ;;
        --tool-root) TOOL_ROOT="${2:?}"; shift 2 ;;
        --launcher-root) LAUNCHER_ROOT="${2:?}"; shift 2 ;;
        --expected-before) EXPECTED_BEFORE="${2:?}"; shift 2 ;;
        --target-commit) TARGET_COMMIT="${2:?}"; shift 2 ;;
        --deployment-key) DEPLOYMENT_KEY="${2:?}"; shift 2 ;;
        --check-only|--execute) [[ -z "$MODE" ]] || { usage >&2; exit 2; }; MODE="$1"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done
[[ -n "$PROJECT_ROOT" && -n "$TOOL_ROOT" && -n "$EXPECTED_BEFORE" && -n "$TARGET_COMMIT" && -n "$DEPLOYMENT_KEY" && -n "$MODE" ]] || { usage >&2; exit 2; }
[[ "$DEPLOYMENT_KEY" =~ ^[A-Za-z0-9._-]+$ && ${#DEPLOYMENT_KEY} -le 128 ]] || { echo "Invalid deployment key" >&2; exit 2; }
SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
PROJECT_ROOT="$(realpath -e "$PROJECT_ROOT")"
TOOL_ROOT="$(realpath -e "$TOOL_ROOT")"
LAUNCHER_ROOT="$(realpath -e "${LAUNCHER_ROOT:-$PROJECT_ROOT}")"
[[ "$SCRIPT_ROOT" == "$LAUNCHER_ROOT" && "$TOOL_ROOT" != "$PROJECT_ROOT" ]] || { echo "Launcher, production, and target roots do not match the trusted layout" >&2; exit 1; }

DB_PATH="$PROJECT_ROOT/data/production.db"
BACKUP_DIR="$PROJECT_ROOT/data/backups"
DEPLOYMENT_DIR="$PROJECT_ROOT/data/deployments"
MANIFEST="$DEPLOYMENT_DIR/$DEPLOYMENT_KEY.json"
LOG_FILE="$DEPLOYMENT_DIR/$DEPLOYMENT_KEY.log"
FENCE="$DEPLOYMENT_DIR/write-fence.json"
BACKUP_METADATA="$BACKUP_DIR/backup_$DEPLOYMENT_KEY.json"
OLD_STATIC_BACKUP="$BACKUP_DIR/static_before_$DEPLOYMENT_KEY.tar.gz"
TARGET_STATIC_BACKUP="$BACKUP_DIR/static_target_$DEPLOYMENT_KEY.tar.gz"
STATIC_DIR="$PROJECT_ROOT/public/static"
STATIC_STAGE="$PROJECT_ROOT/public/.static-$DEPLOYMENT_KEY.stage"
STATIC_PREVIOUS="$PROJECT_ROOT/public/.static-$DEPLOYMENT_KEY.previous"
HEALTH_URL="${HEALTH_URL:-https://127.0.0.1/api/health}"
NODE_BIN="${NODE_BIN:-node}" NPM_BIN="${NPM_BIN:-npm}"
TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/qr-backend-static-$DEPLOYMENT_KEY.XXXXXX")"
WORKTREE="$TMP_DIR/target-worktree" BUILD_DIR="$TMP_DIR/static-build"
TARGET_ARCHIVE="$TMP_DIR/static-target.tar.gz" NPM_CACHE="$TMP_DIR/npm-cache"
NPM_CONFIG="$TMP_DIR/npmrc" TRUST="$TMP_DIR/trusted-controls"
install -d -m 0700 "$TRUST/scripts"
: > "$TRUST/scripts/__init__.py"
chmod 0700 "$TRUST/scripts/__init__.py"
for file in backend_frontend_static_release.py code_only_release.py deployment_manifest.py rollback-deployment.sh backup-db.sh; do
    install -m 0700 "$LAUNCHER_ROOT/scripts/$file" "$TRUST/scripts/$file"
done
export PYTHONPATH="$TRUST${PYTHONPATH:+:$PYTHONPATH}"
RELEASE_TOOL="$TRUST/scripts/backend_frontend_static_release.py"
MANIFEST_TOOL="$TRUST/scripts/deployment_manifest.py"
ROLLBACK="$TRUST/scripts/rollback-deployment.sh"
BACKUP="$TRUST/scripts/backup-db.sh"
FENCE_OWNED=false SERVICE_STOPPED=false MANIFEST_STARTED=false PREPARED=false BASELINE=false ROLLING_BACK=false

cleanup() {
    local code=$?
    if [[ -d "$WORKTREE" ]]; then
        case "$WORKTREE" in "$TMP_DIR"/target-worktree) git -C "$TOOL_ROOT" worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true ;; *) echo "Unsafe worktree cleanup path" >&2 ;; esac
    fi
    if [[ -d "$TMP_DIR" ]]; then
        case "$TMP_DIR" in "${TMPDIR:-/tmp}"/qr-backend-static-*) rm -rf -- "$TMP_DIR" ;; *) echo "Unsafe temp cleanup path" >&2 ;; esac
    fi
    return "$code"
}
trap cleanup EXIT
log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
status() { local args=(update --manifest "$MANIFEST" --status "$1" --detail "$2"); [[ -z "${3:-}" ]] || args+=(--database-version "$3"); python3 "$MANIFEST_TOOL" "${args[@]}"; }
health() {
    local commit="$1" fence="$2" key="$3" body
    body="$(curl -ksSf --max-time 5 "$HEALTH_URL" 2>/dev/null)" || return 1
    printf '%s' "$body" | python3 -c 'import json,sys; p=json.load(sys.stdin); c=sys.argv[1]; f=sys.argv[2]=="true"; k=sys.argv[3]; ok=p.get("status")=="ok" and p.get("db")=="connected" and p.get("commit")==c and p.get("write_fenced") is f; ok=ok and (p.get("deployment_key")==k if f else not p.get("deployment_key")); raise SystemExit(0 if ok else 1)' "$commit" "$fence" "$key"
}
wait_health() { for _ in {1..30}; do health "$1" "$2" "$3" && return 0; sleep 1; done; return 1; }
stop_service() { systemctl --user stop qr-system.service; systemctl --user is-active --quiet qr-system.service && return 1; SERVICE_STOPPED=true; }
preflight() {
    local args=(preflight --tool-root "$TOOL_ROOT" --project-root "$PROJECT_ROOT" --database "$DB_PATH" --before-commit "$EXPECTED_BEFORE" --target-commit "$TARGET_COMMIT")
    [[ "$MODE" != "--check-only" ]] || args+=(--check-only)
    python3 "$RELEASE_TOOL" "${args[@]}"
}

build_static() {
    git -C "$TOOL_ROOT" worktree add --quiet --detach "$WORKTREE" "$TARGET_COMMIT"
    [[ -f "$WORKTREE/package.json" && -f "$WORKTREE/package-lock.json" ]] || { echo "Locked frontend inputs missing" >&2; return 1; }
    command -v "$NODE_BIN" >/dev/null && command -v "$NPM_BIN" >/dev/null || { echo "Pinned Node/npm binaries unavailable" >&2; return 1; }
    export PATH="$(dirname "$(command -v "$NODE_BIN")"):$(dirname "$(command -v "$NPM_BIN")"):$PATH"
    local wanted_node wanted_npm actual_node actual_npm
    wanted_node="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["engines"]["node"])' "$WORKTREE/package.json")"
    wanted_npm="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["engines"]["npm"])' "$WORKTREE/package.json")"
    actual_node="$("$NODE_BIN" --version | sed 's/^v//')" actual_npm="$("$NPM_BIN" --version)"
    [[ "$actual_node" == "$wanted_node" && "$actual_npm" == "$wanted_npm" ]] || { echo "Toolchain mismatch: required Node $wanted_node/npm $wanted_npm; got $actual_node/$actual_npm" >&2; return 1; }
    log "isolated build: Node $actual_node / npm $actual_npm"
    install -d -m 0700 "$NPM_CACHE"
    printf 'cache=%s\nfund=false\naudit=false\nupdate-notifier=false\n' "$NPM_CACHE" > "$NPM_CONFIG"
    (
        cd "$WORKTREE"
        "$NODE_BIN" frontend/scripts/check-toolchain.mjs
        NPM_CONFIG_USERCONFIG="$NPM_CONFIG" NPM_CONFIG_CACHE="$NPM_CACHE" "$NPM_BIN" ci --ignore-scripts --no-audit --no-fund --cache "$NPM_CACHE"
        NPM_CONFIG_USERCONFIG="$NPM_CONFIG" NPM_CONFIG_CACHE="$NPM_CACHE" "$NPM_BIN" run check:api
        NPM_CONFIG_USERCONFIG="$NPM_CONFIG" NPM_CONFIG_CACHE="$NPM_CACHE" "$NPM_BIN" run check:imports
        NPM_CONFIG_USERCONFIG="$NPM_CONFIG" NPM_CONFIG_CACHE="$NPM_CACHE" "$NPM_BIN" run check:layers
        NPM_CONFIG_USERCONFIG="$NPM_CONFIG" NPM_CONFIG_CACHE="$NPM_CACHE" "$NPM_BIN" run build -- --outDir "$BUILD_DIR" --emptyOutDir
    )
    test -s "$BUILD_DIR/index.html"
    python3 "$RELEASE_TOOL" archive-static --source "$BUILD_DIR" --archive "$TARGET_ARCHIVE"
}
safe_abort() {
    if [[ -e "$STATIC_STAGE" || -L "$STATIC_STAGE" ]]; then
        [[ -d "$STATIC_STAGE" && ! -L "$STATIC_STAGE" ]] || return 1
        python3 "$RELEASE_TOOL" verify-static-backup --directory "$STATIC_STAGE" --archive "$TARGET_STATIC_BACKUP" || return 1
        case "$STATIC_STAGE" in
            "$PROJECT_ROOT"/public/.static-*.stage) rm -rf -- "$STATIC_STAGE" || return 1 ;;
            *) return 1 ;;
        esac
    fi
    python3 "$RELEASE_TOOL" verify-baseline-checkout --project-root "$PROJECT_ROOT" --before-commit "$EXPECTED_BEFORE" || return 1
    systemctl --user start qr-system.service || return 1
    SERVICE_STOPPED=false
    wait_health "$EXPECTED_BEFORE" true "$DEPLOYMENT_KEY" || { stop_service || true; return 1; }
    python3 "$MANIFEST_TOOL" authorize-code-only-abort --manifest "$MANIFEST" --database "$DB_PATH" --project-root "$PROJECT_ROOT" --current-commit "$EXPECTED_BEFORE" || { stop_service || true; return 1; }
    python3 "$RELEASE_TOOL" verify-baseline-checkout --project-root "$PROJECT_ROOT" --before-commit "$EXPECTED_BEFORE" || { stop_service || true; return 1; }
    python3 "$MANIFEST_TOOL" release-fence --manifest "$MANIFEST" --mode abort || { stop_service || true; return 1; }
    FENCE_OWNED=false
}
on_error() {
    local code=$? line="${BASH_LINENO[0]:-unknown}" current rollback_code
    trap - ERR
    [[ "$ROLLING_BACK" != true ]] || exit "$code"
    ROLLING_BACK=true; set +e
    log "release failed at line $line with exit $code"
    [[ "$MANIFEST_STARTED" == true ]] && status deployment_failed "static release failed at line $line with exit $code" || true
    if [[ "$FENCE_OWNED" == true ]]; then
        [[ "$SERVICE_STOPPED" == true ]] || stop_service || true
        if [[ "$PREPARED" == true && "$BASELINE" == true ]]; then
            current="$(git -C "$PROJECT_ROOT" rev-parse HEAD 2>/dev/null)"
            if [[ "$current" == "$EXPECTED_BEFORE" ]]; then
                safe_abort && log "aborted before code switch; old service healthy and fence safely released" || { stop_service >/dev/null 2>&1 || true; log "abort verification failed; fence retained"; }
            else
                QR_PROJECT_ROOT="$PROJECT_ROOT" DB_PATH="$DB_PATH" DEPLOYMENT_MANIFEST_TOOL_SOURCE="$MANIFEST_TOOL" bash "$ROLLBACK" "$MANIFEST"
                rollback_code=$?
                if [[ $rollback_code -eq 0 ]]; then FENCE_OWNED=false; SERVICE_STOPPED=false; log "code/static rollback accepted; data was not restored"
                else systemctl --user stop qr-system.service >/dev/null 2>&1 || true; log "rollback failed; service stopped, fence/evidence retained"; fi
            fi
        else
            systemctl --user stop qr-system.service >/dev/null 2>&1 || true
            log "baseline incomplete; service stopped, fence/evidence retained"
        fi
    fi
    exit "$code"
}

preflight_output="$(preflight)"
printf '%s\n' "$preflight_output"
health "$EXPECTED_BEFORE" false "" && systemctl --user is-active --quiet qr-system.service || { echo "Production must be healthy, active, and unfenced at expected SHA" >&2; exit 1; }
[[ ! -L "$FENCE" && ! -e "$FENCE" ]] || { echo "Write-fence file is present; refusing release preparation" >&2; exit 1; }
if [[ "$MODE" == "--check-only" ]]; then
    python3 "$MANIFEST_TOOL" non-data-state-evidence --database "$DB_PATH" --project-root "$PROJECT_ROOT"
    build_static
    log "check-only passed; production checkout, database, attachments, static tree, fence, and service state were not changed"
    exit 0
fi
build_static
preflight_output="$(preflight)"
health "$EXPECTED_BEFORE" false "" && systemctl --user is-active --quiet qr-system.service || { echo "Production changed during checks" >&2; exit 1; }
for path in "$PROJECT_ROOT/data" "$BACKUP_DIR" "$DEPLOYMENT_DIR" "$MANIFEST" "$LOG_FILE" "$BACKUP_METADATA" "$OLD_STATIC_BACKUP" "$TARGET_STATIC_BACKUP" "$FENCE" "$STATIC_DIR" "$STATIC_STAGE" "$STATIC_PREVIOUS"; do
    [[ ! -L "$path" ]] || { echo "Unsafe symlink: $path" >&2; exit 1; }
done
[[ -d "$PROJECT_ROOT/public" && ! -L "$PROJECT_ROOT/public" && -d "$STATIC_DIR" ]] || { echo "public and public/static must be real directories" >&2; exit 1; }
for path in "$MANIFEST" "$LOG_FILE" "$BACKUP_METADATA" "$OLD_STATIC_BACKUP" "$TARGET_STATIC_BACKUP" "$FENCE" "$STATIC_STAGE" "$STATIC_PREVIOUS"; do
    [[ ! -e "$path" ]] || { echo "Idempotency/evidence path already exists: $path" >&2; exit 1; }
done
install -d -m 0700 "$BACKUP_DIR" "$DEPLOYMENT_DIR"
( set -o noclobber; : > "$LOG_FILE" ) 2>/dev/null || { echo "Deployment log already exists" >&2; exit 1; }
exec > >(tee -a "$LOG_FILE") 2>&1
trap on_error ERR
DB_VERSION="$(printf '%s' "$preflight_output" | python3 -c 'import json,sys; print(json.load(sys.stdin)["database"]["user_version"])')"
log "begin backend/static deployment $DEPLOYMENT_KEY -> $TARGET_COMMIT"
python3 "$MANIFEST_TOOL" begin-code-only --scope backend_frontend_static --output "$MANIFEST" --deployment-key "$DEPLOYMENT_KEY" --before-commit "$EXPECTED_BEFORE" --target-commit "$TARGET_COMMIT" --source-database-version "$DB_VERSION" --target-database-version "$DB_VERSION" --write-fence "$FENCE"
MANIFEST_STARTED=true
python3 "$MANIFEST_TOOL" acquire-fence --path "$FENCE" --deployment-key "$DEPLOYMENT_KEY" --target-commit "$TARGET_COMMIT"
FENCE_OWNED=true
python3 "$MANIFEST_TOOL" record-code-only-fence --manifest "$MANIFEST"
wait_health "$EXPECTED_BEFORE" true "$DEPLOYMENT_KEY" || { echo "Service did not acknowledge the write fence" >&2; false; }
stop_service
PRESERVE_EXISTING_BACKUPS=1 BACKUP_TIMESTAMP="$DEPLOYMENT_KEY" BACKUP_METADATA_FILE="$BACKUP_METADATA" DEPLOYMENT_MANIFEST_TOOL_SOURCE="$MANIFEST_TOOL" QR_PROJECT_ROOT="$PROJECT_ROOT" DB_PATH="$DB_PATH" BACKUP_DIR="$BACKUP_DIR" bash "$BACKUP"
python3 "$RELEASE_TOOL" archive-static --source "$STATIC_DIR" --archive "$OLD_STATIC_BACKUP"
install -m 0600 "$TARGET_ARCHIVE" "$TARGET_STATIC_BACKUP"
python3 "$MANIFEST_TOOL" prepare --scope backend_frontend_static --output "$MANIFEST" --backup-metadata "$BACKUP_METADATA" --release-backup "$OLD_STATIC_BACKUP" --target-static-backup "$TARGET_STATIC_BACKUP" --deployment-key "$DEPLOYMENT_KEY" --before-commit "$EXPECTED_BEFORE" --target-commit "$TARGET_COMMIT" --target-database-version "$DB_VERSION" --write-fence "$FENCE"
PREPARED=true
python3 "$MANIFEST_TOOL" capture-code-only-state --manifest "$MANIFEST" --database "$DB_PATH" --project-root "$PROJECT_ROOT"
BASELINE=true
status backup_verified "DB/attachment/static backups and fingerprints verified; DB and attachment migrations prohibited" "$DB_VERSION"
python3 "$RELEASE_TOOL" extract-static --archive "$TARGET_STATIC_BACKUP" --destination "$STATIC_STAGE"
git -C "$PROJECT_ROOT" switch --detach "$TARGET_COMMIT"
python3 "$MANIFEST_TOOL" write-commit-marker --project-root "$PROJECT_ROOT" --expected-current "$EXPECTED_BEFORE" --commit "$TARGET_COMMIT"
python3 "$RELEASE_TOOL" exchange-static --active "$STATIC_DIR" --staged "$STATIC_STAGE"
mv "$STATIC_STAGE" "$STATIC_PREVIOUS"
status starting "backend code switched and static directory atomically exchanged behind write fence" "$DB_VERSION"
systemctl --user start qr-system.service
SERVICE_STOPPED=false
wait_health "$TARGET_COMMIT" true "$DEPLOYMENT_KEY" || { echo "Target failed fenced health acceptance" >&2; false; }
python3 "$MANIFEST_TOOL" verify-code-only-state --manifest "$MANIFEST" --database "$DB_PATH" --project-root "$PROJECT_ROOT"
status accepted_fenced "backend health, unchanged DB/attachment fingerprints, and built static SHA-256 inventory accepted; migrations prohibited" "$DB_VERSION"
python3 "$RELEASE_TOOL" verify-static-backup --directory "$STATIC_PREVIOUS" --archive "$OLD_STATIC_BACKUP"
case "$STATIC_PREVIOUS" in
    "$PROJECT_ROOT"/public/.static-*.previous) ;;
    *) echo "Unsafe temporary static backup path" >&2; false ;;
esac
[[ -d "$STATIC_PREVIOUS" && ! -L "$STATIC_PREVIOUS" ]] || { echo "Temporary static backup is missing or unsafe" >&2; false; }
rm -rf -- "$STATIC_PREVIOUS"
python3 "$MANIFEST_TOOL" authorize-release --manifest "$MANIFEST"
python3 "$MANIFEST_TOOL" release-fence --manifest "$MANIFEST" --mode deployment
FENCE_OWNED=false
log "deployment succeeded; DB and attachments were not migrated, restored, or modified"
