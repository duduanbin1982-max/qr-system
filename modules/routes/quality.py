"""qr-system — 质量检验路由"""
from flask import request, jsonify
from modules.app import app
from modules.db import get_db
from modules.middleware.auth import check_auth, check_permission, audit_log


INSPECTION_TYPES = {
    'first_article': '首件检验',
    'in_process': '过程检验',
    'final': '终检',
}

DEFECT_CATEGORIES = ['尺寸超差', '外观缺陷', '材质问题', '焊接缺陷', '装配不良', '其他']


@app.route('/api/quality/inspections', methods=['GET'])
@check_auth
@check_permission('orders:view')
def quality_list():
    try:
        db = get_db()
        order_id = request.args.get('order_id', type=int)
        process_id = request.args.get('process_id', type=int)
        inspection_type = request.args.get('type', '')
        result = request.args.get('result', '')
        search = request.args.get('search', '')
        date_from = request.args.get('from', '')
        date_to = request.args.get('to', '')
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 20))

        where = ['1=1']
        params = []
        if order_id:
            where.append('qi.order_id = ?')
            params.append(order_id)
        if process_id:
            where.append('qi.process_id = ?')
            params.append(process_id)
        if inspection_type:
            where.append('qi.inspection_type = ?')
            params.append(inspection_type)
        if result:
            where.append('qi.result = ?')
            params.append(result)
        if search:
            where.append('(o.order_no LIKE ? OR p.name LIKE ?)')
            params.extend([f'%{search}%'] * 2)
        if date_from:
            where.append('qi.inspected_at >= ?')
            params.append(date_from)
        if date_to:
            where.append('qi.inspected_at <= ?')
            params.append(date_to + ' 23:59:59')

        where_clause = ' AND '.join(where)

        total = db.execute(f'''SELECT COUNT(*) FROM quality_inspections qi
            JOIN orders o ON qi.order_id=o.id AND o.deleted_at IS NULL
            JOIN processes p ON qi.process_id=p.id
            WHERE {where_clause}''', params).fetchone()[0]

        offset = (page - 1) * per_page
        rows = db.execute(f'''
            SELECT qi.*, o.order_no, o.product_name,
                   COALESCE(c.name, o.customer) as customer_name,
                   p.name as process_name,
                   u.name as inspector_name
            FROM quality_inspections qi
            JOIN orders o ON qi.order_id = o.id AND o.deleted_at IS NULL
            LEFT JOIN customers c ON o.customer_id = c.id
            JOIN processes p ON qi.process_id = p.id
            LEFT JOIN users u ON qi.inspector_id = u.id
            WHERE {where_clause}
            ORDER BY qi.inspected_at DESC
            LIMIT ? OFFSET ?
        ''', params + [per_page, offset]).fetchall()
        return jsonify({'ok': True, 'items': [dict(r) for r in rows], 'total': total, 'page': page, 'per_page': per_page})
    except Exception as e:
        return jsonify({'error': f'查询失败: {str(e)}'}), 500


@app.route('/api/quality/inspections', methods=['POST'])
@check_auth
@check_permission('orders:edit')
def quality_create():
    db = get_db()
    try:
        data = request.get_json() or {}
        order_id = data.get('order_id')
        process_id = data.get('process_id')
        inspection_type = data.get('inspection_type', 'first_article')
        quantity_checked = data.get('quantity_checked', 0)
        quantity_passed = data.get('quantity_passed', 0)
        quantity_failed = data.get('quantity_failed', 0)
        defect_category = data.get('defect_category', '').strip()
        defect_quantity = data.get('defect_quantity', 0)
        notes = data.get('notes', '')
        inspected_at = data.get('inspected_at', '')

        if not order_id or not process_id:
            return jsonify({'error': '订单和工序必填'}), 400
        if inspection_type not in INSPECTION_TYPES:
            return jsonify({'error': '无效的检验类型'}), 400

        # 校验订单存在且未被软删除
        order = db.execute('SELECT id, deleted_at FROM orders WHERE id = ?', (order_id,)).fetchone()
        if not order:
            return jsonify({'error': '订单不存在'}), 404
        if order['deleted_at'] is not None:
            return jsonify({'error': '订单已删除，无法添加检验记录'}), 400

        user = g.current_user if hasattr(g, 'current_user') else {}
        result = 'pass' if quantity_failed == 0 else ('fail' if quantity_passed == 0 else 'partial')

        db.execute("BEGIN IMMEDIATE")
        db.execute('''INSERT INTO quality_inspections
            (order_id, process_id, inspection_type, inspector_id, quantity_checked, quantity_passed, quantity_failed, result, defect_category, defect_quantity, notes, inspected_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
            (order_id, process_id, inspection_type, user.get('id'), quantity_checked, quantity_passed, quantity_failed, result,
             defect_category, defect_quantity, notes, inspected_at or None))
        db.commit()

        rid = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        audit_log('quality_create', 'quality_inspection', rid, f'order={order_id} process={process_id} type={inspection_type}')
        return jsonify({'ok': True, 'id': rid, 'message': '检验记录已创建'})
    except Exception as e:
        return jsonify({'error': f'创建失败: {str(e)}'}), 500


@app.route('/api/quality/inspections/<int:inspection_id>', methods=['PUT'])
@check_auth
@check_permission('orders:edit')
def quality_update(inspection_id):
    db = get_db()
    try:
        qi = db.execute('SELECT * FROM quality_inspections WHERE id=?', (inspection_id,)).fetchone()
        if not qi:
            return jsonify({'error': '记录不存在'}), 404

        data = request.get_json() or {}
        quantity_checked = data.get('quantity_checked', qi['quantity_checked'])
        quantity_passed = data.get('quantity_passed', qi['quantity_passed'])
        quantity_failed = data.get('quantity_failed', qi['quantity_failed'])
        defect_category = data.get('defect_category', qi.get('defect_category', ''))
        defect_quantity = data.get('defect_quantity', qi.get('defect_quantity', 0))
        notes = data.get('notes', qi['notes'])
        inspection_type = data.get('inspection_type', qi['inspection_type'])
        inspected_at = data.get('inspected_at', qi['inspected_at'])

        if inspection_type not in INSPECTION_TYPES:
            return jsonify({'error': '无效的检验类型'}), 400

        result = 'pass' if quantity_failed == 0 else ('fail' if quantity_passed == 0 else 'partial')

        db.execute("BEGIN IMMEDIATE")
        db.execute('''UPDATE quality_inspections
            SET inspection_type=?, quantity_checked=?, quantity_passed=?, quantity_failed=?, result=?, defect_category=?, defect_quantity=?, notes=?, inspected_at=?
            WHERE id=?''',
            (inspection_type, quantity_checked, quantity_passed, quantity_failed, result,
             defect_category, defect_quantity, notes, inspected_at or qi['inspected_at'], inspection_id))
        db.commit()
        audit_log('quality_edit', 'quality_inspection', inspection_id, f'result={result}')
        return jsonify({'ok': True, 'message': '已更新'})
    except Exception as e:
        return jsonify({'error': f'更新失败: {str(e)}'}), 500


@app.route('/api/quality/inspections/<int:inspection_id>', methods=['DELETE'])
@check_auth
@check_permission('orders:edit')
def quality_delete(inspection_id):
    db = get_db()
    try:
        qi = db.execute('SELECT * FROM quality_inspections WHERE id=?', (inspection_id,)).fetchone()
        if not qi:
            return jsonify({'error': '记录不存在'}), 404
        db.execute("BEGIN IMMEDIATE")
        db.execute('DELETE FROM quality_inspections WHERE id=?', (inspection_id,))
        db.commit()
        audit_log('quality_delete', 'quality_inspection', inspection_id, 'deleted')
        return jsonify({'ok': True, 'message': '已删除'})
    except Exception as e:
        return jsonify({'error': f'删除失败: {str(e)}'}), 500


@app.route('/api/quality/inspections/stats', methods=['GET'])
@check_auth
@check_permission('orders:view')
def quality_stats():
    try:
        db = get_db()
        today = __import__('datetime').datetime.now().strftime('%Y-%m-%d')
        total = db.execute('''SELECT COUNT(*) FROM quality_inspections qi
            JOIN orders o ON qi.order_id = o.id AND o.deleted_at IS NULL''').fetchone()[0]
        today_count = db.execute('''SELECT COUNT(*) FROM quality_inspections qi
            JOIN orders o ON qi.order_id = o.id AND o.deleted_at IS NULL
            WHERE DATE(qi.inspected_at)=?''', (today,)).fetchone()[0]
        pass_count = db.execute('''SELECT COUNT(*) FROM quality_inspections qi
            JOIN orders o ON qi.order_id = o.id AND o.deleted_at IS NULL
            WHERE qi.result='pass' ''').fetchone()[0]
        fail_count = db.execute('''SELECT COUNT(*) FROM quality_inspections qi
            JOIN orders o ON qi.order_id = o.id AND o.deleted_at IS NULL
            WHERE qi.result IN ('fail','partial')''').fetchone()[0]
        return jsonify({
            'ok': True,
            'total': total, 'today_count': today_count,
            'pass_count': pass_count, 'fail_count': fail_count,
        })
    except Exception as e:
        return jsonify({'error': f'查询失败: {str(e)}'}), 500


@app.route('/api/quality/defect-pareto', methods=['GET'])
@check_auth
@check_permission('orders:view')
def quality_defect_pareto():
    """不良品帕累托图数据"""
    try:
        db = get_db()
        date_from = request.args.get('from', '')
        date_to = request.args.get('to', '')
        where = ["defect_category != ''"]
        params = []
        if date_from:
            where.append('inspected_at >= ?')
            params.append(date_from)
        if date_to:
            where.append('inspected_at <= ?')
            params.append(date_to + ' 23:59:59')
        where_clause = ' AND '.join(where)
        rows = db.execute(f'''
            SELECT qi.defect_category, SUM(qi.defect_quantity) as total_qty, COUNT(*) as count
            FROM quality_inspections qi
            JOIN orders o ON qi.order_id = o.id AND o.deleted_at IS NULL
            WHERE {where_clause}
            GROUP BY qi.defect_category
            ORDER BY total_qty DESC
        ''', params).fetchall()
        items = [{'category': r['defect_category'], 'quantity': r['total_qty'] or 0, 'count': r['count']} for r in rows]
        grand_total = sum(i['quantity'] for i in items)
        cumulative = 0
        for i in items:
            cumulative += i['quantity']
            i['pct'] = round(i['quantity'] / grand_total * 100, 1) if grand_total else 0
            i['cum_pct'] = round(cumulative / grand_total * 100, 1) if grand_total else 0
        return jsonify({'ok': True, 'items': items, 'grand_total': grand_total, 'categories': DEFECT_CATEGORIES})
    except Exception as e:
        return jsonify({'error': f'查询失败: {str(e)}'}), 500
