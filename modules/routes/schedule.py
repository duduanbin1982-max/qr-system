"""
qr-system — 生产排程路由

注：Swagger docstring 仅供文档参考。
"""
from flask import request, jsonify

from modules.app import app
from modules.db import get_db
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.error_handler import handle_unexpected_error


@app.route('/api/schedule/gantt', methods=['GET'])
@check_auth
@check_permission('schedule:view')
def schedule_gantt():
    """
    返回甘特图所需的所有订单排程数据
    ---
    tags:
      - Schedule
    summary: 返回甘特图所需的所有订单排程数据
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    try:
        db = get_db()
        rows = db.execute('''
            SELECT o.id, o.order_no, o.product_name, o.plan_start, o.plan_end,
                   o.status, o.quantity, o.completed,
                   COALESCE(c.name, o.customer) as customer_name
            FROM orders o
            LEFT JOIN customers c ON o.customer_id = c.id
            WHERE o.plan_start != ''
              AND o.deleted_at IS NULL
            ORDER BY o.plan_start, o.order_no
        ''').fetchall()

        orders = []
        min_date = None
        max_date = None

        for r in rows:
            start = r['plan_start']
            end = r['plan_end']
            orders.append({
                'id': r['id'],
                'order_no': r['order_no'],
                'product_name': r['product_name'],
                'customer_name': r['customer_name'],
                'plan_start': start,
                'plan_end': end,
                'status': r['status'],
                'quantity': r['quantity'],
                'completed': r['completed'],
                'progress': min(round(r['completed'] / r['quantity'] * 100), 100) if r['quantity'] else 0,
            })
            if start:
                if min_date is None or start < min_date:
                    min_date = start
                if max_date is None or end > max_date:
                    max_date = end

        return jsonify({'ok': True, 'orders': orders, 'min_date': min_date, 'max_date': max_date})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')
