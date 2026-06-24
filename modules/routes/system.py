"""qr-system - Admin Backup & System Health Routes (Refactored)"""
import os, io, zipfile, time
from datetime import datetime
from flask import request, jsonify, send_file
from modules.app import app
from modules.config import DATA_DIR, DB_PATH
from modules.middleware.audit import audit_log
from modules.middleware.auth import check_auth, check_permission
from modules.services.system_service import SystemService


@app.route('/api/system/health', methods=['GET'])
def system_health():
    db_ok = False
    db_size = 0
    try:
        SystemService.ping()
        db_ok = True
    except Exception:
        pass

    if os.path.exists(DB_PATH):
        db_size = round(os.path.getsize(DB_PATH) / (1024 * 1024), 2)

    try:
        stat = os.statvfs(DATA_DIR)
        disk_free_gb = round((stat.f_frsize * stat.f_bavail) / (1024**3), 2)
        disk_total_gb = round((stat.f_frsize * stat.f_blocks) / (1024**3), 2)
        disk_used_pct = round((1 - stat.f_bavail / stat.f_blocks) * 100, 1) if stat.f_blocks > 0 else 0
    except Exception:
        disk_free_gb = disk_total_gb = disk_used_pct = 0

    tables = SystemService.get_db_stats() if db_ok else {}

    return jsonify({
        'status': 'ok' if db_ok else 'degraded',
        'db': 'connected' if db_ok else 'disconnected',
        'db_size_mb': db_size,
        'version': '2.0',
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'uptime_seconds': round(time.time() - app.config.get('START_TIME', time.time()), 0),
        'disk': {'free_gb': disk_free_gb, 'total_gb': disk_total_gb, 'used_pct': disk_used_pct},
        'table_counts': tables,
    })


@app.route('/api/system/backup', methods=['POST'])
@check_auth
@check_permission('settings:manage')
def create_backup():
    attach_dir = os.path.join(DATA_DIR, 'attachments')
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    zip_name = f'qr_backup_{timestamp}.zip'

    try:
        SystemService.vacuum()
    except Exception:
        pass

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        if os.path.exists(DB_PATH):
            zf.write(DB_PATH, os.path.basename(DB_PATH))
        if os.path.exists(attach_dir):
            for root, dirs, files in os.walk(attach_dir):
                for fname in files:
                    fpath = os.path.join(root, fname)
                    arcname = os.path.join('attachments', os.path.relpath(fpath, attach_dir))
                    zf.write(fpath, arcname)
        zf.writestr('backup_info.txt', f'Backup created: {timestamp}\nSystem: QR Production System v2.0\n')

    buf.seek(0)
    audit_log('system_backup', detail=f'backup_{timestamp}.zip')
    return send_file(buf, mimetype='application/zip', as_attachment=True, download_name=zip_name)


@app.route('/api/system/check-integrity', methods=['POST'])
@check_auth
@check_permission('settings:manage')
def check_integrity():
    results = []

    integrity = SystemService.check_integrity()
    results.append({'check': 'sqlite_integrity', 'pass': integrity[0] == 'ok', 'detail': integrity[0]})

    orphan_result = SystemService.check_orphans()
    results.extend(orphan_result['checks'])
    all_clean = orphan_result['all_clean']

    audit_log('integrity_check', detail=f'clean={all_clean}')
    return jsonify({'all_clean': all_clean, 'checks': results})
