#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
# QR System DB Backup with integrity verification
# cron: 0 3 * * * /home/dubin/qr-system/scripts/backup-db.sh >> /home/dubin/qr-system/data/backups/backup.log 2>&1

QR_PROJECT_ROOT="${QR_PROJECT_ROOT:-/home/dubin/qr-system}"
DB_PATH="${DB_PATH:-$QR_PROJECT_ROOT/data/production.db}"
ATTACH_DIR="$QR_PROJECT_ROOT/data/attachments"
LEGACY_ATTACH_DIR="$QR_PROJECT_ROOT/uploads/employee_docs"
BACKUP_DIR="${BACKUP_DIR:-$QR_PROJECT_ROOT/data/backups}"
KEEP_DAYS=30
PRESERVE_EXISTING_BACKUPS="${PRESERVE_EXISTING_BACKUPS:-0}"
if [[ "$PRESERVE_EXISTING_BACKUPS" != "0" && "$PRESERVE_EXISTING_BACKUPS" != "1" ]]; then
    echo "PRESERVE_EXISTING_BACKUPS must be 0 or 1" >&2
    exit 2
fi
LOG_TAG="[$(date '+%Y-%m-%d %H:%M:%S')]"

if [[ -L "$BACKUP_DIR" || -L "$QR_PROJECT_ROOT/data" ]]; then
    echo "Backup refused: data or backup directory cannot be a symlink" >&2
    exit 1
fi
install -d -m 0700 "$BACKUP_DIR"
TIMESTAMP="${BACKUP_TIMESTAMP:-$(date +%Y%m%d_%H%M%S)}"
if [[ ! "$TIMESTAMP" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "$LOG_TAG invalid BACKUP_TIMESTAMP" >&2
    exit 2
fi
WEEKDAY=$(date +%u)
BACKUP_FILE="$BACKUP_DIR/production_${TIMESTAMP}.db"
TEMP_FILE="$BACKUP_FILE.partial.$$"
ATTACH_BACKUP="$BACKUP_DIR/attachments_${TIMESTAMP}.tar.gz"
ATTACH_TEMP="$ATTACH_BACKUP.partial.$$"
ATTACH_CHECKSUM="$ATTACH_BACKUP.sha256"
ATTACH_CHECKSUM_TEMP="$ATTACH_CHECKSUM.partial.$$"
BACKUP_METADATA_FILE="${BACKUP_METADATA_FILE:-$BACKUP_DIR/backup_${TIMESTAMP}.json}"
WEEKLY_BACKUP_FILE="$BACKUP_DIR/weekly_${TIMESTAMP}.db"
for output_path in \
    "$BACKUP_FILE" "$TEMP_FILE" "$ATTACH_BACKUP" "$ATTACH_TEMP" \
    "$ATTACH_CHECKSUM" "$ATTACH_CHECKSUM_TEMP" "$BACKUP_METADATA_FILE"; do
    if [[ -e "$output_path" || -L "$output_path" ]]; then
        echo "$LOG_TAG refusing to overwrite existing backup evidence: $output_path" >&2
        exit 1
    fi
done
WEEKLY_TEMP="$WEEKLY_BACKUP_FILE.partial.$$"
if [ "$WEEKDAY" = "7" ] && [[ -e "$WEEKLY_BACKUP_FILE" || -L "$WEEKLY_BACKUP_FILE" || -e "$WEEKLY_TEMP" || -L "$WEEKLY_TEMP" ]]; then
    echo "$LOG_TAG refusing to overwrite existing weekly backup: $WEEKLY_BACKUP_FILE" >&2
    exit 1
fi
trap 'rm -f "$TEMP_FILE" "$ATTACH_TEMP" "$ATTACH_CHECKSUM_TEMP" "$WEEKLY_TEMP"' EXIT

/usr/bin/sqlite3 "$DB_PATH" ".backup $TEMP_FILE" 2>&1
if [ ! -f "$TEMP_FILE" ]; then
    echo "$LOG_TAG BACKUP FAILED"
    exit 1
fi

INTEGRITY=$(/usr/bin/sqlite3 "$TEMP_FILE" "PRAGMA integrity_check" 2>&1)
if [ "$INTEGRITY" != "ok" ]; then
    echo "$LOG_TAG BACKUP CORRUPT: $INTEGRITY"
    exit 1
fi

FOREIGN_KEY_ERRORS=$(/usr/bin/sqlite3 "$TEMP_FILE" "PRAGMA foreign_key_check" 2>&1)
if [ -n "$FOREIGN_KEY_ERRORS" ]; then
    echo "$LOG_TAG BACKUP FOREIGN-KEY CHECK FAILED: $FOREIGN_KEY_ERRORS"
    exit 1
fi

TABLE_COUNT=$(/usr/bin/sqlite3 "$TEMP_FILE" "SELECT COUNT(*) FROM sqlite_master WHERE type='table'" 2>&1)
if [ "$TABLE_COUNT" -lt 10 ]; then
    echo "$LOG_TAG BACKUP SUSPICIOUS: $TABLE_COUNT tables"
    exit 1
fi

# A same-directory hard link is an atomic no-clobber publish. `mv` could
# overwrite a concurrently-created evidence file after the initial check.
ln "$TEMP_FILE" "$BACKUP_FILE"
rm -f "$TEMP_FILE"
chmod 0600 "$BACKUP_FILE"
SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "$LOG_TAG BACKUP OK: $BACKUP_FILE ($SIZE, $TABLE_COUNT tables)"

if [ "$WEEKDAY" = "7" ]; then
    ln "$BACKUP_FILE" "$WEEKLY_BACKUP_FILE"
    chmod 0600 "$WEEKLY_BACKUP_FILE"
    echo "$LOG_TAG Weekly archive saved"
fi

attachment_paths=()
if [ -d "$ATTACH_DIR" ] && [ "$(ls -A "$ATTACH_DIR" 2>/dev/null)" ]; then
    attachment_paths+=("data/attachments")
fi
if [ -d "$LEGACY_ATTACH_DIR" ] && [ "$(ls -A "$LEGACY_ATTACH_DIR" 2>/dev/null)" ]; then
    attachment_paths+=("uploads/employee_docs")
fi
if [ "${#attachment_paths[@]}" -gt 0 ]; then
    tar -czf "$ATTACH_TEMP" -C "$QR_PROJECT_ROOT" "${attachment_paths[@]}" 2>/dev/null
else
    tar -czf "$ATTACH_TEMP" --files-from /dev/null
fi
tar -tzf "$ATTACH_TEMP" >/dev/null
ln "$ATTACH_TEMP" "$ATTACH_BACKUP"
rm -f "$ATTACH_TEMP"
chmod 0600 "$ATTACH_BACKUP"
sha256sum "$ATTACH_BACKUP" > "$ATTACH_CHECKSUM_TEMP"
ln "$ATTACH_CHECKSUM_TEMP" "$ATTACH_CHECKSUM"
rm -f "$ATTACH_CHECKSUM_TEMP"
chmod 0600 "$ATTACH_CHECKSUM"
echo "$LOG_TAG Attachments backup: $ATTACH_BACKUP"

if [[ "$PRESERVE_EXISTING_BACKUPS" == "0" ]]; then
    find "$BACKUP_DIR" -name "production_*.db" -mtime +$KEEP_DAYS -delete 2>/dev/null
    find "$BACKUP_DIR" -name "attachments_*.tar.gz" -mtime +$KEEP_DAYS -delete 2>/dev/null
    find "$BACKUP_DIR" -name "attachments_*.tar.gz.sha256" -mtime +$KEEP_DAYS -delete 2>/dev/null
    find "$BACKUP_DIR" -name "weekly_*.db" -mtime +90 -delete 2>/dev/null
    find "$BACKUP_DIR" -name "backup_*.json" -mtime +$KEEP_DAYS -delete 2>/dev/null
else
    echo "$LOG_TAG backup retention cleanup skipped; existing evidence preserved"
fi

# Restore verification: test the backup can be opened
RESTORE_TEST=$(/usr/bin/sqlite3 "$BACKUP_FILE" "SELECT COUNT(*) FROM users" 2>&1)
if [ -z "$RESTORE_TEST" ] || [ "$RESTORE_TEST" -lt 1 ] 2>/dev/null; then
    echo "$LOG_TAG RESTORE TEST FAILED: $RESTORE_TEST" >&2
    exit 1
fi

metadata_args=(
    backup
    --output "$BACKUP_METADATA_FILE"
    --database "$BACKUP_FILE"
    --attachments "$ATTACH_BACKUP"
)
for attachment_path in "${attachment_paths[@]}"; do
    metadata_args+=(--attachment-root "$attachment_path")
done
python3 "$QR_PROJECT_ROOT/scripts/deployment_manifest.py" "${metadata_args[@]}"
python3 "$QR_PROJECT_ROOT/scripts/deployment_manifest.py" verify-backup \
    --metadata "$BACKUP_METADATA_FILE"
echo "BACKUP_METADATA=$BACKUP_METADATA_FILE"
