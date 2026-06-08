"""qr-system - Notification System API"""
from datetime import datetime
from flask import request, jsonify, g
from modules.app import app
from modules.db import get_db
from modules.middleware.auth import check_auth


@app.route('/api/notifications', methods=['GET'])
@check_auth
def get_notifications():
    """Get notifications for current user with pagination."""
    db = get_db()
    user_id = g.current_user['id']
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    unread_only = request.args.get('unread_only', '0') == '1'
    offset = (page - 1) * per_page

    where = 'WHERE (user_id = ? OR user_id IS NULL)'
    params = [user_id]
    if unread_only:
        where += ' AND is_read = 0'

    count = db.execute(
        f'SELECT COUNT(*) FROM notifications {where}', params
    ).fetchone()[0]

    rows = db.execute(
        f'SELECT id, title, message, type, link, is_read, created_at '
        f'FROM notifications {where} '
        f'ORDER BY created_at DESC LIMIT ? OFFSET ?',
        params + [per_page, offset]
    ).fetchall()

    notifications = []
    for r in rows:
        notifications.append({
            'id': r[0], 'title': r[1], 'message': r[2], 'type': r[3],
            'link': r[4], 'is_read': bool(r[5]), 'created_at': r[6],
        })

    return jsonify({
        'notifications': notifications,
        'total': count,
        'page': page,
        'per_page': per_page,
        'total_pages': (count + per_page - 1) // per_page if count else 0,
    })


@app.route('/api/notifications/unread-count', methods=['GET'])
@check_auth
def unread_notification_count():
    """Get unread notification count for badge display."""
    db = get_db()
    user_id = g.current_user['id']
    count = db.execute(
        'SELECT COUNT(*) FROM notifications '
        'WHERE (user_id = ? OR user_id IS NULL) AND is_read = 0',
        (user_id,)
    ).fetchone()[0]
    return jsonify({'unread_count': count})


@app.route('/api/notifications/<int:notification_id>/read', methods=['POST'])
@check_auth
def mark_notification_read(notification_id):
    """Mark a single notification as read."""
    db = get_db()
    user_id = g.current_user['id']
    db.execute(
        'UPDATE notifications SET is_read = 1 WHERE id = ? AND (user_id = ? OR user_id IS NULL)',
        (notification_id, user_id)
    )
    db.commit()
    return jsonify({'ok': True})


@app.route('/api/notifications/read-all', methods=['POST'])
@check_auth
def mark_all_notifications_read():
    """Mark all notifications as read for current user."""
    db = get_db()
    user_id = g.current_user['id']
    db.execute(
        'UPDATE notifications SET is_read = 1 WHERE (user_id = ? OR user_id IS NULL) AND is_read = 0',
        (user_id,)
    )
    db.commit()
    return jsonify({'ok': True, 'marked': db.total_changes})


def create_notification(db, title, message, notification_type='info', link='', user_id=None):
    """Helper: create a notification. Call within a route handler.
    
    Args:
        db: database connection
        title: notification title
        message: notification body
        notification_type: 'info', 'success', 'warning', 'error'
        link: optional frontend route link
        user_id: target user (None = broadcast to all)
    """
    db.execute(
        'INSERT INTO notifications (user_id, title, message, type, link, created_at) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (user_id, title, message, notification_type, link,
         datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    )
    db.commit()
