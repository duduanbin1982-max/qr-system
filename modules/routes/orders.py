"""
qr-system — 订单管理路由：CRUD + 批量创建 + 报工记录 + 发货记录 + 自动单号
"""
import json
from datetime import datetime
from flask import request, jsonify, g

from modules.app import app
from modules.db import get_db, get_page_size
from modules.middleware.auth import check_auth, check_permission, audit_log
from modules.middleware.validate import validate_json
from modules.middleware.data_scope import get_user_process_ids



from modules.services.order_service import OrderService
from modules.middleware.error_handler import handle_unexpected_error
from modules.middleware.helpers import get_json_body

@app.route('/api/orders', methods=['GET'])
@check_auth
@check_permission('orders:view')
def list_orders():
    db = get_db()
    page = max(request.args.get('page', 1, type=int), 1)
    limit_raw = request.args.get('limit', get_page_size(), type=int)
    limit = min(max(limit_raw, 1), 200)
    status = request.args.get('status', '')
    keyword = request.args.get('keyword', '')
    customer = request.args.get('customer', '')

    where = ['o.deleted_at IS NULL']
    params = []
    if status:
        where.append('o.status = ?')
        params.append(status)
    if keyword:
        where.append('(o.order_no LIKE ? OR o.product_name LIKE ?)')
        params.extend([f'%{keyword}%', f'%{keyword}%'])
    if customer:
        where.append('c.name LIKE ?')
        params.append(f'%{customer}%')

    # 数据权限：按用户岗位工序范围过滤订单
    pids = get_user_process_ids(g.current_user)
    if pids is not None:
        if not pids:
            return jsonify({'orders': [], 'total': 0, 'page': page, 'limit': limit})
        placeholders = ','.join('?' for _ in pids)
        where.append(f'o.id IN (SELECT order_id FROM order_processes WHERE process_id IN ({placeholders}))')
        params.extend(pids)

    where_sql = ' AND '.join(where)

    total = db.execute(f'SELECT COUNT(*) FROM orders o WHERE {where_sql}', params).fetchone()[0]

    rows = db.execute(f'''
        SELECT o.*, pr.name as route_name, c.name as customer_name
        FROM orders o
        LEFT JOIN process_routes pr ON o.route_id = pr.id
        LEFT JOIN customers c ON o.customer_id = c.id
        WHERE {where_sql}
        ORDER BY o.updated_at DESC, o.id DESC
        LIMIT ? OFFSET ?
    ''', params + [limit, (page - 1) * limit]).fetchall()

    order_ids = [row['id'] for row in rows]
    all_procs = {}
    if order_ids:
        placeholders = ','.join('?' for _ in order_ids)
        procs = db.execute(f'''
            SELECT op.*, p.name as process_name
            FROM order_processes op JOIN processes p ON op.process_id = p.id
            WHERE op.order_id IN ({placeholders})
            ORDER BY op.order_id, op.seq_order
        ''', order_ids).fetchall()
        for p in procs:
            oid = p['order_id']
            if oid not in all_procs:
                all_procs[oid] = []
            all_procs[oid].append(dict(p))

    result = []
    for row in rows:
        o = dict(row)
        try:
            o['extra_fields'] = json.loads(o.get('extra_fields') or '{}')
        except Exception:
            o['extra_fields'] = {}
        if not o.get('product_code'):
            o['product_code'] = o['extra_fields'].get('product_code', '') if isinstance(o['extra_fields'], dict) else ''
        o['processes'] = all_procs.get(o['id'], [])
        result.append(o)

    # Status counts (global, not paginated)
    status_counts = db.execute(f'''SELECT o.status, COUNT(*) as cnt FROM orders o WHERE {where_sql} GROUP BY o.status''', params).fetchall()
    counts = {r['status']: r['cnt'] for r in status_counts}

    return jsonify({'orders': result, 'total': total, 'page': page, 'limit': limit,
                    'pending': counts.get('pending', 0), 'producing': counts.get('producing', 0),
                    'completed': counts.get('completed', 0)})


@app.route('/api/orders/next-no', methods=['GET'])
@check_auth
def get_next_order_no():
    order_no = OrderService.next_order_no()
    return jsonify({'order_no': order_no})


@app.route('/api/orders', methods=['POST'])
@check_auth
@check_permission('orders:create')
@validate_json('create_order')
def create_order():
    data = get_json_body()
    order_no = data.get('order_no', '').strip()
    if not order_no:
        order_no = OrderService.next_order_no()
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    try:
        existing = db.execute('SELECT id FROM orders WHERE order_no = ?', (order_no,)).fetchone()
        if existing:
            order_no = OrderService.next_order_no()
            existing2 = db.execute('SELECT id FROM orders WHERE order_no = ?', (order_no,)).fetchone()
            if existing2:
                return jsonify({'error': '订单号冲突，请重试'}), 409

        extra = {k: v for k, v in data.items()
                 if k not in ('order_no', 'customer', 'customer_id', 'product_name', 'quantity',
                              'plan_start', 'plan_end', 'deadline', 'remark', 'process_ids', 'route_id')}

        route_id = data.get('route_id')
        customer_id = data.get('customer_id')
        customer = (data.get('customer') or '').strip()
        if not customer and customer_id:
            cust_row = db.execute('SELECT name FROM customers WHERE id = ?', (customer_id,)).fetchone()
            if cust_row:
                customer = cust_row['name']
        cur = db.execute('''
            INSERT INTO orders (order_no, customer, customer_id, product_name, quantity, plan_start, plan_end, deadline, extra_fields, remark, route_id, status, product_code)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,'pending', ?)
        ''', (order_no, customer, customer_id if customer_id else None, data.get('product_name', ''),
              data.get('quantity', 0), data.get('plan_start', ''), data.get('plan_end', ''),
              data.get('deadline', ''), json.dumps(extra, ensure_ascii=False), data.get('remark', ''),
              route_id if route_id else None, data.get('product_code', '')))
        order_id = cur.lastrowid

        process_ids = data.get('process_ids', [])
        if route_id and not process_ids:
            route_items = db.execute('''
                SELECT pri.process_id, pri.seq_order, pri.required_audit
                FROM process_route_items pri
                WHERE pri.route_id = ?
                ORDER BY pri.seq_order
            ''', (route_id,)).fetchall()
            for item in route_items:
                db.execute('INSERT INTO order_processes (order_id, process_id, seq_order, required_audit) VALUES (?,?,?,?)',
                           (order_id, item['process_id'], item['seq_order'], item['required_audit']))
        else:
            if not process_ids:
                procs = db.execute('SELECT id, seq_order FROM processes WHERE status = "active" ORDER BY seq_order').fetchall()
                process_ids = [p['id'] for p in procs]
            for pid in process_ids:
                proc = db.execute('SELECT seq_order FROM processes WHERE id = ?', (pid,)).fetchone()
                if proc:
                    db.execute('INSERT INTO order_processes (order_id, process_id, seq_order) VALUES (?,?,?)',
                               (order_id, pid, proc['seq_order']))

        db.commit()
        audit_log('create_order', 'order', order_id, order_no)
        return jsonify({'message': '创建成功', 'id': order_id})
    except Exception as e:
        db.execute('ROLLBACK')
        return jsonify({'error': f'创建失败: {e}'}), 500


@app.route('/api/orders/<int:oid>', methods=['PUT'])
@check_auth
@check_permission('orders:edit')
def update_order(oid):
    data = get_json_body()
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    existing = db.execute('SELECT id, status FROM orders WHERE id = ? AND deleted_at IS NULL', (oid,)).fetchone()
    if not existing:
        return jsonify({'error': '订单不存在'}), 404

    # 状态转换校验 — 禁止无效转换
    VALID_TRANSITIONS = {
        'pending':   ['producing', 'cancelled', 'paused'],
        'producing': ['completed', 'cancelled', 'paused'],
        'completed': [],  # 已完成不可回退
        'cancelled': ['pending'],  # 已取消可重新激活
        'paused':    ['producing', 'pending', 'cancelled'],
    }
    if 'status' in data:
        new_status = data['status']
        old_status = existing['status']
        if new_status != old_status:
            allowed = VALID_TRANSITIONS.get(old_status, [])
            if new_status not in allowed:
                return jsonify({'error': f'不允许从「{old_status}」切换到「{new_status}」'}), 400

    if 'customer_id' in data and data['customer_id']:
        if not (data.get('customer') or '').strip():
            cust = db.execute('SELECT name FROM customers WHERE id = ?', (data['customer_id'],)).fetchone()
            if cust:
                data['customer'] = cust['name']
    sets = []
    params = []
    for field in ['order_no', 'customer', 'customer_id', 'product_name', 'product_code', 'quantity', 'plan_start',
                  'plan_end', 'deadline', 'remark', 'status', 'route_id']:
        if field in data:
            sets.append(f'{field} = ?')
            params.append(data[field] if data[field] is not None else None)
    if sets:
        sets.append('updated_at = datetime("now","localtime")')
        params.append(oid)
        db.execute(f'UPDATE orders SET {", ".join(sets)} WHERE id = ?', params)

    if 'process_ids' in data:
        new_pids = [int(pid) for pid in data["process_ids"]]
        existing_procs = db.execute('SELECT process_id, completed, scrapped, rework, status FROM order_processes WHERE order_id = ?', (oid,)).fetchall()
        existing_map = {r['process_id']: r for r in existing_procs}
        remove_ids = [pid for pid in existing_map if pid not in new_pids]
        if remove_ids:
            db.execute('DELETE FROM order_processes WHERE order_id = ? AND process_id IN (' + ','.join('?' for _ in remove_ids) + ')', remove_ids)
        for pid in new_pids:
            if pid in existing_map:
                continue
            proc = db.execute('SELECT seq_order FROM processes WHERE id = ?', (pid,)).fetchone()
            if proc:
                db.execute('INSERT INTO order_processes (order_id, process_id, seq_order) VALUES (?,?,?)',
                           (oid, pid, proc['seq_order']))
    try:
        db.commit()
        safe_data = {k:v for k,v in data.items() if k not in ('password', 'token', 'process_ids')}
        audit_log('update_order', 'order', oid, str(safe_data))
        return jsonify({'message': '更新成功'})
    except Exception as e:
        db.execute('ROLLBACK')
        return jsonify({'error': f'更新失败: {e}'}), 500


@app.route('/api/orders/<int:oid>', methods=['DELETE'])
@check_auth
@check_permission('orders:delete')
def delete_order(oid):
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    try:
        existing = db.execute('SELECT id, order_no FROM orders WHERE id = ? AND deleted_at IS NULL', (oid,)).fetchone()
        if not existing:
            return jsonify({'error': '订单不存在'}), 404
        db.execute('''UPDATE orders SET deleted_at = datetime("now","localtime"),
                      deleted_by = ? WHERE id = ?''', (g.current_user['id'], oid))
        db.commit()
        audit_log('delete_order', 'order', oid, existing['order_no'] + ' (soft)')
        return jsonify({'message': '已移至回收站'})
    except Exception as e:
        db.execute('ROLLBACK')
        return jsonify({'error': f'删除失败: {e}'}), 500


@app.route('/api/orders/<int:oid>/restore', methods=['POST'])
@check_auth
@check_permission('orders:edit')
def restore_order(oid):
    db = get_db()
    existing = db.execute('SELECT id, order_no FROM orders WHERE id = ? AND deleted_at IS NOT NULL', (oid,)).fetchone()
    if not existing:
        return jsonify({'error': '未找到已删除的订单'}), 404
    db.execute('UPDATE orders SET deleted_at = NULL, deleted_by = NULL WHERE id = ?', (oid,))
    db.commit()
    audit_log('restore_order', 'order', oid, existing['order_no'])
    return jsonify({'message': '订单已恢复'})


@app.route('/api/orders/trash', methods=['GET'])
@check_auth
@check_permission('orders:view')
def trash_orders():
    db = get_db()
    page = max(request.args.get('page', 1, type=int), 1)
    limit = min(max(request.args.get('limit', 20, type=int), 1), 200)
    total = db.execute('SELECT COUNT(*) FROM orders WHERE deleted_at IS NOT NULL').fetchone()[0]
    rows = db.execute('''
        SELECT o.*, u.name as deleted_by_name
        FROM orders o LEFT JOIN users u ON o.deleted_by = u.id
        WHERE o.deleted_at IS NOT NULL
        ORDER BY o.deleted_at DESC LIMIT ? OFFSET ?
    ''', (limit, (page - 1) * limit)).fetchall()
    return jsonify({'orders': [dict(r) for r in rows], 'total': total, 'page': page, 'limit': limit})


@app.route('/api/orders/<int:oid>/purge', methods=['DELETE'])
@check_auth
@check_permission('orders:delete')
def purge_order(oid):
    """彻底删除订单及其所有子表数据（从回收站永久删除）"""
    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    try:
        existing = db.execute('SELECT id, order_no FROM orders WHERE id = ? AND deleted_at IS NOT NULL', (oid,)).fetchone()
        if not existing:
            return jsonify({'error': '未找到可彻底删除的订单'}), 404
        for tbl in ['work_records','scrap_records','rework_records','quality_inspections',
                    'material_consumptions','order_processes','product_items','order_attachments']:
            db.execute(f'DELETE FROM {tbl} WHERE order_id = ?', (oid,))
        db.execute('DELETE FROM orders WHERE id = ?', (oid,))
        db.commit()
        audit_log('purge_order', 'order', oid, existing['order_no'])
        return jsonify({'message': '订单已彻底删除'})
    except Exception as e:
        db.execute('ROLLBACK')
        return jsonify({'error': f'删除失败: {e}'}), 500


@app.route('/api/orders/<int:oid>/work-records', methods=['GET'])
@check_auth
def get_order_work_records(oid):
    db = get_db()
    order = db.execute('SELECT id, order_no FROM orders WHERE id = ?', (oid,)).fetchone()
    if not order:
        return jsonify({'error': '订单不存在'}), 404

    normal = db.execute('''
        SELECT wr.*, u.name as worker_name, p.name as process_name,
               'normal' as record_type
        FROM work_records wr
        JOIN users u ON wr.user_id = u.id
        JOIN processes p ON wr.process_id = p.id
        WHERE wr.order_id = ?
        ORDER BY wr.created_at DESC
    ''', (oid,)).fetchall()

    scrap = db.execute('''
        SELECT sr.*, u.name as worker_name, p.name as process_name,
               'scrap' as record_type
        FROM scrap_records sr
        JOIN users u ON sr.user_id = u.id
        JOIN processes p ON sr.process_id = p.id
        WHERE sr.order_id = ?
        ORDER BY sr.created_at DESC
    ''', (oid,)).fetchall()

    rework = db.execute('''
        SELECT rr.*, u.name as worker_name, p.name as process_name,
               'rework' as record_type
        FROM rework_records rr
        JOIN users u ON rr.user_id = u.id
        JOIN processes p ON rr.process_id = p.id
        WHERE rr.order_id = ?
        ORDER BY rr.created_at DESC
    ''', (oid,)).fetchall()

    all_records = [dict(r) for r in list(normal) + list(scrap) + list(rework)]
    all_records.sort(key=lambda x: x.get('created_at', ''), reverse=True)

    return jsonify({
        'order_id': oid,
        'order_no': order['order_no'],
        'records': all_records,
        'summary': {
            'normal_count': len(normal),
            'scrap_count': len(scrap),
            'rework_count': len(rework),
            'total_quantity': sum(r.get('quantity', 0) for r in normal)
        }
    })


@app.route('/api/orders/<int:oid>/shipments', methods=['GET'])
@check_auth
@check_permission('shipments:view')
def get_order_shipments(oid):
    db = get_db()
    order = db.execute('SELECT id, order_no, product_code, product_name FROM orders WHERE id = ?', (oid,)).fetchone()
    if not order:
        return jsonify({'error': '订单不存在'}), 404

    # Note: matches by product_code (attribute key), not order_id.
    # Shows all shipments for products with the same product_code — intentional
    # for users to see all shipments of this product type.
    shipments = db.execute('''
        SELECT DISTINCT s.*,
               (SELECT COUNT(*) FROM shipment_items WHERE shipment_id = s.id) as item_count
        FROM shipments s
        JOIN shipment_items si ON si.shipment_id = s.id
        JOIN inventory i ON si.inventory_id = i.id
        WHERE i.product_model = ?
        ORDER BY s.created_at DESC
    ''', (order['product_code'],)).fetchall()

    return jsonify({
        'order_id': oid,
        'order_no': order['order_no'],
        'product_name': order['product_name'],
        'product_code': order['product_code'],
        'shipments': [dict(s) for s in shipments]
    })


@app.route('/api/orders/batch', methods=['POST'])
@check_auth
def batch_create_orders():
    data = get_json_body()
    orders_data = data.get('orders', [])
    if not orders_data:
        return jsonify({'error': '无订单数据'}), 400

    db = get_db()
    db.execute("BEGIN IMMEDIATE")
    try:
        created = 0
        errors = []
        procs = db.execute('SELECT id, seq_order FROM processes WHERE status = "active" ORDER BY seq_order').fetchall()
        proc_ids = [p['id'] for p in procs]
        seen_nos = set()

        for i, o in enumerate(orders_data):
            order_no = str(o.get('order_no', '')).strip()
            if not order_no:
                errors.append(f'第{i+1}行: 订单号为空')
                continue
            if order_no in seen_nos:
                errors.append(f"第{i+1}行: 批次内订单号{order_no}重复")
                continue
            seen_nos.add(order_no)
            existing = db.execute('SELECT id FROM orders WHERE order_no = ?', (order_no,)).fetchone()
            if existing:
                errors.append(f'第{i+1}行: 订单号{order_no}已存在')
                continue
            try:
                cur = db.execute('''
                    INSERT INTO orders (order_no, customer, customer_id, product_name, product_code, quantity,
                        plan_start, plan_end, deadline, remark, route_id, status)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,'pending')
                ''', (order_no, str(o.get('customer', '')), o.get('customer_id'),
                      str(o.get('product_name', '')), str(o.get('product_code', '')),
                      int(o.get('quantity', 0) or 0),
                      str(o.get('plan_start', '')), str(o.get('plan_end', '')),
                      str(o.get('deadline', '')), str(o.get('remark', '')),
                      o.get('route_id')))
                oid = cur.lastrowid
                for pid in proc_ids:
                    proc = db.execute('SELECT seq_order FROM processes WHERE id = ?', (pid,)).fetchone()
                    if proc:
                        db.execute('INSERT INTO order_processes (order_id, process_id, seq_order) VALUES (?,?,?)',
                                   (oid, pid, proc['seq_order']))
                created += 1
            except Exception as e:
                errors.append(f'第{i+1}行: {str(e)}')

        db.commit()
        return jsonify({'message': f'成功创建{created}条', 'created': created, 'errors': errors})
    except Exception as e:
        db.execute('ROLLBACK')
        return jsonify({'error': f'批量创建失败: {e}'}), 500

# ============================================================
# 工件进度追踪
# ============================================================

@app.route('/api/orders/<int:order_id>/workpiece-progress', methods=['GET'])
@check_auth
@check_permission('orders:view')
def workpiece_progress(order_id):
    """返回订单每个工件×每道工序的进度矩阵"""
    db = get_db()

    order = db.execute(
        'SELECT * FROM orders WHERE id = ? AND deleted_at IS NULL', (order_id,)
    ).fetchone()
    if not order:
        return jsonify({'error': '订单不存在'}), 404

    # 所有工件
    items = db.execute(
        'SELECT * FROM product_items WHERE order_id = ? ORDER BY position_no',
        (order_id,)
    ).fetchall()

    # 所有工序（按 seq_order 排序）
    processes = db.execute('''
        SELECT op.*, p.name as process_name
        FROM order_processes op
        JOIN processes p ON p.id = op.process_id
        WHERE op.order_id = ?
        ORDER BY op.seq_order
    ''', (order_id,)).fetchall()

    # 获取所有报工记录（含 serial_no）
    work_records = db.execute('''
        SELECT wr.serial_no, wr.process_id, wr.status, wr.created_at
        FROM work_records wr
        WHERE wr.order_id = ? AND wr.serial_no IS NOT NULL AND wr.serial_no != ''
    ''', (order_id,)).fetchall()

    # 构建查找：serial_no → {process_id: record}
    record_map = {}
    for r in work_records:
        sn = r['serial_no']
        if sn not in record_map:
            record_map[sn] = {}
        record_map[sn][r['process_id']] = {
            'status': r['status'],
            'completed_at': r['created_at']
        }

    # 构建进度矩阵
    progress = []
    for item in items:
        sn = item['serial_no']
        steps = []
        current_found = False
        for proc in processes:
            pid = proc['process_id']
            rec = record_map.get(sn, {}).get(pid)

            if rec:
                # 有报工记录 → 已完成
                step_status = 'completed'
                step_time = rec['completed_at']
            elif current_found and proc['process_id'] == item['current_process_id']:
                # 当前工序
                step_status = 'current'
                step_time = None
            elif not current_found and item['current_process_id'] and proc['process_id'] == item['current_process_id']:
                step_status = 'current'
                step_time = None
                current_found = True
            elif item['status'] == 'completed':
                step_status = 'completed'
                step_time = item.get('completed_at')
            else:
                step_status = 'pending'
                step_time = None

            steps.append({
                'process_id': pid,
                'process_name': proc['process_name'],
                'seq_order': proc['seq_order'],
                'status': step_status,
                'completed_at': step_time,
            })

        # 判断工件整体状态
        all_completed = all(s['status'] == 'completed' for s in steps)
        workpiece_status = 'completed' if all_completed else (
            'in_progress' if any(s['status'] in ('completed', 'current') for s in steps) else 'pending'
        )

        progress.append({
            'serial_no': sn,
            'position_no': item['position_no'],
            'current_process_id': item['current_process_id'],
            'status': workpiece_status,
            'steps': steps,
        })

    # 汇总统计
    total_items = len(items)
    total_steps = len(processes)
    completed_items = sum(1 for p in progress if p['status'] == 'completed')
    in_progress_items = sum(1 for p in progress if p['status'] == 'in_progress')

    summary = {
        'total_workpieces': total_items,
        'completed_workpieces': completed_items,
        'in_progress_workpieces': in_progress_items,
        'pending_workpieces': total_items - completed_items - in_progress_items,
        'total_processes': total_steps,
        'overall_progress_pct': round(
            sum(1 for p in progress for s in p['steps'] if s['status'] == 'completed')
            / max(total_items * total_steps, 1) * 100, 1
        ),
        'process_stats': [
            {
                'process_id': proc['process_id'],
                'process_name': proc['process_name'],
                'seq_order': proc['seq_order'],
                'completed': sum(1 for p in progress
                    for s in p['steps']
                    if s['process_id'] == proc['process_id'] and s['status'] in ('completed',)
                ),
                'total': total_items,
            }
            for proc in processes
        ],
    }

    return jsonify({
        'order_id': order_id,
        'order_no': order['order_no'],
        'product_name': order['product_name'],
        'quantity': order['quantity'],
        'progress': progress,
        'summary': summary,
        'processes': [{'process_id': p['process_id'], 'name': p['process_name'], 'seq_order': p['seq_order']} for p in processes],
    })
