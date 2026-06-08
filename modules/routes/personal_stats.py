"""
qr-system - Personal Stats for Mobile Workers
Provides individual worker statistics for mobile H5 display.
"""
from flask import request, jsonify, g
from datetime import datetime, timedelta
from modules.app import app
from modules.db import get_db
from modules.middleware.auth import check_auth

@app.route('/api/personal/stats', methods=['GET'])
@check_auth
def personal_stats():
    """Get personal work statistics for the current user."""
    db = get_db()
    uid = g.current_user['id']

    now = datetime.now()
    today_start = now.strftime('%Y-%m-%d') + ' 00:00:00'
    week_start = (now - timedelta(days=now.weekday())).strftime('%Y-%m-%d') + ' 00:00:00'
    month_start = now.strftime('%Y-%m') + '-01 00:00:00'

    # Today's work records
    today_records = db.execute('''
        SELECT wr.id, wr.order_id, wr.process_id, wr.serial_no, wr.quantity, wr.type, wr.remark, wr.created_at,
               o.order_no, o.product_name, p.name as process_name
        FROM work_records wr
        LEFT JOIN orders o ON wr.order_id = o.id
        LEFT JOIN processes p ON wr.process_id = p.id
        WHERE wr.user_id = ? AND wr.created_at >= ?
        ORDER BY wr.created_at DESC
        LIMIT 50
    ''', (uid, today_start)).fetchall()

    # Today's summary
    today_sum = db.execute('''
        SELECT COUNT(*) as total_records, COALESCE(SUM(quantity),0) as total_qty,
               COUNT(DISTINCT order_id) as order_count
        FROM work_records
        WHERE user_id = ? AND created_at >= ?
    ''', (uid, today_start)).fetchone()

    # Week summary
    week_sum = db.execute('''
        SELECT COUNT(*) as total_records, COALESCE(SUM(quantity),0) as total_qty,
               COUNT(DISTINCT order_id) as order_count
        FROM work_records
        WHERE user_id = ? AND created_at >= ?
    ''', (uid, week_start)).fetchone()

    # Month summary
    month_sum = db.execute('''
        SELECT COUNT(*) as total_records, COALESCE(SUM(quantity),0) as total_qty,
               COUNT(DISTINCT order_id) as order_count
        FROM work_records
        WHERE user_id = ? AND created_at >= ?
    ''', (uid, month_start)).fetchone()

    # Process breakdown today
    process_breakdown = db.execute('''
        SELECT p.name as process_name, COUNT(*) as count, COALESCE(SUM(wr.quantity),0) as total_qty
        FROM work_records wr
        LEFT JOIN processes p ON wr.process_id = p.id
        WHERE wr.user_id = ? AND wr.created_at >= ?
        GROUP BY wr.process_id
        ORDER BY total_qty DESC
    ''', (uid, today_start)).fetchall()

    # Recent orders being worked on
    active_orders = db.execute('''
        SELECT DISTINCT o.id, o.order_no, o.product_name, o.status, o.quantity,
               (SELECT COALESCE(SUM(wr2.quantity),0) FROM work_records wr2 WHERE wr2.order_id = o.id AND wr2.user_id = ?) as my_qty
        FROM work_records wr
        JOIN orders o ON wr.order_id = o.id
        WHERE wr.user_id = ? AND o.status IN ('producing','pending')
        ORDER BY wr.created_at DESC
        LIMIT 10
    ''', (uid, uid)).fetchall()

    # Weekly trend (last 7 days)
    trend = []
    for i in range(6, -1, -1):
        day = (now - timedelta(days=i)).strftime('%Y-%m-%d')
        day_sum = db.execute('''
            SELECT COALESCE(SUM(quantity),0) as qty, COUNT(*) as records
            FROM work_records
            WHERE user_id = ? AND created_at >= ? AND created_at < ?
        ''', (uid, day + ' 00:00:00', day + ' 23:59:59')).fetchone()
        trend.append({
            'date': day,
            'quantity': day_sum['qty'],
            'records': day_sum['records'],
        })

    records = []
    for r in today_records:
        records.append({
            'id': r['id'],
            'order_id': r['order_id'],
            'order_no': r['order_no'] or '',
            'product_name': r['product_name'] or '',
            'process_id': r['process_id'],
            'process_name': r['process_name'] or '',
            'serial_no': r['serial_no'] or '',
            'quantity': r['quantity'],
            'type': r['type'] or '',
            'remark': r['remark'] or '',
            'created_at': r['created_at'],
        })

    return jsonify({
        'user': {
            'id': uid,
            'name': g.current_user.get('name', g.current_user.get('username', '')),
            'username': g.current_user.get('username', ''),
        },
        'today': {
            'records': today_sum['total_records'],
            'quantity': today_sum['total_qty'],
            'orders': today_sum['order_count'],
        },
        'week': {
            'records': week_sum['total_records'],
            'quantity': week_sum['total_qty'],
            'orders': week_sum['order_count'],
        },
        'month': {
            'records': month_sum['total_records'],
            'quantity': month_sum['total_qty'],
            'orders': month_sum['order_count'],
        },
        'process_breakdown': [{'process': r['process_name'], 'count': r['count'], 'quantity': r['total_qty']} for r in process_breakdown],
        'active_orders': [{'id': r['id'], 'order_no': r['order_no'], 'product_name': r['product_name'], 'status': r['status'], 'order_qty': r['quantity'], 'my_qty': r['my_qty']} for r in active_orders],
        'trend': trend,
        'recent_records': records,
    })