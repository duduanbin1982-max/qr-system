"""qr-system — 库存管理（路由层）

注：docstring 中的 Swagger 标记仅供文档参考，项目未集成 Flask-RESTX。
"""
from flask import request, jsonify, g, send_file
from datetime import datetime
from modules.app import app
from modules.db import get_page_size
from modules.middleware.audit import audit_log
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.helpers import get_json_body, parse_pagination
from modules.middleware.validate import validate_json
from modules.middleware.error_handler import handle_unexpected_error
from modules.services.inventory_service import InventoryService


@app.route('/api/inventory', methods=['GET'])
@check_auth
@check_permission('inventory:view')
def list_inventory():
    """
    库存列表
    ---
    tags: [Inventory]
    summary: 库存列表
    parameters:
      - name: keyword
        in: query
        type: string
      - name: low_stock
        in: query
        type: string
        description: 设为1仅显示低库存
    responses: {200: {description: 库存列表}}
    security: [{Bearer: []}]
    """
    keyword = request.args.get('keyword', '')
    low_stock = request.args.get('low_stock', '0') == '1'
    location = request.args.get('location', '')
    page = max(request.args.get('page', 1, type=int), 1)
    limit = min(max(request.args.get('limit', 100, type=int), 1), 500)
    return jsonify(InventoryService.list_items(keyword, low_stock, location, page, limit))


@app.route('/api/inventory', methods=['POST'])
@check_auth
@check_permission('inventory:create')
@validate_json('create_inventory')
def create_inventory():
    """
    创建库存项
    ---
    tags: [Inventory]
    summary: 创建库存项
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            product_model:
              type: string
            product_name:
              type: string
            quantity:
              type: number
            unit:
              type: string
            safety_stock:
              type: number
            remark:
              type: string
    responses: {200: {description: 创建成功}}
    security: [{Bearer: []}]
    """
    data = get_json_body()
    try:
        item_id = InventoryService.create_item(data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    try:
        audit_log('create_inventory', 'inventory', item_id, data.get('product_model'))
    except Exception as e:
        app.logger.warning('audit_log failed: %s', e)
    return jsonify({'message': '创建成功', 'id': item_id})


@app.route('/api/inventory/<int:id>', methods=['PUT'])
@check_auth
@check_permission('inventory:edit')
@validate_json('update_inventory')
def update_inventory(id):
    """
    更新库存
    ---
    tags: [Inventory]
    summary: 更新库存项
    parameters:
      - name: id
        in: path
        type: integer
        required: true
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            product_model:
              type: string
            product_name:
              type: string
            quantity:
              type: number
            safety_stock:
              type: number
    responses: {200: {description: 更新成功}}
    security: [{Bearer: []}]
    """
    data = get_json_body()
    try:
        InventoryService.update_item(id, data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 409 if '已存在' in str(e) else 400
    try:
        audit_log('update_inventory', 'inventory', id)
    except Exception as e:
        app.logger.warning('audit_log failed: %s', e)
    return jsonify({'message': '更新成功'})


@app.route('/api/inventory/<int:id>', methods=['DELETE'])
@check_auth
@check_permission('inventory:delete')
def delete_inventory(id):
    """
    删除库存项
    ---
    tags: [Inventory]
    summary: 删除库存项
    parameters:
      - name: id
        in: path
        type: integer
        required: true
    responses: {200: {description: 删除成功}}
    security: [{Bearer: []}]
    """
    try:
        InventoryService.delete_item(id)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    try:
        audit_log('delete_inventory', 'inventory', id)
    except Exception as e:
        app.logger.warning('audit_log failed: %s', e)
    return jsonify({'message': '删除成功'})


@app.route('/api/inventory/stock-in', methods=['POST'])
@check_auth
@check_permission('inventory:edit')
@validate_json('stock_movement')
def stock_in():
    """
    入库
    ---
    tags: [Inventory]
    summary: 入库
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [inventory_id, quantity]
          properties:
            inventory_id: {type: integer}
            quantity: {type: number}
            order_id: {type: integer}
            order_no: {type: string}
            remark: {type: string}
    responses: {200: {description: 入库成功}}
    security: [{Bearer: []}]
    """
    data = get_json_body()
    inv_id = data.get('inventory_id')
    try:
        qty = float(data.get('quantity', 0))
    except (ValueError, TypeError):
        return jsonify({'error': '数量必须为数字'}), 400
    if not inv_id or qty <= 0:
        return jsonify({'error': '参数错误'}), 400
    try:
        InventoryService.stock_in(inv_id, qty, order_id=data.get('order_id'), order_no=data.get('order_no', ''), remark=data.get('remark', ''), operator_id=g.current_user['id'], operator_name=g.current_user['name'])
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    try:
        audit_log('stock_in', 'inventory', inv_id, f'+{qty}')
    except Exception as e:
        app.logger.warning('audit_log failed: %s', e)
    return jsonify({'message': '入库成功'})


@app.route('/api/inventory/stock-out', methods=['POST'])
@check_auth
@check_permission('inventory:edit')
@validate_json('stock_movement')
def stock_out():
    """
    出库
    ---
    tags: [Inventory]
    summary: 出库
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          required: [inventory_id, quantity]
          properties:
            inventory_id: {type: integer}
            quantity: {type: number}
            order_id: {type: integer}
            order_no: {type: string}
            remark: {type: string}
    responses:
      200: {description: 出库成功}
      400: {description: 库存不足}
    security: [{Bearer: []}]
    """
    data = get_json_body()
    inv_id = data.get('inventory_id')
    try:
        qty = float(data.get('quantity', 0))
    except (ValueError, TypeError):
        return jsonify({'error': '数量必须为数字'}), 400
    if not inv_id or qty <= 0:
        return jsonify({'error': '参数错误'}), 400
    try:
        InventoryService.stock_out(inv_id, qty, order_id=data.get('order_id'), order_no=data.get('order_no', ''), remark=data.get('remark', ''), operator_id=g.current_user['id'], operator_name=g.current_user['name'])
    except ValueError as e:
        code = 400 if '不足' in str(e) else 404
        return jsonify({'error': str(e)}), code
    try:
        audit_log('stock_out', 'inventory', inv_id, f'-{qty}')
    except Exception as e:
        app.logger.warning('audit_log failed: %s', e)
    return jsonify({'message': '出库成功'})


@app.route('/api/inventory/logs', methods=['GET'])
@check_auth
@check_permission('inventory:view')
def inventory_logs():
    """
    库存日志
    ---
    tags: [Inventory]
    summary: 出入库流水
    parameters:
      - name: inventory_id
        in: query
        type: string
      - name: type
        in: query
        type: string
        description: stock-in / stock-out
      - name: page
        in: query
        type: integer
        default: 1
      - name: limit
        in: query
        type: integer
        default: 20
    responses: {200: {description: 日志列表}}
    security: [{Bearer: []}]
    """
    inv_id = request.args.get('inventory_id', '')
    type_filter = request.args.get('type', '')
    p = parse_pagination()
    page, limit = p['page'], p['limit']
    return jsonify(InventoryService.get_logs(inv_id, type_filter, page, limit))


@app.route('/api/inventory/alerts', methods=['GET'])
@check_auth
@check_permission('inventory:view')
def inventory_alerts():
    """
    库存预警
    ---
    tags: [Inventory]
    summary: 低库存预警
    responses: {200: {description: 预警列表}}
    security: [{Bearer: []}]
    """
    return jsonify(InventoryService.get_alerts())


@app.route('/api/inventory/<int:id>/adjust', methods=['POST'])
@check_auth
@check_permission('inventory:edit')
def inventory_adjust(id):
    try:
        data = request.get_json() or {}
        actual_qty = data.get('actual_qty', 0)
        remark = data.get('remark', '')
        user = g.current_user if hasattr(g, 'current_user') else {}
        result = InventoryService.stock_adjust(
            id, actual_qty,
            operator_id=user.get('id'),
            operator_name=user.get('name', user.get('username', '')),
            remark=remark
        )
        audit_log('inventory_adjust', 'inventory', id, f'qty adjusted')
        return jsonify({'ok': True, **result})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/inventory/export', methods=['GET'])
@check_auth
@check_permission('inventory:view')
def inventory_export():
    try:
        output = InventoryService.export_inventory(
            keyword=request.args.get('keyword', ''),
            low_stock=request.args.get('low_stock', '') == '1',
        )
        output.seek(0)
        return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                         as_attachment=True, download_name=f'inventory_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx')
    except Exception as e:
        return handle_unexpected_error(e, 'export operation')


@app.route('/api/inventory/logs/export', methods=['GET'])
@check_auth
@check_permission('inventory:view')
def inventory_logs_export():
    try:
        output = InventoryService.export_logs(
            inv_id=request.args.get('inventory_id', ''),
            type_filter=request.args.get('type', ''),
            date_from=request.args.get('from', ''),
            date_to=request.args.get('to', ''),
        )
        output.seek(0)
        return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                         as_attachment=True, download_name=f'inventory_logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx')
    except Exception as e:
        return handle_unexpected_error(e, 'export operation')





# ── P2: ABC 分类 ──
@app.route("/api/inventory/abc", methods=["POST"])
@check_auth
@check_permission("inventory:edit")
def classify_abc():
    try:
        result = InventoryService.classify_abc()
        return jsonify(result)
    except Exception as e:
        return handle_unexpected_error(e, "abc classification")


# ── P2: 周转率 ──
@app.route("/api/inventory/turnover", methods=["GET"])
@check_auth
@check_permission("inventory:view")
def inventory_turnover():
    return jsonify(InventoryService.get_turnover())


# ── P2: 安全库存建议 ──
@app.route("/api/inventory/safe-stock-suggestions", methods=["GET"])
@check_auth
@check_permission("inventory:view")
def safe_stock_suggestions():
    return jsonify(InventoryService.suggest_safe_stock())


# ── P3: 批次追踪 ──
@app.route("/api/inventory/batch-tracking", methods=["GET"])
@check_auth
@check_permission("inventory:view")
def batch_tracking():
    item_id = request.args.get("item_id", type=int)
    lot_no = request.args.get("lot_no", "")
    return jsonify(InventoryService.get_batch_tracking(item_id=item_id, lot_no=lot_no))


# ── P3: 库位管理 ──
@app.route("/api/inventory/locations", methods=["GET"])
@check_auth
@check_permission("inventory:view")
def inventory_locations():
    return jsonify(InventoryService.get_locations())


@app.route("/api/inventory/locations/move", methods=["POST"])
@check_auth
@check_permission("inventory:edit")
def move_locations():
    data = get_json_body()
    try:
        result = InventoryService.update_location(
            item_ids=data.get("item_ids", []),
            new_location=data.get("location", "")
        )
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# ── P3: 盘点任务 ──

@app.route("/api/inventory/<int:id>/impact", methods=["GET"])
@check_auth
@check_permission("inventory:view")
def inventory_impact(id):
    """Get impact analysis for deleting an inventory item."""
    try:
        return jsonify(InventoryService.get_impact(id))
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

@app.route("/api/inventory/count-task", methods=["POST"])
@check_auth
@check_permission("inventory:edit")
def create_count_task():
    return jsonify(InventoryService.create_count_task())


@app.route("/api/inventory/count-status", methods=["GET"])
@check_auth
@check_permission("inventory:view")
def count_status():
    return jsonify(InventoryService.get_count_status())


@app.route("/api/inventory/<int:id>/count", methods=["POST"])
@check_auth
@check_permission("inventory:edit")
def submit_count(id):
    data = get_json_body()
    try:
        result = InventoryService.submit_count(
            item_id=id,
            actual_qty=data.get("actual_qty", 0),
            remark=data.get("remark", "")
        )
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/inventory/stats', methods=['GET'])
@check_auth
@check_permission('inventory:view')
def inventory_stats():
    """
    库存统计
    ---
    tags: [Inventory]
    summary: 库存统计
    responses: {200: {description: 统计数据}}
    security: [{Bearer: []}]
    """
    return jsonify(InventoryService.get_stats())
