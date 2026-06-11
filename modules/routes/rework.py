"""qr-system — 返工管理路由"""
from datetime import datetime
from flask import request, jsonify, g
from modules.app import app
from modules.db import get_db
from modules.middleware.auth import check_auth, check_permission, audit_log
from modules.middleware.error_handler import handle_unexpected_error


@app.route('/api/rework', methods=['GET'])
@check_auth
@check_permission('rework:view')
def rework_list():
    try:
        db = get_db()
        status = request.args.get('status', '')
        search = request.args.get('search', '')
        date_from = request.args.get('from', '')
        date_to = request.args.get('to', '')
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 50))

        where = ['1=1']
        params = []
        if status:
            where.append('rw.status = ?')
            params.append(status)
        if search:
            where.append('(o.order_no LIKE ? OR p.name LIKE ? OR u.name LIKE ?)')
            params.extend([f'%{search}%'] * 3)
        if date_from:
            where.append('rw.created_at >= ?')
            params.append(date_from)
        if date_to:
            where.append('rw.created_at <= ?')
            params.append(date_to + ' 23:59:59')

        where_clause = ' AND '.join(where)

        total = db.execute(f'''SELECT COUNT(*) FROM rework_records rw
            JOIN orders o ON rw.order_id=o.id AND o.deleted_at IS NULL
            JOIN processes p ON rw.process_id=p.id
            LEFT JOIN users u ON rw.user_id=u.id
            WHERE {where_clause}''', params).fetchone()[0]

        offset = (page - 1) * per_page
        rows = db.execute(f'''
            SELECT rw.*, o.order_no, o.product_name,
                   COALESCE(c.name, o.customer) as customer_name,
                   p.name as process_name, u.name as worker_name,
                   cu.name as completed_by_name
            FROM rework_records rw
            JOIN orders o ON rw.order_id = o.id AND o.deleted_at IS NULL
            LEFT JOIN customers c ON o.customer_id = c.id
            JOIN processes p ON rw.process_id = p.id
            LEFT JOIN users u ON rw.user_id = u.id
            LEFT JOIN users cu ON rw.completed_by = cu.id
            WHERE {where_clause}
            ORDER BY rw.created_at DESC
            LIMIT ? OFFSET ?
        ''', params + [per_page, offset]).fetchall()
        return jsonify({'ok': True, 'items': [dict(r) for r in rows], 'total': total, 'page': page, 'per_page': per_page})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/rework/stats', methods=['GET'])
@check_auth
@check_permission('rework:view')
def rework_stats():
    try:
        db = get_db()
        today = datetime.now().strftime('%Y-%m-%d')
        pending = db.execute('''SELECT COUNT(*), COALESCE(SUM(rw.quantity),0)
            FROM rework_records rw JOIN orders o ON rw.order_id=o.id AND o.deleted_at IS NULL
            WHERE rw.status='pending' ''').fetchone()
        today_total = db.execute('''SELECT COUNT(*), COALESCE(SUM(rw.quantity),0)
            FROM rework_records rw JOIN orders o ON rw.order_id=o.id AND o.deleted_at IS NULL
            WHERE DATE(rw.created_at)=?''', (today,)).fetchone()
        today_done = db.execute('''SELECT COUNT(*), COALESCE(SUM(rw.quantity),0)
            FROM rework_records rw JOIN orders o ON rw.order_id=o.id AND o.deleted_at IS NULL
            WHERE DATE(rw.completed_at)=?''', (today,)).fetchone()
        return jsonify({
            'ok': True,
            'pending_count': pending[0], 'pending_qty': pending[1] or 0,
            'today_count': today_total[0], 'today_qty': today_total[1] or 0,
            'today_done': today_done[0], 'today_done_qty': today_done[1] or 0,
        })
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/rework/<int:rework_id>', methods=['PUT'])
@check_auth
@check_permission('rework:edit')
def rework_update(rework_id):
    db = get_db()
    try:
        rw = db.execute('SELECT * FROM rework_records WHERE id = ?', (rework_id,)).fetchone()
        if not rw:
            return jsonify({'error': '记录不存在'}), 404
        data = request.get_json() or {}
        if 'reason' in data:
            db.execute("BEGIN IMMEDIATE")
            db.execute('UPDATE rework_records SET reason = ? WHERE id = ?', (data['reason'], rework_id))
            db.commit()
            audit_log('rework_edit', 'rework', rework_id, 'reason updated')
            return jsonify({'ok': True})
        return jsonify({'error': '无更新内容'}), 400
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/rework/<int:rework_id>/complete', methods=['POST'])
@check_auth
@check_permission('rework:edit')
def rework_complete(rework_id):
    db = get_db()
    try:
        rw = db.execute('SELECT * FROM rework_records WHERE id = ?', (rework_id,)).fetchone()
        if not rw:
            return jsonify({'error': '返工记录不存在'}), 404
        if rw['status'] == 'completed':
            return jsonify({'error': '该记录已完成'}), 409
        # 校验订单未被软删除
        order = db.execute('SELECT deleted_at FROM orders WHERE id = ?', (rw['order_id'],)).fetchone()
        if not order or order['deleted_at'] is not None:
            return jsonify({'error': '关联订单已删除'}), 400
        data = request.get_json() or {}
        user = g.current_user if hasattr(g, 'current_user') else {}
        reason_final = data.get('reason', rw['reason'])
        db.execute("BEGIN IMMEDIATE")
        db.execute('''UPDATE rework_records SET status = 'completed', reason = ?,
                      completed_at = datetime("now","localtime"),
                      completed_by = ? WHERE id = ?''', (reason_final, user.get('id'), rework_id))
        db.execute('UPDATE order_processes SET rework = MAX(rework - ?, 0) WHERE order_id = ? AND process_id = ?',
                   (rw['quantity'], rw['order_id'], rw['process_id']))
        db.execute('''UPDATE orders SET rework = (SELECT COALESCE(SUM(rework),0) FROM order_processes WHERE order_id = ?),
                      updated_at = datetime("now","localtime") WHERE id = ?''', (rw['order_id'], rw['order_id']))
        db.commit()
        audit_log('rework_complete', 'rework', rework_id, f'order={rw["order_id"]} process={rw["process_id"]}')
        return jsonify({'ok': True, 'message': '返工完成'})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')
