"""qr-system - Board Routes (Refactored + Secure Token)"""
import secrets
from datetime import datetime, timedelta
from flask import request, jsonify
from modules.app import app
from modules.cache_utils import ttl_cache
from modules.db import get_setting, get_db
from modules.middleware.auth import check_auth, check_permission
from modules.services.board_service import BoardService

BOARD_SESSION_HOURS = 8


@app.route('/api/board/auth', methods=['POST'])
def board_auth():
    data = request.get_json(silent=True) or {}
    provided = (data.get('board_token') or '').strip()
    if not provided:
        return jsonify({'error': 'missing token'}), 400
    stored_token = get_setting('board_token', '')
    if not stored_token:
        return jsonify({'error': 'token not configured'}), 400
    if provided != stored_token:
        return jsonify({'error': 'invalid token'}), 401
    db = get_db()
    session_token = secrets.token_hex(32)
    expires_at = (datetime.now() + timedelta(hours=BOARD_SESSION_HOURS)).strftime('%Y-%m-%d %H:%M:%S')
    db.execute("CREATE TABLE IF NOT EXISTS board_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT UNIQUE NOT NULL, expires_at TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now','localtime')))")
    db.execute("INSERT INTO board_sessions (token, expires_at) VALUES (?, ?)", (session_token, expires_at))
    db.commit()
    return jsonify({'token': session_token, 'expires_at': expires_at, 'expires_in_hours': BOARD_SESSION_HOURS})


def _verify_board_session(token):
    if not token:
        return False
    db = get_db()
    row = db.execute("SELECT id FROM board_sessions WHERE token = ? AND expires_at > datetime('now','localtime')", (token,)).fetchone()
    return row is not None


@app.route('/api/dashboard/board', methods=['GET'])
def dashboard_board():
    board_token = get_setting('board_token', '')
    has_cookie = request.cookies.get('qr_token', '')
    authorized = False
    if has_cookie:
        authorized = True
    if not authorized:
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            if _verify_board_session(auth_header[7:]):
                authorized = True
    if not authorized and board_token:
        provided = ''  # URL token fallback disabled for security
        if provided == board_token:
            authorized = True
            app.logger.warning('Board accessed via legacy URL token')
    if not authorized:
        msg = 'Unauthorized' if board_token else 'Board token not configured'
        return jsonify({'error': msg}), 401
    category = request.args.get('category', '').strip()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    data = BoardService.get_board_data(category)
    return jsonify({
        'now': now_str, 'update_time': now_str,
        'stats': {'total_orders': data['total_orders'], 'producing_orders': data['producing_orders'], 'completed_orders': data['completed_orders']},
        'today': {'today_output': data['today_output'], 'today_scrap': data['today_scrap'], 'today_reports': data.get('today_reports', 0), 'today_rework': data.get('today_rework', 0)},
        'orders': data['orders_in_progress'], 'overdue_orders': data.get('overdue_orders', []),
        'process_stats': data['process_efficiency'], 'worker_stats': data.get('worker_stats', []),
        'recent_reports': data['recent_work'], 'monthly_completion': data['monthly_completion'],
    })


@app.route('/api/board/auth/cleanup', methods=['POST'])
@check_auth
@check_permission('settings:manage')
def board_auth_cleanup():
    db = get_db()
    db.execute("DELETE FROM board_sessions WHERE expires_at <= datetime('now','localtime')")
    db.commit()
    return jsonify({'message': 'cleaned'})