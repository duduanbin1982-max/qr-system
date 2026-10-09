#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="${QR_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
MANIFEST_PATH="${1:?deployment manifest path is required}"
DB_PATH="${DB_PATH:-$PROJECT_ROOT/data/production.db}"
HEALTH_URL="${HEALTH_URL:-https://127.0.0.1/api/health}"
UNIT_SOURCE="$PROJECT_ROOT/deploy/qr-system.service"
UNIT_TARGET="$HOME/.config/systemd/user/qr-system.service"
MANIFEST_TOOL="$PROJECT_ROOT/scripts/deployment_manifest.py"
MANIFEST_TOOL_SNAPSHOT="$(mktemp "$PROJECT_ROOT/data/deployments/.deployment-manifest.XXXXXX.py")"
install -m 0600 "$MANIFEST_TOOL" "$MANIFEST_TOOL_SNAPSHOT"
cleanup_manifest_tool() {
    rm -f "$MANIFEST_TOOL_SNAPSHOT"
}
trap cleanup_manifest_tool EXIT

record_rollback_failure() {
    local exit_code=$?
    local failed_line="${BASH_LINENO[0]:-unknown}"
    trap - ERR
    set +e
    python3 "$MANIFEST_TOOL_SNAPSHOT" update \
        --manifest "$MANIFEST_PATH" \
        --status rollback_failed \
        --detail "rollback failed at line $failed_line with exit $exit_code"
    echo "Rollback failed at line $failed_line" >&2
    exit "$exit_code"
}

trap record_rollback_failure ERR

field() {
    python3 "$MANIFEST_TOOL_SNAPSHOT" field \
        --manifest "$MANIFEST_PATH" --path "$1"
}

before_commit="$(field before_commit)"
if [[ ! "$before_commit" =~ ^[0-9a-f]{40}$ ]]; then
    echo "Invalid rollback commit in deployment manifest" >&2
    exit 1
fi

rollback_supports_runtime_fence=false
if git -C "$PROJECT_ROOT" cat-file -e "$before_commit:modules/deployment_write_fence.py" 2>/dev/null; then
    rollback_supports_runtime_fence=true
fi

systemctl --user stop qr-system.service || true
python3 "$MANIFEST_TOOL_SNAPSHOT" restore \
    --manifest "$MANIFEST_PATH" \
    --database "$DB_PATH" \
    --project-root "$PROJECT_ROOT"

# A rollback target created before the write-fence feature cannot enforce the
# fence in-process.  Keep the service stopped and release only after verified
# data restoration; later targets retain the fence through their health check.
if [[ "$rollback_supports_runtime_fence" != true ]]; then
    python3 "$MANIFEST_TOOL_SNAPSHOT" release-fence \
        --manifest "$MANIFEST_PATH" --mode rollback
fi

git -C "$PROJECT_ROOT" cat-file -e "$before_commit^{commit}"
git -C "$PROJECT_ROOT" switch --detach "$before_commit"
printf '%s\n' "$before_commit" > "$PROJECT_ROOT/.deployed_commit.tmp.$$"
mv -f "$PROJECT_ROOT/.deployed_commit.tmp.$$" "$PROJECT_ROOT/.deployed_commit"

install -D -m 0644 "$UNIT_SOURCE" "$UNIT_TARGET"
systemctl --user daemon-reload
systemctl --user start qr-system.service

for _ in {1..20}; do
    health_payload="$(curl -ksSf --max-time 5 "$HEALTH_URL" 2>/dev/null || true)"
    if [[ -n "$health_payload" ]] && printf '%s' "$health_payload" \
        | python3 -c 'import json,sys; raise SystemExit(json.load(sys.stdin).get("status") != "ok")'; then
        if [[ "$rollback_supports_runtime_fence" == true ]]; then
            if ! printf '%s' "$health_payload" \
                | python3 -c 'import json,sys; raise SystemExit(json.load(sys.stdin).get("write_fenced") is not True)'; then
                sleep 1
                continue
            fi
            python3 "$MANIFEST_TOOL_SNAPSHOT" update \
                --manifest "$MANIFEST_PATH" \
                --status rollback_accepted_fenced \
                --detail "rollback health passed while writes remained fenced"
            if ! python3 "$MANIFEST_TOOL_SNAPSHOT" release-fence \
                --manifest "$MANIFEST_PATH" --mode rollback; then
                python3 "$MANIFEST_TOOL_SNAPSHOT" update \
                    --manifest "$MANIFEST_PATH" \
                    --status rollback_release_failed \
                    --detail "rollback restored state is healthy but write fence remains active"
                echo "Rollback data restored, but write fence release failed" >&2
                exit 1
            fi
        fi
        python3 "$MANIFEST_TOOL_SNAPSHOT" update \
            --manifest "$MANIFEST_PATH" \
            --status rolled_back \
            --detail "failure snapshot preserved; code, database, attachments, and release restored"
        exit 0
    fi
    sleep 1
done

systemctl --user stop qr-system.service || true
python3 "$MANIFEST_TOOL_SNAPSHOT" update \
    --manifest "$MANIFEST_PATH" \
    --status rollback_failed \
    --detail "restored state did not pass health check"
trap - ERR
echo "Rollback failed: restored service did not become healthy" >&2
exit 1
