#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
E2E_PUBLIC_DIR="$(mktemp -d "$PROJECT_ROOT/data/e2e-public.XXXXXX")"

cleanup() {
    rm -rf "$E2E_PUBLIC_DIR"
}
trap cleanup EXIT

cd "$PROJECT_ROOT"
cp -a "$PROJECT_ROOT/public"/. "$E2E_PUBLIC_DIR"/
rm -rf "$E2E_PUBLIC_DIR/static"
npm run build -- --outDir "$E2E_PUBLIC_DIR/static" --emptyOutDir
test -s "$E2E_PUBLIC_DIR/static/index.html"

export PUBLIC_DIR="$E2E_PUBLIC_DIR"
bash scripts/run-playwright.sh "$@"
