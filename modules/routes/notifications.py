"""qr-system - Notifications Routes（Refactored）"""
from flask import request, jsonify, g
from modules.app import app
from modules.middleware.auth import check_auth
from modules.services.notification_service import NotificationService


@app.route('/api/notifications', methods=['GET'])
@check_auth
def list_notifications():
    user_id = g.current_user['id']
    limit = min(max(request.args.get('limit', 50, type=int), 1), 200)
    notifications = NotificationService.list_unread(user_id, limit)
    count = NotificationService.unread_count(user_id)
    return jsonify({'notifications': notifications, 'unread_count': count})


@app.route('/api/notifications/<int:nid>/read', methods=['POST'])
@check_auth
def mark_read(nid):
    NotificationService.mark_read(nid, g.current_user['id'])
    return jsonify({'ok': True})


@app.route('/api/notifications/read-all', methods=['POST'])
@check_auth
def mark_all_read():
    NotificationService.mark_all_read(g.current_user['id'])
    return jsonify({'ok': True})
