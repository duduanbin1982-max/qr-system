"""qr-system — 订单管理路由 (Refactored: all SQL → OrderService)"""
from flask import request, jsonify, g
from modules.app import app
from modules.middleware.audit import audit_log
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.validate import validate_json
from modules.middleware.data_scope import get_user_process_ids
from modules.middleware.error_handler import handle_unexpected_error
from modules.middleware.helpers import get_json_body
from modules.services.order_service import OrderService
from modules.services.scan_helper_service import ScanHelperService
from modules.services.setting_service import SettingsService



def _check_order_data_scope(oid):
    """Check if current user can access this order based on process permissions."""
    pids = get_user_process_ids(g.current_user)
    if pids is not None and not ScanHelperService.check_order_scope(oid, pids):
        return False
    return True

@app.route('/api/orders', methods=['GET'])
@check_auth
@check_permission('orders:view')
def list_orders():
    page = max(request.args.get('page', 1, type=int), 1)
    limit_raw = request.args.get('limit', int(SettingsService.get_value('page_size', '20') or 20), type=int)
    limit = min(max(limit_raw, 1), 200)
    status = request.args.get('status', '')
    keyword = request.args.get('keyword', '')
    customer = request.args.get('customer', '')
    pids = get_user_process_ids(g.current_user)
    result = OrderService.list_orders(
        page=page, limit=limit, status=status, keyword=keyword,
        customer=customer, data_scope_pids=pids
    )
    return jsonify(result)


@app.route('/api/orders/next-no', methods=['GET'])
@check_auth
@check_permission('orders:view')
def get_next_order_no():
    return jsonify({'order_no': OrderService.next_order_no()})


@app.route('/api/orders', methods=['POST'])
@check_auth
@check_permission('orders:create')
@validate_json('create_order')
def create_order():
    data = get_json_body()
    try:
        order_id, _order_no = OrderService.create_order(data)
        try:
            audit_log('create_order', 'order', order_id, data.get('order_no', ''))
        except Exception as e:
            app.logger.warning("audit_log failed: %s", e)
        return jsonify({'message': '创建成功', 'id': order_id})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f'创建失败: {e}'}), 500


@app.route('/api/orders/<int:oid>', methods=['PUT'])
@check_auth
@check_permission('orders:edit')
@validate_json('update_order')
def update_order(oid):
    if not _check_order_data_scope(oid):
        return jsonify({"error": "无权限访问此订单"}), 403
    data = get_json_body()
    try:
        # Remark history is now handled inside OrderService.update_order for TOCTOU safety
        uname = g.current_user.get('name', g.current_user.get('username', ''))
        OrderService.update_order(oid, data, user_id=g.current_user['id'], user_name=uname)
        return jsonify({'message': '更新成功'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': f'更新失败: {e}'}), 500


@app.route('/api/orders/<int:oid>', methods=['DELETE'])
@check_auth
@check_permission('orders:delete')
def delete_order(oid):
    if not _check_order_data_scope(oid):
        return jsonify({"error": "无权限访问此订单"}), 403
    """软删除 — 移入回收站"""
    try:
        user_id = g.current_user['id']
        OrderService.soft_delete_order(oid, user_id)
        try:
            audit_log('delete_order', 'order', oid, '')
        except Exception as e:
            app.logger.warning("audit_log failed: %s", e)
        return jsonify({'message': '已移入回收站'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/orders/<int:oid>/restore', methods=['POST'])
@check_auth
@check_permission('orders:delete')
def restore_order(oid):
    if not _check_order_data_scope(oid):
        return jsonify({"error": "无权限访问此订单"}), 403
    """从回收站恢复"""
    try:
        order_no = OrderService.restore_order(oid)
        return jsonify({'message': f'订单 {order_no} 已恢复'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/orders/trash', methods=['GET'])
@check_auth
@check_permission('orders:view')
def trash_orders():
    page = max(request.args.get('page', 1, type=int), 1)
    limit = min(max(request.args.get('limit', 20, type=int), 1), 200)
    result = OrderService.list_trash(page, limit)
    return jsonify(result)


@app.route('/api/orders/<int:oid>/purge', methods=['DELETE'])
@check_auth
@check_permission('orders:delete')
def purge_order(oid):
    if not _check_order_data_scope(oid):
        return jsonify({"error": "无权限访问此订单"}), 403
    """彻底删除（仅回收站中的订单）"""
    try:
        order_no = OrderService.purge_order(oid)
        return jsonify({'message': f'订单 {order_no} 已彻底删除'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/orders/<int:oid>/work-records', methods=['GET'])
@check_auth
@check_permission('orders:view')
def get_order_work_records(oid):
    if not _check_order_data_scope(oid):
        return jsonify({"error": "无权限访问此订单"}), 403
    """获取订单报工/报废/返工记录"""
    try:
        order = OrderService.get_order(oid)
        if not order:
            return jsonify({'error': '订单不存在'}), 404
        d = dict(order)
        return jsonify({
            'order_id': oid,
            'order_no': d.get('order_no', ''),
            'work_records': d.get('work_records', []),
            'scrap_records': d.get('scrap_records', []),
            'rework_records': d.get('rework_records', []),
        })
    except ValueError as e:
        return jsonify({'error': str(e)}), 404


@app.route('/api/orders/<int:oid>/shipments', methods=['GET'])
@check_auth
@check_permission('orders:view')
def get_order_shipments(oid):
    if not _check_order_data_scope(oid):
        return jsonify({"error": "无权限访问此订单"}), 403
    """获取订单发货记录"""
    try:
        order = OrderService.get_order(oid)
        if not order:
            return jsonify({'error': '订单不存在'}), 404
        d = dict(order)
        return jsonify({
            'order_id': oid,
            'shipments': d.get('shipments', []),
        })
    except ValueError as e:
        return jsonify({'error': str(e)}), 404


@app.route('/api/orders/batch', methods=['POST'])
@check_auth
@check_permission('orders:create')
@validate_json('batch_orders')
def batch_create_orders():
    data = get_json_body()
    orders_data = data.get('orders', data.get('items', []))
    try:
        created, errors = OrderService.batch_create(orders_data)
        return jsonify({
            'message': f'导入完成：成功{created}条，跳过{len(errors)}条',
            'created': created,
            'errors': errors,
            'detail': errors[:20] if errors else []
        })
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/orders/<int:order_id>/workpiece-progress', methods=['GET'])
@check_auth
@check_permission('orders:view')
def workpiece_progress(order_id):
    if not _check_order_data_scope(order_id):
        return jsonify({"error": "无权限访问此订单"}), 403
    """返回订单每个工件×每道工序的进度矩阵"""
    try:
        progress = OrderService.get_workpiece_progress(order_id)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        return jsonify({'error': '加载工件进度失败: ' + str(e)}), 500

    order = progress['order']
    items = progress['items']
    processes = progress['processes']
    record_map = progress['record_map']

    progress = []
    for item in items:
        sn = item['serial_no']
        steps = []
        current_found = False
        for proc in processes:
            pid = proc['process_id']
            rec = record_map.get(sn, {}).get(pid)
            if rec:
                step_status = 'completed'
                step_time = rec['completed_at']
            elif current_found and proc['process_id'] == item['current_process_id']:
                step_status = 'current'
                step_time = None
            elif not current_found and item['current_process_id'] and proc['process_id'] == item['current_process_id']:
                step_status = 'current'
                step_time = None
                current_found = True
            elif item['status'] == 'completed':
                step_status = 'completed'
                step_time = dict(item).get('completed_at')
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
                    if s['process_id'] == proc['process_id'] and s['status'] == 'completed'
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

# ═══════════════════════════════════════════
#  Order Materials (订单物料配方)
# ═══════════════════════════════════════════

@app.route("/api/orders/<int:order_id>/materials", methods=["GET"])
@check_auth

@check_permission("orders:view")
def list_order_materials(order_id):
    """????????"""
    try:
        materials = OrderService.list_order_materials(order_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify({"materials": materials})

@app.route("/api/orders/<int:order_id>/materials", methods=["POST"])
@check_auth
@check_permission("orders:edit")
def add_order_material(order_id):
    """?????????"""
    try:
        material = OrderService.add_order_material(order_id, get_json_body())
    except LookupError as e:
        return jsonify({"error": str(e)}), 409
    except ValueError as e:
        return jsonify({"error": str(e)}), 404 if "???" in str(e) else 400
    return jsonify({"material": material}), 201

@app.route("/api/orders/<int:order_id>/materials/<int:item_id>", methods=["DELETE"])
@check_auth
@check_permission("orders:edit")
def delete_order_material(order_id, item_id):
    """?????????"""
    try:
        OrderService.delete_order_material(order_id, item_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify({"message": "???"})

