"""
qr-system — 产品追溯路由

注：全读端点，Swagger docstring 仅供文档参考。
"""
from flask import jsonify
from modules.app import app
from modules.db import get_db
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.error_handler import handle_unexpected_error


@app.route('/api/trace/<code>', methods=['GET'])
@check_auth
@check_permission('trace:view')
def trace_product(code):
    """追溯产品完整生命周期"""
    try:
        db = get_db()

        # 1. 查找产品
        item = db.execute('''
            SELECT pi.*, o.order_no, o.product_name, o.quantity as order_quantity,
                   o.completed, o.status as order_status, o.created_at as order_created,
                   COALESCE(c.name, o.customer) as customer
            FROM product_items pi
            LEFT JOIN orders o ON pi.order_id = o.id AND o.deleted_at IS NULL
            LEFT JOIN customers c ON o.customer_id = c.id
            WHERE pi.serial_no = ?
        ''', (code,)).fetchone()

        if not item:
            return jsonify({'item': None, 'order': None, 'work_records': [], 'shipments': []})

        item_dict = dict(item)

        # 2. 订单信息
        order = None
        if item['order_id']:
            order = {
                'order_no': item_dict.pop('order_no', ''),
                'product_name': item_dict.pop('product_name', ''),
                'quantity': item_dict.pop('order_quantity', 0),
                'completed': item_dict.pop('completed', 0),
                'status': item_dict.pop('order_status', ''),
                'created_at': item_dict.pop('order_created', ''),
                'customer': item_dict.pop('customer', ''),
            }
        else:
            # 清理多余字段
            for k in ['order_no', 'product_name', 'order_quantity', 'completed', 'order_status', 'order_created', 'customer']:
                item_dict.pop(k, None)

        # 过滤 item_dict，只保留 product_items 表字段
        item_fields = ['id', 'serial_no', 'order_id', 'order_no', 'position_no',
                       'qr_content', 'status', 'current_process_id', 'created_at']
        clean_item = {k: item_dict.get(k) for k in item_fields if k in item_dict}

        # 3. 报工记录（同一订单的所有报工，按时间排序）
        work_records = []
        if item['order_id']:
            rows = db.execute('''
                SELECT wr.id, wr.quantity, wr.status, wr.type, wr.remark, wr.created_at,
                       p.name as process_name, u.name as worker_name
                FROM work_records wr
                JOIN processes p ON wr.process_id = p.id
                JOIN users u ON wr.user_id = u.id
                WHERE wr.order_id = ?
                ORDER BY wr.created_at ASC
            ''', (item['order_id'],)).fetchall()
            work_records = [dict(r) for r in rows]

        # 4. 发货记录（匹配产品名的出库单）
        shipments = []
        if order and order['product_name']:
            rows = db.execute('''
                SELECT DISTINCT s.id, s.shipment_no, s.customer, s.status,
                       s.total_quantity, s.completed_at
                FROM shipments s
                JOIN shipment_items si ON si.shipment_id = s.id
                WHERE si.product_name = ?
                ORDER BY s.created_at DESC
                LIMIT 10
            ''', (order['product_name'],)).fetchall()
            shipments = [dict(r) for r in rows]

        return jsonify({
            'item': clean_item,
            'order': order,
            'work_records': work_records,
            'shipments': shipments,
        })
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')
