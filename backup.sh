#!/bin/bash
# Database backup script
BACKUP_DIR=/home/dubin/qr-system/backups
mkdir -p $BACKUP_DIR
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
sqlite3 /home/dubin/qr-system/data/production.db .dump | gzip > $BACKUP_DIR/db_$TIMESTAMP.sql.gz
# Keep only last 30 days
find $BACKUP_DIR -name 'db_*.sql.gz' -mtime +30 -delete
echo [$TIMESTAMP] Backup complete: $(ls -lh $BACKUP_DIR/db_$TIMESTAMP.sql.gz | awk {print $5})
