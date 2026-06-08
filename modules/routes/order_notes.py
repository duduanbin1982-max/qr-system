"""
qr-system - Order Remark History Routes
"""
from flask import request, jsonify, g
from modules.app import app
from modules.db import get_db, get_page_size
from modules.middleware.auth import check_auth, check_permission

@app.route('/api/orders/<int:oid>/remarks', methods=['GET'])
@check_auth
@check_permission('orders:view')
def get_order_remarks(oid):
    """Get remark history for an order."""
    db = get_db()
    order = db.execute('SELECT id, order_no, remark FROM orders WHERE id = ? AND deleted_at IS NULL', (oid,)).fetchone()
    if not order:
        return jsonify({'error': 'Order not found'}), 404

    page = max(request.args.get('page', 1, type=int), 1)
    limit_raw = request.args.get('limit', get_page_size(), type=int)
    limit = min(max(limit_raw, 1), 100)
    offset = (page - 1) * limit

    total = db.execute('SELECT COUNT(*) FROM order_remark_history WHERE order_id = ?', (oid,)).fetchone()[0]
    rows = db.execute('''
        SELECT id, old_remark, new_remark, user_id, user_name, created_at
        FROM order_remark_history
        WHERE order_id = ?
        ORDER BY id DESC
        LIMIT ? OFFSET ?
    ''', (oid, limit, offset)).fetchall()

    history = []
    for r in rows:
        history.append({
            'id': r['id'],
            'old_remark': r['old_remark'],
            'new_remark': r['new_remark'],
            'user_id': r['user_id'],
            'user_name': r['user_name'],
            'created_at': r['created_at'],
        })

    return jsonify({
        'order_id': oid,
        'order_no': order['order_no'],
        'current_remark': order['remark'] or '',
        'total': total,
        'page': page,
        'limit': limit,
        'history': history,
    })