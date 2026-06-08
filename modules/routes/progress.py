"""
qr-system - Production Progress & Delivery Alerts
"""
from datetime import datetime
from flask import request, jsonify, g
from modules.app import app
from modules.db import get_db
from modules.middleware.auth import check_auth, check_permission


@app.route('/api/orders/<int:oid>/progress', methods=['GET'])
@check_auth
@check_permission('orders:view')
def get_order_progress(oid):
    """Get per-process progress for an order with completion percentages."""
    db = get_db()
    order = db.execute(
        'SELECT id, order_no, product_name, quantity, status FROM orders WHERE id = ? AND deleted_at IS NULL',
        (oid,)
    ).fetchone()
    if not order:
        return jsonify({'error': 'Order not found'}), 404

    processes = db.execute('''
        SELECT op.process_id, op.seq_order, op.completed, op.scrapped, op.rework, op.status,
               p.name as process_name
        FROM order_processes op
        JOIN processes p ON op.process_id = p.id
        WHERE op.order_id = ?
        ORDER BY op.seq_order
    ''', (oid,)).fetchall()

    total_qty = order['quantity'] or 1
    proc_list = []
    overall = 0
    cnt = len(processes)

    for proc in processes:
        completed = proc['completed'] or 0
        scrapped = proc['scrapped'] or 0
        pct = round((completed / total_qty * 100), 1) if total_qty > 0 else 0
        proc_list.append({
            'process_id': proc['process_id'],
            'process_name': proc['process_name'],
            'seq_order': proc['seq_order'],
            'completed': completed,
            'scrapped': scrapped,
            'rework': proc['rework'] or 0,
            'status': proc['status'] or 'pending',
            'progress_pct': pct,
            'remaining': max(0, total_qty - completed - scrapped),
        })

    if cnt > 0:
        overall = round(sum(p['progress_pct'] for p in proc_list) / cnt, 1)

    return jsonify({
        'order_id': oid,
        'order_no': order['order_no'],
        'product_name': order['product_name'],
        'quantity': total_qty,
        'status': order['status'],
        'process_count': cnt,
        'overall_progress': overall,
        'processes': proc_list,
    })


@app.route('/api/orders/delivery-alerts', methods=['GET'])
@check_auth
@check_permission('orders:view')
def delivery_alerts():
    """Get overdue and near-due orders with severity levels."""
    db = get_db()
    days = max(request.args.get('days', 7, type=int), 1)

    overdue = db.execute('''
        SELECT id, order_no, customer, product_name, quantity, status, deadline,
               CAST(julianday('now') - julianday(deadline) AS INTEGER) as days_overdue
        FROM orders
        WHERE deadline != '' AND deadline IS NOT NULL
          AND deadline < date('now')
          AND status NOT IN ('completed', 'cancelled')
          AND deleted_at IS NULL
        ORDER BY deadline ASC
    ''').fetchall()

    near_due = db.execute('''
        SELECT id, order_no, customer, product_name, quantity, status, deadline,
               CAST(julianday(deadline) - julianday('now') AS INTEGER) as days_remaining
        FROM orders
        WHERE deadline != '' AND deadline IS NOT NULL
          AND deadline >= date('now')
          AND deadline <= date('now', '+' || ? || ' days')
          AND status NOT IN ('completed', 'cancelled')
          AND deleted_at IS NULL
        ORDER BY deadline ASC
    ''', (days,)).fetchall()

    no_dl = db.execute('''
        SELECT COUNT(*) as cnt FROM orders
        WHERE (deadline = '' OR deadline IS NULL)
          AND status IN ('pending', 'producing', 'paused')
          AND deleted_at IS NULL
    ''').fetchone()

    def severity(d):
        if d > 3: return 'critical'
        if d > 0: return 'warning'
        return 'info'

    return jsonify({
        'overdue': [{
            'id': r['id'], 'order_no': r['order_no'], 'customer': r['customer'],
            'product_name': r['product_name'], 'quantity': r['quantity'],
            'status': r['status'], 'deadline': r['deadline'],
            'days_overdue': r['days_overdue'],
            'severity': 'critical' if r['days_overdue'] > 3 else 'warning'
        } for r in overdue],
        'overdue_count': len(overdue),
        'near_due': [{
            'id': r['id'], 'order_no': r['order_no'], 'customer': r['customer'],
            'product_name': r['product_name'], 'quantity': r['quantity'],
            'status': r['status'], 'deadline': r['deadline'],
            'days_remaining': r['days_remaining'],
            'severity': severity(r['days_remaining'])
        } for r in near_due],
        'near_due_count': len(near_due),
        'no_deadline_count': no_dl['cnt'],
        'lookahead_days': days,
    })