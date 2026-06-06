#!/bin/bash
# ============================================================
# qr-system 数据库自动备份脚本
# 用法: ./backup-db.sh
# cron: 0 3 * * * /home/dubin/qr-system/scripts/backup-db.sh
# ============================================================
DB_PATH="/home/dubin/qr-system/data/production.db"
BACKUP_DIR="/home/dubin/qr-system/data/backups"
KEEP_DAYS=30

mkdir -p "$BACKUP_DIR"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
WEEKDAY=$(date +%u)
BACKUP_FILE="$BACKUP_DIR/production_${TIMESTAMP}.db"

# 备份（使用 sqlite3 .backup 保证一致性）
sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"

if [ $? -eq 0 ] && [ -f "$BACKUP_FILE" ]; then
    SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    # 每日备份保留 30 天，每周日保留一份周备份
    if [ "$WEEKDAY" = "7" ]; then
        cp "$BACKUP_FILE" "$BACKUP_DIR/weekly_${TIMESTAMP}.db"
    fi
    # 清理旧备份
    find "$BACKUP_DIR" -name "production_*.db" -mtime +$KEEP_DAYS -delete 2>/dev/null
    find "$BACKUP_DIR" -name "weekly_*.db" -mtime +90 -delete 2>/dev/null
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup OK: $BACKUP_FILE ($SIZE)"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup FAILED"
    exit 1
fi
