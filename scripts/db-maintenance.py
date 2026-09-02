#!/usr/bin/env python3
"""qr-system - Database Maintenance Script
Performs: integrity check, VACUUM, old data cleanup, backup.
Run via cron: 0 2 * * * /home/dubin/qr-system/scripts/db-maintenance.sh
"""
import sqlite3
import os
import logging
import json
from datetime import datetime

DB_PATH = '/home/dubin/qr-system/data/production.db'
BACKUP_DIR = '/home/dubin/qr-system/data/backups'
LOG_FILE = '/home/dubin/qr-system/logs/db_maintenance.log'
MAX_BACKUPS = 7
OLD_DATA_DAYS = 90
COMPANY_PROFILE_RETENTION_YEARS = 3

if os.path.isdir(os.path.dirname(LOG_FILE)):
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
else:
    # Keep the maintenance module importable in local verification and tests;
    # production deployments provide the configured log directory.
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
logger = logging.getLogger('db-maintenance')


def get_db_size_mb(path):
    return round(os.path.getsize(path) / (1024 * 1024), 2) if os.path.exists(path) else 0


def backup_database(source_conn):
    """Create timestamped backup."""
    os.makedirs(BACKUP_DIR, mode=0o700, exist_ok=True)
    os.chmod(BACKUP_DIR, 0o700)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(BACKUP_DIR, f'production_backup_{ts}.db')
    backup_conn = sqlite3.connect(backup_path)
    try:
        source_conn.backup(backup_conn)
    finally:
        backup_conn.close()
    os.chmod(backup_path, 0o600)
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


def check_foreign_keys(conn):
    """Abort maintenance when logical referential integrity is broken."""
    violations = conn.execute('PRAGMA foreign_key_check').fetchall()
    if violations:
        logger.error(f'Foreign-key check FAILED: {violations}')
        return False
    logger.info('Foreign-key check: PASSED')
    return True


def publish_audit_outbox(conn, limit=500):
    """Publish durable audit envelopes without deleting or mutating evidence."""

    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='audit_event_outbox'"
    ).fetchone()
    if not table:
        return {"published": 0, "failed": 0}

    audit_columns = {
        row[1] for row in conn.execute("PRAGMA table_info(audit_logs)").fetchall()
    }
    required_columns = {
        "event_id", "category", "severity", "mandatory", "schema_version",
        "redaction_version", "request_id",
    }
    if not required_columns.issubset(audit_columns):
        logger.warning("Audit outbox present but v066 audit columns are incomplete")
        return {"published": 0, "failed": 0}

    rows = conn.execute(
        "SELECT * FROM audit_event_outbox "
        "WHERE status IN ('pending','failed') "
        "AND (next_retry_at IS NULL OR next_retry_at <= datetime('now','localtime')) "
        "ORDER BY id LIMIT ?",
        (max(1, min(int(limit), 1000)),),
    ).fetchall()
    published = 0
    failed = 0
    for row in rows:
        try:
            payload = json.loads(row["payload"] or "{}")
            conn.execute(
                "INSERT OR IGNORE INTO audit_logs "
                "(event_id,user_id,action,target_type,target_id,detail,category,"
                "severity,mandatory,schema_version,redaction_version,request_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    payload["event_id"],
                    payload.get("user_id"),
                    payload["action"],
                    payload.get("target_type", ""),
                    payload.get("target_id", 0),
                    payload.get("detail", ""),
                    payload.get("category", row["category"]),
                    payload.get("severity", "info"),
                    int(payload.get("mandatory", 0)),
                    int(payload.get("schema_version", 1)),
                    int(payload.get("redaction_version", 1)),
                    payload.get("request_id", ""),
                ),
            )
            conn.execute(
                "UPDATE audit_event_outbox SET status='published', attempts=attempts+1, "
                "last_error='', published_at=datetime('now','localtime') WHERE id=?",
                (row["id"],),
            )
            published += 1
        except Exception as exc:
            conn.execute(
                "UPDATE audit_event_outbox SET status='failed', attempts=attempts+1, "
                "last_error=?, next_retry_at=datetime('now','localtime','+5 minutes') "
                "WHERE id=?",
                (str(exc)[:500], row["id"]),
            )
            failed += 1
    conn.commit()
    return {"published": published, "failed": failed}


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

    # Audit logs are evidence and must only be removed through the controlled
    # archive/approval workflow.  The generic maintenance job must never
    # delete them based on the ordinary soft-delete retention window.
    logger.info('Audit logs retained; controlled archive workflow owns cleanup')

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

    company_history_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='company_profile_revisions'"
    ).fetchone()
    if company_history_table:
        old_company_revisions = conn.execute(
            "DELETE FROM company_profile_revisions "
            "WHERE profile_id=1 "
            "AND created_at < datetime('now','localtime',?) "
            "AND version <> (SELECT version FROM company_profiles WHERE id=1)",
            (f'-{COMPANY_PROFILE_RETENTION_YEARS} years',),
        )
        if old_company_revisions.rowcount > 0:
            logger.info(
                f'Cleaned {old_company_revisions.rowcount} expired company profile revisions'
            )

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
        backup_database(conn)
        
        # Step 2: Integrity check
        if not check_integrity(conn):
            logger.critical('Integrity check failed - aborting maintenance!')
            conn.close()
            return 1

        if not check_foreign_keys(conn):
            logger.critical('Foreign-key check failed - aborting maintenance!')
            conn.close()
            return 1

        outbox_result = publish_audit_outbox(conn)
        logger.info(
            'Audit outbox: published=%s failed=%s',
            outbox_result['published'],
            outbox_result['failed'],
        )
        
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
