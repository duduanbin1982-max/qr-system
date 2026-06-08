#!/usr/bin/env python3
"""qr-system - Database Maintenance Script
Performs: integrity check, VACUUM, old data cleanup, backup.
Run via cron: 0 2 * * * /home/dubin/qr-system/scripts/db-maintenance.sh
"""
import sqlite3
import os
import shutil
import logging
from datetime import datetime

DB_PATH = '/home/dubin/qr-system/data/production.db'
BACKUP_DIR = '/home/dubin/qr-system/data/backups'
LOG_FILE = '/home/dubin/qr-system/logs/db_maintenance.log'
MAX_BACKUPS = 7
OLD_DATA_DAYS = 90

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger('db-maintenance')


def get_db_size_mb(path):
    return round(os.path.getsize(path) / (1024 * 1024), 2) if os.path.exists(path) else 0


def backup_database():
    """Create timestamped backup."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(BACKUP_DIR, f'production_backup_{ts}.db')
    shutil.copy2(DB_PATH, backup_path)
    logger.info(f'Backup created: {backup_path} ({get_db_size_mb(backup_path)}MB)')


def rotate_backups():
    """Keep only the most recent MAX_BACKUPS backups."""
    backups = sorted([
        f for f in os.listdir(BACKUP_DIR) if f.startswith('production_backup_')
    ])
    while len(backups) > MAX_BACKUPS:
        oldest = backups.pop(0)
        os.remove(os.path.join(BACKUP_DIR, oldest))
        logger.info(f'Removed old backup: {oldest}')


def check_integrity(conn):
    """Run PRAGMA integrity_check."""
    result = conn.execute('PRAGMA integrity_check').fetchone()
    if result[0] == 'ok':
        logger.info('Integrity check: PASSED')
        return True
    else:
        logger.error(f'Integrity check FAILED: {result[0]}')
        return False


def vacuum_database(conn):
    """Reclaim unused space."""
    size_before = get_db_size_mb(DB_PATH)
    conn.execute('VACUUM')
    size_after = get_db_size_mb(DB_PATH)
    saved = round(size_before - size_after, 2)
    logger.info(f'VACUUM: {size_before}MB -> {size_after}MB (saved {saved}MB)')


def clean_old_data(conn):
    """Clean up soft-deleted records older than OLD_DATA_DAYS."""
    total_deleted = 0
    
    # Clean old soft-deleted orders
    old_orders = conn.execute(f"""
        SELECT id FROM orders 
        WHERE deleted_at IS NOT NULL 
        AND deleted_at < datetime('now','localtime','-{OLD_DATA_DAYS} days')
    """).fetchall()
    
    for (oid,) in old_orders:
        for tbl in ['work_records', 'scrap_records', 'rework_records',
                     'quality_inspections', 'material_consumptions',
                     'order_processes', 'product_items', 'order_attachments']:
            conn.execute(f'DELETE FROM {tbl} WHERE order_id = ?', (oid,))
        conn.execute('DELETE FROM orders WHERE id = ?', (oid,))
        total_deleted += 1
    
    if total_deleted > 0:
        logger.info(f'Cleaned {total_deleted} old soft-deleted orders')

    # Clean old audit logs
    old_logs = conn.execute(f"""
        DELETE FROM audit_logs 
        WHERE created_at < datetime('now','localtime','-{OLD_DATA_DAYS} days')
    """)
    if old_logs.rowcount > 0:
        logger.info(f'Cleaned {old_logs.rowcount} old audit log entries')

    # Clean old login logs
    old_login = conn.execute(f"""
        DELETE FROM login_logs 
        WHERE created_at < datetime('now','localtime','-{OLD_DATA_DAYS} days')
    """)
    if old_login.rowcount > 0:
        logger.info(f'Cleaned {old_login.rowcount} old login log entries')

    # Clean old login attempts
    old_attempts = conn.execute(f"""
        DELETE FROM login_attempts 
        WHERE created_at < datetime('now','localtime','-1 days')
    """)
    if old_attempts.rowcount > 0:
        logger.info(f'Cleaned {old_attempts.rowcount} old login attempts')

    conn.commit()


def get_table_stats(conn):
    """Log table row counts."""
    tables = ['orders', 'work_records', 'users', 'products', 'audit_logs',
              'quality_inspections', 'notifications', 'product_items']
    stats = []
    for tbl in tables:
        try:
            count = conn.execute(f'SELECT COUNT(*) FROM {tbl}').fetchone()[0]
            stats.append(f'{tbl}={count}')
        except Exception:
            pass
    logger.info('Table stats: ' + ', '.join(stats))


def main():
    logger.info('=== DB Maintenance Started ===')
    start_size = get_db_size_mb(DB_PATH)
    logger.info(f'DB size before: {start_size}MB')
    
    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA journal_mode=WAL')
    
    try:
        # Step 1: Backup
        backup_database()
        
        # Step 2: Integrity check
        if not check_integrity(conn):
            logger.critical('Integrity check failed - aborting maintenance!')
            conn.close()
            return 1
        
        # Step 3: Clean old data
        clean_old_data(conn)
        
        # Step 4: VACUUM
        vacuum_database(conn)
        
        # Step 5: Table stats
        get_table_stats(conn)
        
        # Step 6: Rotate old backups
        rotate_backups()
        
    except Exception as e:
        logger.error(f'Maintenance failed: {e}', exc_info=True)
        return 1
    finally:
        conn.close()
    
    end_size = get_db_size_mb(DB_PATH)
    logger.info(f'DB size after: {end_size}MB')
    logger.info('=== DB Maintenance Completed ===')
    return 0


if __name__ == '__main__':
    exit(main())
