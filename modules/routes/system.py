"""
qr-system - Admin Backup & System Health Routes
"""
import os, shutil, io, zipfile, time
from datetime import datetime
from flask import request, jsonify, send_file, g
from modules.app import app
from modules.db import get_db
from modules.config import DATA_DIR
from modules.middleware.auth import check_auth, check_permission, audit_log


@app.route('/api/system/health', methods=['GET'])
def system_health():
    """Enhanced health check with disk, memory, and DB stats."""
    db = get_db()
    db_ok = False
    db_size = 0
    try:
        db.execute('SELECT 1')
        db_ok = True
    except Exception:
        pass

    # DB file size
    db_path = os.path.join(DATA_DIR, 'production.db')
    if os.path.exists(db_path):
        db_size = round(os.path.getsize(db_path) / (1024 * 1024), 2)

    # Disk space
    try:
        stat = os.statvfs(DATA_DIR)
        disk_free_gb = round((stat.f_frsize * stat.f_bavail) / (1024**3), 2)
        disk_total_gb = round((stat.f_frsize * stat.f_blocks) / (1024**3), 2)
        disk_used_pct = round((1 - stat.f_bavail / stat.f_blocks) * 100, 1) if stat.f_blocks > 0 else 0
    except Exception:
        disk_free_gb = 0
        disk_total_gb = 0
        disk_used_pct = 0

    # Row counts
    try:
        tables = {}
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
            try:
                cnt = db.execute(f'SELECT COUNT(*) FROM "{row["name"]}"').fetchone()[0]
                tables[row['name']] = cnt
            except Exception:
                tables[row['name']] = -1
    except Exception:
        tables = {}

    return jsonify({
        'status': 'ok' if db_ok else 'degraded',
        'db': 'connected' if db_ok else 'disconnected',
        'db_size_mb': db_size,
        'version': '2.0',
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'uptime_seconds': round(time.time() - app.config.get('START_TIME', time.time()), 0),
        'disk': {
            'free_gb': disk_free_gb,
            'total_gb': disk_total_gb,
            'used_pct': disk_used_pct,
        },
        'table_counts': tables,
    })


@app.route('/api/system/backup', methods=['POST'])
@check_auth
@check_permission('settings:manage')
def create_backup():
    """Create and download a full backup (DB + attachments as ZIP)."""
    db_path = os.path.join(DATA_DIR, 'production.db')
    attach_dir = os.path.join(DATA_DIR, 'attachments')
    backup_dir = os.path.join(DATA_DIR, 'backups')
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    zip_name = f'qr_backup_{timestamp}.zip'

    # Create ZIP in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        # Add DB file
        if os.path.exists(db_path):
            # VACUUM first to compact
            try:
                db = get_db()
                db.execute('VACUUM')
            except Exception:
                pass
            zf.write(db_path, 'production.db')

        # Add attachments
        if os.path.exists(attach_dir):
            for root, dirs, files in os.walk(attach_dir):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    arcname = os.path.join('attachments', os.path.relpath(fpath, attach_dir))
                    zf.write(fpath, arcname)

        # Add metadata
        meta = f'Backup created: {timestamp}\nSystem: QR Production System v2.0\n'
        zf.writestr('backup_info.txt', meta)

    buf.seek(0)
    audit_log('system_backup', detail=f'backup_{timestamp}.zip')
    return send_file(
        buf,
        mimetype='application/zip',
        as_attachment=True,
        download_name=zip_name,
    )


@app.route('/api/system/check-integrity', methods=['POST'])
@check_auth
@check_permission('settings:manage')
def check_integrity():
    """Run DB integrity check and report orphaned records."""
    db = get_db()
    results = []

    # SQLite integrity check
    try:
        ok = db.execute('PRAGMA integrity_check').fetchone()
        results.append({'check': 'sqlite_integrity', 'pass': ok[0] == 'ok', 'detail': ok[0]})
    except Exception as e:
        results.append({'check': 'sqlite_integrity', 'pass': False, 'detail': str(e)})

    # Check orphans
    checks = [
        ('order_processes → orders', "SELECT COUNT(*) FROM order_processes op LEFT JOIN orders o ON op.order_id = o.id WHERE o.id IS NULL"),
        ('work_records → orders', "SELECT COUNT(*) FROM work_records wr LEFT JOIN orders o ON wr.order_id = o.id WHERE o.id IS NULL"),
        ('work_records → users', "SELECT COUNT(*) FROM work_records wr LEFT JOIN users u ON wr.user_id = u.id WHERE u.id IS NULL"),
        ('user_roles → users', "SELECT COUNT(*) FROM user_roles ur LEFT JOIN users u ON ur.user_id = u.id WHERE u.id IS NULL"),
        ('order_attachments → orders', "SELECT COUNT(*) FROM order_attachments oa LEFT JOIN orders o ON oa.order_id = o.id WHERE o.id IS NULL"),
        ('inventory → products', "SELECT COUNT(*) FROM inventory i LEFT JOIN products p ON i.product_model = p.model WHERE p.id IS NULL AND i.product_model != ''"),
    ]

    all_clean = True
    for label, sql in checks:
        try:
            cnt = db.execute(sql).fetchone()[0]
            ok = cnt == 0
            results.append({'check': label, 'pass': ok, 'orphans': cnt})
            if not ok:
                all_clean = False
        except Exception as e:
            results.append({'check': label, 'pass': False, 'detail': str(e)})
            all_clean = False

    audit_log('integrity_check', detail=f'clean={all_clean}')
    return jsonify({
        'all_clean': all_clean,
        'checks': results,
    })