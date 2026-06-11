"""qr-system - Export API Routes"""
from flask import request, jsonify, send_file
from modules.app import app
from modules.db import get_db
from modules.middleware.auth import check_auth
from modules.export_utils import (
    export_orders_to_excel,
    export_work_records_to_excel,
    export_inventory_to_excel,
)
import io


@app.route('/api/export/orders', methods=['GET'])
@check_auth
def export_orders():
    """Export orders to Excel."""
    db = get_db()
    rows = db.execute(
        'SELECT o.id, o.order_no, c.name as customer, o.product_name, '
        'o.quantity, o.status, o.plan_start, o.plan_end, o.deadline, o.created_at '
        'FROM orders o LEFT JOIN customers c ON o.customer_id = c.id '
        'ORDER BY o.id DESC'
    ).fetchall()

    orders = []
    for r in rows:
        orders.append({
            'id': r[0], 'order_no': r[1], 'customer': r[2], 'product_name': r[3],
            'quantity': r[4], 'status': r[5], 'plan_start': r[6], 'plan_end': r[7],
            'deadline': r[8], 'created_at': r[9],
        })

    output = export_orders_to_excel(orders)
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='orders_export.xlsx'
    )


@app.route('/api/exports/orders', methods=['GET'])
@check_auth
def export_orders_alias():
    """Alias for /api/export/orders"""
    return export_orders()

@app.route('/api/export/work-records', methods=['GET'])
@check_auth
def export_work_records():
    """Export work records to Excel."""
    db = get_db()
    order_id = request.args.get('order_id')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    query = (
        'SELECT wr.id, o.order_no, p.name as process_name, u.name as worker_name, '
        'wr.serial_no, wr.quantity, wr.type, wr.remark, wr.created_at '
        'FROM work_records wr '
        'LEFT JOIN orders o ON wr.order_id = o.id '
        'LEFT JOIN processes p ON wr.process_id = p.id '
        'LEFT JOIN users u ON wr.user_id = u.id '
        'WHERE 1=1'
    )
    params = []
    if order_id:
        query += ' AND wr.order_id = ?'
        params.append(order_id)
    if date_from:
        query += ' AND wr.created_at >= ?'
        params.append(date_from)
    if date_to:
        query += ' AND wr.created_at <= ?'
        params.append(date_to + ' 23:59:59')
    query += ' ORDER BY wr.id DESC LIMIT 10000'

    rows = db.execute(query, params).fetchall()
    records = []
    for r in rows:
        records.append({
            'id': r[0], 'order_no': r[1], 'process_name': r[2], 'worker_name': r[3],
            'serial_no': r[4], 'quantity': r[5], 'type': r[6], 'remark': r[7],
            'created_at': r[8],
        })

    output = export_work_records_to_excel(records)
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='work_records_export.xlsx'
    )


@app.route('/api/export/inventory', methods=['GET'])
@check_auth
def export_inventory():
    """Export inventory items to Excel."""
    db = get_db()
    rows = db.execute(
        'SELECT pi.id, p.code as product_code, p.name as product_name, '
        'pi.serial_no, pi.status, pi.location, pi.updated_at '
        'FROM product_items pi '
        'LEFT JOIN products p ON pi.product_id = p.id '
        'ORDER BY pi.id DESC LIMIT 10000'
    ).fetchall()

    items = []
    for r in rows:
        items.append({
            'id': r[0], 'product_code': r[1], 'product_name': r[2],
            'serial_no': r[3], 'status': r[4], 'location': r[5],
            'updated_at': r[6],
        })

    output = export_inventory_to_excel(items)
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='inventory_export.xlsx'
    )