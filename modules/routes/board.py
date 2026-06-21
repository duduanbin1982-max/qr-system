"""qr-system - Board Routes (Secure Token v2 — hashed + rotation + expiry)"""
import secrets, hashlib
from datetime import datetime, timedelta
from flask import request, jsonify
from modules.app import app
from modules.cache_utils import ttl_cache
from modules.middleware.rate_limit import rate_limit
from modules.db import get_setting, get_db, clear_settings_cache
from modules.middleware.auth import check_auth, check_permission
from modules.services import BaseService
from modules.services.board_service import BoardService

BOARD_SESSION_HOURS = 8
BOARD_TOKEN_MAX_AGE_DAYS = 90  # board_token must be rotated within 90 days


def _hash_token(token):
    """SHA256 hash a token for secure storage comparison."""
    return hashlib.sha256(token.encode()).hexdigest()


def _is_board_token_valid():
    """Check if the stored board_token exists and is not expired."""
    stored_hash = get_setting('board_token', '')
    if not stored_hash:
        return False, 'Board token not configured'
    created_at_str = get_setting('board_token_created_at', '')
    if created_at_str:
        try:
            created_at = datetime.strptime(created_at_str, '%Y-%m-%d %H:%M:%S')
            age_days = (datetime.now() - created_at).days
            if age_days > BOARD_TOKEN_MAX_AGE_DAYS:
                return False, f'Board token expired ({age_days} days old, max {BOARD_TOKEN_MAX_AGE_DAYS})'
        except (ValueError, TypeError):
            import logging
            logging.getLogger("qr.board").warning("Invalid board_token_created_at value: %s", created_at_str)
    return True, ''


@app.route('/api/board/auth', methods=['POST'])
@rate_limit(max_rpm=10)
def board_auth():
    data = request.get_json(silent=True) or {}
    provided = (data.get('board_token') or '').strip()
    if not provided:
        return jsonify({'error': 'missing token'}), 400

    valid, err_msg = _is_board_token_valid()
    if not valid:
        return jsonify({'error': err_msg}), 401

    stored_hash = get_setting('board_token', '')
    if _hash_token(provided) != stored_hash:
        return jsonify({'error': 'invalid token'}), 401

    db = get_db()
    session_token = secrets.token_hex(32)
    expires_at = (datetime.now() + timedelta(hours=BOARD_SESSION_HOURS)).strftime('%Y-%m-%d %H:%M:%S')

    with BaseService.transaction() as txn:
        txn.execute("INSERT INTO board_sessions (token, expires_at) VALUES (?, ?)", (session_token, expires_at))
    return jsonify({
        'token': session_token,
        'expires_at': expires_at,
        'expires_in_hours': BOARD_SESSION_HOURS
    })


@app.route('/api/board/auth/rotate', methods=['POST'])
@check_auth
@check_permission('settings:manage')
def board_auth_rotate():
    """Generate a new board_token (rotates old token, invalidates all sessions)."""
    new_token = secrets.token_hex(32)
    new_hash = _hash_token(new_token)
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    db = get_db()
    with BaseService.transaction() as txn:
        # Store the hash, never the plaintext
        txn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('board_token', ?)",
            (new_hash,)
        )
        txn.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('board_token_created_at', ?)",
            (now_str,)
        )
        # Invalidate all existing sessions immediately
        txn.execute("DELETE FROM board_sessions")
    clear_settings_cache()

    return jsonify({
        'board_token': new_token,
        'created_at': now_str,
        'expires_in_days': BOARD_TOKEN_MAX_AGE_DAYS,
        'message': 'Token rotated. Old sessions invalidated. Save this token — it will NOT be shown again.'
    })


@app.route('/api/board/auth/status', methods=['GET'])
@check_auth
@check_permission('settings:manage')
def board_auth_status():
    """Check board_token status (age, expiry, session count)."""
    valid, err_msg = _is_board_token_valid()
    created_at_str = get_setting('board_token_created_at', '')
    age_days = None
    if created_at_str:
        try:
            created_at = datetime.strptime(created_at_str, '%Y-%m-%d %H:%M:%S')
            age_days = (datetime.now() - created_at).days
        except (ValueError, TypeError):
            import logging
            logging.getLogger("qr.board").warning("Invalid board_token_created_at value: %s", created_at_str)

    db = get_db()
    active_sessions = db.execute(
        "SELECT COUNT(*) FROM board_sessions WHERE expires_at > datetime('now','localtime')"
    ).fetchone()[0]

    return jsonify({
        'configured': bool(get_setting('board_token', '')),
        'valid': valid,
        'error': None if valid else err_msg,
        'age_days': age_days,
        'max_age_days': BOARD_TOKEN_MAX_AGE_DAYS,
        'expires_in_days': BOARD_TOKEN_MAX_AGE_DAYS - age_days if age_days is not None else None,
        'active_sessions': active_sessions,
        'session_hours': BOARD_SESSION_HOURS,
    })


def _verify_board_session(token):
    if not token:
        return False
    db = get_db()
    row = db.execute(
        "SELECT id FROM board_sessions WHERE token = ? AND expires_at > datetime('now','localtime')",
        (token,)
    ).fetchone()
    return row is not None


@app.route('/api/dashboard/board', methods=['GET'])
@ttl_cache(ttl_seconds=15)
def dashboard_board():
    # Authorization: cookie > Bearer session > (URL token disabled for security)
    has_cookie = request.cookies.get('qr_token', '')
    authorized = False
    if has_cookie:
        authorized = True
    if not authorized:
        auth_header = request.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            if _verify_board_session(auth_header[7:]):
                authorized = True
    if not authorized:
        board_configured = bool(get_setting('board_token', ''))
        msg = 'Unauthorized' if board_configured else 'Board token not configured'
        return jsonify({'error': msg}), 401

    category = request.args.get('category', '').strip()
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    data = BoardService.get_board_data(category)
    return jsonify({
        'now': now_str, 'update_time': now_str,
        'stats': {
            'total_orders': data['total_orders'],
            'producing_orders': data['producing_orders'],
            'completed_orders': data['completed_orders']
        },
        'today': {
            'today_output': data['today_output'],
            'today_scrap': data['today_scrap'],
            'today_reports': data.get('today_reports', 0),
            'today_rework': data.get('today_rework', 0)
        },
        'orders': data['orders_in_progress'],
        'overdue_orders': data.get('overdue_orders', []),
        'process_stats': data['process_efficiency'],
        'worker_stats': data.get('worker_stats', []),
        'recent_reports': data['recent_work'],
        'monthly_completion': data['monthly_completion'],
    })


@app.route('/api/board/auth/cleanup', methods=['POST'])
@check_auth
@check_permission('settings:manage')
def board_auth_cleanup():
    db = get_db()
    with BaseService.transaction() as txn:
        txn.execute("DELETE FROM board_sessions WHERE expires_at <= datetime('now','localtime')")
    return jsonify({'message': 'cleaned'})
