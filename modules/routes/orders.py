"""qr-system — 订单管理路由 (Refactored: all SQL → OrderService)"""
from flask import request, jsonify, g
from modules.route_decorators import (
    app,
    check_auth,
    check_order_data_scope,
    check_permission,
    get_json_body,
    get_user_process_ids,
    safe_audit_log,
    validate_json,
)
from modules.services.order_service import OrderService
from modules.services.order_focus_service import OrderFocusService
from modules.services.setting_service import SettingsService



def _check_order_data_scope(oid):
    """Check if current user can access this order based on process permissions."""
    return check_order_data_scope(oid, g.current_user)

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
    archive = request.args.get('archive', 'active')
    pids = get_user_process_ids(g.current_user)
    result = OrderService.list_orders(
        page=page, limit=limit, status=status, keyword=keyword,
        customer=customer, data_scope_pids=pids, archive=archive
    )
    return jsonify(result)


@app.route('/api/orders/next-no', methods=['GET'])
@check_auth
@check_permission('orders:view')
def get_next_order_no():
    return jsonify({'order_no': OrderService.next_order_no()})


@app.route('/api/orders/<int:oid>/qr-print', methods=['POST'])
@check_auth
@check_permission('scan:view')
@validate_json('qr_print_record')
def record_order_qr_print(oid):
    if not _check_order_data_scope(oid):
        return jsonify({'error': '无权限访问此订单'}), 403
    try:
        result = OrderService.record_qr_print(oid, get_json_body(), g.current_user)
        safe_audit_log(
            'print_order_qr',
            'order',
            oid,
            f"order_no={result['order_no']}; mode={result['mode']}; "
            f"copies={result['copies']}; labels={result['label_count']}; "
            f"print_count={result['qr_print_count']}",
        )
        return jsonify({'message': '打印状态已记录', 'print_status': result})
    except ValueError as error:
        return jsonify({'error': str(error)}), 400


@app.route('/api/orders', methods=['POST'])
@check_auth
@check_permission('orders:create')
@validate_json('create_order')
def create_order():
    data = get_json_body()
    try:
        order_id, order_no = OrderService.create_order(data)
        safe_audit_log('create_order', 'order', order_id, f'order_no={order_no}')
        return jsonify({'message': '创建成功', 'id': order_id})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


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
        order_no = OrderService.update_order(
            oid,
            data,
            user_id=g.current_user['id'],
            user_name=uname,
        )
        changed_fields = ','.join(sorted(data))
        safe_audit_log(
            'update_order',
            'order',
            oid,
            f'order_no={order_no}; fields={changed_fields}',
        )
        return jsonify({'message': '更新成功'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/orders/<int:oid>', methods=['DELETE'])
@check_auth
@check_permission('orders:delete')
def delete_order(oid):
    if not _check_order_data_scope(oid):
        return jsonify({"error": "无权限访问此订单"}), 403
    """软删除 — 移入回收站"""
    try:
        user_id = g.current_user['id']
        order_no = OrderService.soft_delete_order(oid, user_id)
        safe_audit_log('delete_order', 'order', oid, f'order_no={order_no}')
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
        safe_audit_log('restore_order', 'order', oid, f'order_no={order_no}')
        return jsonify({'message': f'订单 {order_no} 已恢复'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/orders/<int:oid>/reopen', methods=['POST'])
@check_auth
@check_permission('orders:edit')
def reopen_order(oid):
    if not _check_order_data_scope(oid):
        return jsonify({"error": "无权限访问此订单"}), 403
    data = get_json_body()
    reason = (data.get('reason') or '').strip()
    status = data.get('status', 'producing')
    try:
        result = OrderService.reopen_order(oid, reason, status=status)
        safe_audit_log(
            'reopen_order',
            'order',
            oid,
            f"order_no={result['order_no']}; status={result['status']}; reason={reason}",
        )
        return jsonify({'message': '订单已重新打开', 'status': result['status']})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/orders/trash', methods=['GET'])
@check_auth
@check_permission('orders:view')
def trash_orders():
    page = max(request.args.get('page', 1, type=int), 1)
    limit = min(max(request.args.get('limit', 20, type=int), 1), 200)
    result = OrderService.list_trash(
        page,
        limit,
        data_scope_pids=get_user_process_ids(g.current_user),
    )
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
        safe_audit_log('purge_order', 'order', oid, f'order_no={order_no}')
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
        return jsonify(OrderService.get_work_records(oid))
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
        return jsonify(OrderService.get_shipments(oid))
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


@app.route('/api/orders/completion-focus', methods=['GET'])
@check_auth
@check_permission('orders:view')
def completion_focus_board():
    limit = min(max(request.args.get('limit', 80, type=int), 1), 200)
    return jsonify(OrderFocusService.board(
        limit=limit,
        data_scope_pids=get_user_process_ids(g.current_user),
    ))


@app.route('/api/orders/completion-focus/config', methods=['GET'])
@check_auth
@check_permission('orders:view')
def completion_focus_config():
    return jsonify(OrderFocusService.config())


@app.route('/api/orders/completion-focus/config', methods=['POST'])
@check_auth
@check_permission('orders:edit')
def save_completion_focus_config():
    try:
        config = OrderFocusService.save_config(get_json_body())
        safe_audit_log('completion_focus_config', 'system', 0, str(config))
        return jsonify({'message': '集中完工管控配置已保存', 'config': config})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/orders/<int:order_id>/completion-focus-exception', methods=['POST'])
@check_auth
@check_permission('orders:edit')
def create_completion_focus_exception(order_id):
    if not _check_order_data_scope(order_id):
        return jsonify({"error": "无权限访问此订单"}), 403
    try:
        exception = OrderFocusService.create_exception(order_id, get_json_body(), g.current_user)
        safe_audit_log(
            'completion_focus_exception_create',
            'order',
            order_id,
            f"{exception['reason']} until {exception.get('expires_at','')}"
        )
        return jsonify({'message': '已设置集中完工例外', 'exception': exception})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/orders/completion-focus-exceptions/<int:exception_id>', methods=['DELETE'])
@check_auth
@check_permission('orders:edit')
def cancel_completion_focus_exception(exception_id):
    data = get_json_body() if request.data else {}
    order_id = OrderFocusService.exception_order_id(exception_id)
    if not order_id:
        return jsonify({'error': '集中完工例外不存在'}), 404
    if not _check_order_data_scope(order_id):
        return jsonify({"error": "无权限访问此订单"}), 403
    OrderFocusService.cancel_exception(
        exception_id,
        g.current_user,
        (data.get('reason') or '').strip(),
    )
    safe_audit_log('completion_focus_exception_cancel', 'completion_focus_exception', exception_id, '')
    return jsonify({'message': '已取消集中完工例外'})


@app.route('/api/orders/<int:order_id>/workpiece-progress', methods=['GET'])
@check_auth
@check_permission('orders:view')
def workpiece_progress(order_id):
    if not _check_order_data_scope(order_id):
        return jsonify({"error": "无权限访问此订单"}), 403
    """返回订单工件进度、卡点和交期风险分析。"""
    try:
        return jsonify(OrderService.get_workpiece_progress(order_id))
    except ValueError as e:
        return jsonify({'error': str(e)}), 404

# ═══════════════════════════════════════════
#  Order Materials (订单物料配方)
# ═══════════════════════════════════════════

@app.route("/api/orders/<int:order_id>/materials", methods=["GET"])
@check_auth

@check_permission("orders:view")
def list_order_materials(order_id):
    """Return the material recipe attached to an order."""
    if not _check_order_data_scope(order_id):
        return jsonify({"error": "无权限访问此订单"}), 403
    materials = OrderService.list_order_materials(order_id)
    return jsonify({"materials": materials})

@app.route("/api/orders/<int:order_id>/materials", methods=["POST"])
@check_auth
@check_permission("orders:edit")
def add_order_material(order_id):
    """Add one material requirement to an order."""
    if not _check_order_data_scope(order_id):
        return jsonify({"error": "无权限访问此订单"}), 403
    material = OrderService.add_order_material(order_id, get_json_body())
    return jsonify({"material": material}), 201

@app.route("/api/orders/<int:order_id>/materials/<int:item_id>", methods=["DELETE"])
@check_auth
@check_permission("orders:edit")
def delete_order_material(order_id, item_id):
    """Delete one material requirement from an order."""
    if not _check_order_data_scope(order_id):
        return jsonify({"error": "无权限访问此订单"}), 403
    OrderService.delete_order_material(order_id, item_id)
    return jsonify({"message": "删除成功"})
