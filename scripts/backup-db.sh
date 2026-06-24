#!/bin/bash
# QR System DB Backup with integrity verification
# cron: 0 3 * * * /home/dubin/qr-system/scripts/backup-db.sh >> /home/dubin/qr-system/data/backups/backup.log 2>&1

DB_PATH="/home/dubin/qr-system/data/production.db"
ATTACH_DIR="/home/dubin/qr-system/data/attachments"
BACKUP_DIR="/home/dubin/qr-system/data/backups"
KEEP_DAYS=30
LOG_TAG="[$(date '+%Y-%m-%d %H:%M:%S')]"

mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
WEEKDAY=$(date +%u)
BACKUP_FILE="$BACKUP_DIR/production_${TIMESTAMP}.db"

/usr/bin/sqlite3 "$DB_PATH" ".backup $BACKUP_FILE" 2>&1
if [ $? -ne 0 ] || [ ! -f "$BACKUP_FILE" ]; then
    echo "$LOG_TAG BACKUP FAILED"
    exit 1
fi

INTEGRITY=$(/usr/bin/sqlite3 "$BACKUP_FILE" "PRAGMA integrity_check" 2>&1)
if [ "$INTEGRITY" != "ok" ]; then
    echo "$LOG_TAG BACKUP CORRUPT: $INTEGRITY"
    rm -f "$BACKUP_FILE"
    exit 1
fi

TABLE_COUNT=$(/usr/bin/sqlite3 "$BACKUP_FILE" "SELECT COUNT(*) FROM sqlite_master WHERE type='table'" 2>&1)
if [ "$TABLE_COUNT" -lt 10 ]; then
    echo "$LOG_TAG BACKUP SUSPICIOUS: $TABLE_COUNT tables"
    rm -f "$BACKUP_FILE"
    exit 1
fi

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo "$LOG_TAG BACKUP OK: $BACKUP_FILE ($SIZE, $TABLE_COUNT tables)"

if [ "$WEEKDAY" = "7" ]; then
    cp "$BACKUP_FILE" "$BACKUP_DIR/weekly_${TIMESTAMP}.db"
    echo "$LOG_TAG Weekly archive saved"
fi

if [ -d "$ATTACH_DIR" ] && [ "$(ls -A $ATTACH_DIR 2>/dev/null)" ]; then
    ATTACH_BACKUP="$BACKUP_DIR/attachments_${TIMESTAMP}.tar.gz"
    tar -czf "$ATTACH_BACKUP" -C "$(dirname $ATTACH_DIR)" "$(basename $ATTACH_DIR)" 2>/dev/null
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