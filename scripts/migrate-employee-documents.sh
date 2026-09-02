#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

QR_PROJECT_ROOT="${QR_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SOURCE_DIR="$QR_PROJECT_ROOT/uploads/employee_docs"
TARGET_DIR="$QR_PROJECT_ROOT/data/attachments/employee_docs"

secure_chmod() {
    local mode="$1"
    local target="$2"
    if chmod "$mode" "$target" 2>/dev/null; then
        return
    fi
    case "$(uname -s)" in
        MINGW*|MSYS*) return ;;
    esac
    echo "Cannot set mode $mode on $target" >&2
    return 1
}

if [[ ! -d "$SOURCE_DIR" ]]; then
    echo "No legacy employee document directory found"
    exit 0
fi

mkdir -p "$TARGET_DIR"
secure_chmod 0700 "$TARGET_DIR"
copied=0
existing=0
partial_file=""
cleanup() {
    [[ -z "$partial_file" ]] || rm -f "$partial_file"
}
trap cleanup EXIT
while IFS= read -r -d '' source_file; do
    filename="$(basename "$source_file")"
    target_file="$TARGET_DIR/$filename"
    if [[ -e "$target_file" ]]; then
        if ! cmp -s "$source_file" "$target_file"; then
            echo "Employee document migration conflict: $filename" >&2
            exit 1
        fi
        existing=$((existing + 1))
        continue
    fi
    partial_file="$TARGET_DIR/.${filename}.partial.$$"
    cp -- "$source_file" "$partial_file"
    secure_chmod 0600 "$partial_file"
    mv "$partial_file" "$target_file"
    partial_file=""
    copied=$((copied + 1))
done < <(find "$SOURCE_DIR" -maxdepth 1 -type f -print0)

echo "Employee document migration complete: copied=$copied existing=$existing"
