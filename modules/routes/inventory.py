"""qr-system — 库存管理（路由层）

注：docstring 中的 Swagger 标记仅供文档参考，项目未集成 Flask-RESTX。
"""
from flask import request, jsonify, g
from modules.app import app
from modules.db import get_page_size
from modules.middleware.auth import check_auth, check_permission, audit_log
from modules.middleware.helpers import get_json_body, parse_pagination
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
    return jsonify(InventoryService.list_items(keyword, low_stock))


@app.route('/api/inventory', methods=['POST'])
@check_auth
@check_permission('inventory:create')
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
    except Exception:
        pass
    return jsonify({'message': '创建成功'})


@app.route('/api/inventory/<int:id>', methods=['PUT'])
@check_auth
@check_permission('inventory:edit')
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
    except Exception:
        pass
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
    except Exception:
        pass
    return jsonify({'message': '删除成功'})


@app.route('/api/inventory/stock-in', methods=['POST'])
@check_auth
@check_permission('inventory:edit')
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
    qty = data.get('quantity', 0)
    if not inv_id or qty <= 0:
        return jsonify({'error': '参数错误'}), 400
    try:
        InventoryService.stock_in(inv_id, qty, order_id=data.get('order_id'), order_no=data.get('order_no', ''), remark=data.get('remark', ''), operator_id=g.current_user['id'], operator_name=g.current_user['name'])
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    try:
        audit_log('stock_in', 'inventory', inv_id, f'+{qty}')
    except Exception:
        pass
    return jsonify({'message': '入库成功'})


@app.route('/api/inventory/stock-out', methods=['POST'])
@check_auth
@check_permission('inventory:edit')
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
    qty = data.get('quantity', 0)
    if not inv_id or qty <= 0:
        return jsonify({'error': '参数错误'}), 400
    try:
        InventoryService.stock_out(inv_id, qty, order_id=data.get('order_id'), order_no=data.get('order_no', ''), remark=data.get('remark', ''), operator_id=g.current_user['id'], operator_name=g.current_user['name'])
    except ValueError as e:
        code = 400 if '不足' in str(e) else 404
        return jsonify({'error': str(e)}), code
    try:
        audit_log('stock_out', 'inventory', inv_id, f'-{qty}')
    except Exception:
        pass
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
