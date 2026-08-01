#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

DB_PATH=/home/dubin/qr-system/data/production.db
BACKUP_DIR=/home/dubin/qr-system/data/backups
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/production_${TIMESTAMP}.db"
TEMP_FILE="$BACKUP_FILE.partial"

install -d -m 0700 "$BACKUP_DIR"
trap 'rm -f "$TEMP_FILE"' EXIT

sqlite3 "$DB_PATH" ".backup '$TEMP_FILE'"

if [ "$(sqlite3 "$TEMP_FILE" 'PRAGMA quick_check;')" != 'ok' ]; then
    echo "Backup integrity check failed: $TEMP_FILE" >&2
    exit 1
fi

FOREIGN_KEY_ERRORS=$(sqlite3 "$TEMP_FILE" 'PRAGMA foreign_key_check;')
if [ -n "$FOREIGN_KEY_ERRORS" ]; then
    echo "Backup foreign-key check failed:" >&2
    printf '%s\n' "$FOREIGN_KEY_ERRORS" >&2
    exit 1
fi

mv "$TEMP_FILE" "$BACKUP_FILE"
chmod 0600 "$BACKUP_FILE"
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'production_*.db' -mtime +30 -delete
echo "Backup OK: $BACKUP_FILE"
