#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="${QR_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
MANIFEST_PATH="${1:?deployment manifest path is required}"
DB_PATH="${DB_PATH:-$PROJECT_ROOT/data/production.db}"
HEALTH_URL="${HEALTH_URL:-https://127.0.0.1/api/health}"
UNIT_SOURCE="$PROJECT_ROOT/deploy/qr-system.service"
UNIT_TARGET="$HOME/.config/systemd/user/qr-system.service"

record_rollback_failure() {
    local exit_code=$?
    local failed_line="${BASH_LINENO[0]:-unknown}"
    trap - ERR
    set +e
    python3 "$PROJECT_ROOT/scripts/deployment_manifest.py" update \
        --manifest "$MANIFEST_PATH" \
        --status rollback_failed \
        --detail "rollback failed at line $failed_line with exit $exit_code"
    echo "Rollback failed at line $failed_line" >&2
    exit "$exit_code"
}

trap record_rollback_failure ERR

field() {
    python3 "$PROJECT_ROOT/scripts/deployment_manifest.py" field \
        --manifest "$MANIFEST_PATH" --path "$1"
}

before_commit="$(field before_commit)"
if [[ ! "$before_commit" =~ ^[0-9a-f]{40}$ ]]; then
    echo "Invalid rollback commit in deployment manifest" >&2
    exit 1
fi

systemctl --user stop qr-system.service || true
python3 "$PROJECT_ROOT/scripts/deployment_manifest.py" restore \
    --manifest "$MANIFEST_PATH" \
    --database "$DB_PATH" \
    --project-root "$PROJECT_ROOT"

git -C "$PROJECT_ROOT" cat-file -e "$before_commit^{commit}"
git -C "$PROJECT_ROOT" switch --detach "$before_commit"
printf '%s\n' "$before_commit" > "$PROJECT_ROOT/.deployed_commit.tmp.$$"
mv -f "$PROJECT_ROOT/.deployed_commit.tmp.$$" "$PROJECT_ROOT/.deployed_commit"

install -D -m 0644 "$UNIT_SOURCE" "$UNIT_TARGET"
systemctl --user daemon-reload
systemctl --user start qr-system.service

for _ in {1..20}; do
    if curl -ksSf --max-time 5 "$HEALTH_URL" 2>/dev/null | grep -q '"status":"ok"'; then
        python3 "$PROJECT_ROOT/scripts/deployment_manifest.py" update \
            --manifest "$MANIFEST_PATH" \
            --status rolled_back \
            --detail "code, database, and attachments restored"
        exit 0
    fi
    sleep 1
done

python3 "$PROJECT_ROOT/scripts/deployment_manifest.py" update \
    --manifest "$MANIFEST_PATH" \
    --status rollback_failed \
    --detail "restored state did not pass health check"
trap - ERR
echo "Rollback failed: restored service did not become healthy" >&2
exit 1
