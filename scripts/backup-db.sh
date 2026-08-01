#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
# QR System DB Backup with integrity verification
# cron: 0 3 * * * /home/dubin/qr-system/scripts/backup-db.sh >> /home/dubin/qr-system/data/backups/backup.log 2>&1

DB_PATH="/home/dubin/qr-system/data/production.db"
ATTACH_DIR="/home/dubin/qr-system/data/attachments"
BACKUP_DIR="/home/dubin/qr-system/data/backups"
KEEP_DAYS=30
LOG_TAG="[$(date '+%Y-%m-%d %H:%M:%S')]"

install -d -m 0700 "$BACKUP_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
WEEKDAY=$(date +%u)
BACKUP_FILE="$BACKUP_DIR/production_${TIMESTAMP}.db"
TEMP_FILE="$BACKUP_FILE.partial"
trap 'rm -f "$TEMP_FILE"' EXIT

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

mv "$TEMP_FILE" "$BACKUP_FILE"
chmod 0600 "$BACKUP_FILE"
SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "$LOG_TAG BACKUP OK: $BACKUP_FILE ($SIZE, $TABLE_COUNT tables)"

if [ "$WEEKDAY" = "7" ]; then
    install -m 0600 "$BACKUP_FILE" "$BACKUP_DIR/weekly_${TIMESTAMP}.db"
    echo "$LOG_TAG Weekly archive saved"
fi

if [ -d "$ATTACH_DIR" ] && [ "$(ls -A $ATTACH_DIR 2>/dev/null)" ]; then
    ATTACH_BACKUP="$BACKUP_DIR/attachments_${TIMESTAMP}.tar.gz"
    tar -czf "$ATTACH_BACKUP" -C "$(dirname $ATTACH_DIR)" "$(basename $ATTACH_DIR)" 2>/dev/null
    chmod 0600 "$ATTACH_BACKUP"
    echo "$LOG_TAG Attachments backup: $ATTACH_BACKUP"
fi

find "$BACKUP_DIR" -name "production_*.db" -mtime +$KEEP_DAYS -delete 2>/dev/null
find "$BACKUP_DIR" -name "attachments_*.tar.gz" -mtime +$KEEP_DAYS -delete 2>/dev/null
find "$BACKUP_DIR" -name "weekly_*.db" -mtime +90 -delete 2>/dev/null

# Restore verification: test the backup can be opened
RESTORE_TEST=$(/usr/bin/sqlite3 "$BACKUP_FILE" "SELECT COUNT(*) FROM users" 2>&1)
if [ -z "$RESTORE_TEST" ] || [ "$RESTORE_TEST" -lt 1 ] 2>/dev/null; then
    echo "$LOG_TAG WARNING: restore test returned unexpected result: $RESTORE_TEST"
fi
