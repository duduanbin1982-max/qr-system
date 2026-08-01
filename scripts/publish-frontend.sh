#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATIC_DIR="$PROJECT_ROOT/public/static"
RETENTION_DAYS="${STATIC_ASSET_RETENTION_DAYS:-7}"
STAGING_DIR="$(mktemp -d "$PROJECT_ROOT/data/frontend-build.XXXXXX")"

cleanup() {
    rm -rf "$STAGING_DIR"
}
trap cleanup EXIT

cd "$PROJECT_ROOT"
npm run build -- --outDir "$STAGING_DIR" --emptyOutDir
test -s "$STAGING_DIR/index.html"

install -d -m 0755 "$STATIC_DIR"
shopt -s dotglob nullglob
for source in "$STAGING_DIR"/*; do
    name="$(basename "$source")"
    [[ "$name" == 'index.html' ]] && continue
    if [[ -d "$source" ]]; then
        install -d -m 0755 "$STATIC_DIR/$name"
        cp -a "$source"/. "$STATIC_DIR/$name"/
    else
        install -m 0644 "$source" "$STATIC_DIR/$name"
    fi
done

# Assets are in place before the entry document changes. The rename is atomic.
install -m 0644 "$STAGING_DIR/index.html" "$STATIC_DIR/.index.html.new"
mv -f "$STATIC_DIR/.index.html.new" "$STATIC_DIR/index.html"

# Nginx caches hashed assets for one day. Seven days covers stale clients safely.
if [[ -d "$STATIC_DIR/assets" ]]; then
    find "$STATIC_DIR/assets" -type f -mtime "+$RETENTION_DAYS" -delete
fi

echo "Frontend published atomically; old hashed assets retained for $RETENTION_DAYS days"
