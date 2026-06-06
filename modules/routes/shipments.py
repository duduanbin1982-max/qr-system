"""qr-system — 出库管理（路由层）"""
from flask import request, jsonify, g
from modules.app import app
from modules.db import get_page_size
from modules.middleware.auth import check_auth, check_permission, audit_log
from modules.services.shipment_service import ShipmentService


@app.route('/api/shipments/draft', methods=['GET'])
@check_auth
@check_permission('shipments:view')
def shipment_draft_no():
    """
    生成出库单号
    ---
    tags: [Shipments]
    summary: 生成出库单号
    responses: {200: {description: 出库单号}}
    security: [{Bearer: []}]
    """
    return jsonify({'shipment_no': ShipmentService.generate_no()})


@app.route('/api/shipments', methods=['GET'])
@check_auth
@check_permission('shipments:view')
def list_shipments():
    """
    出库单列表
    ---
    tags: [Shipments]
    summary: 出库单列表
    parameters:
      - name: keyword
        in: query
        type: string
      - name: status
        in: query
        type: string
      - name: page
        in: query
        type: integer
        default: 1
      - name: limit
        in: query
        type: integer
        default: 20
    responses: {200: {description: 出库单列表}}
    security: [{Bearer: []}]
    """
    keyword = request.args.get('keyword', '')
    status = request.args.get('status', '')
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', get_page_size(), type=int)
    return jsonify(ShipmentService.list_shipments(keyword, status, page, limit))


@app.route('/api/shipments', methods=['POST'])
@check_auth
@check_permission('shipments:create')
def create_shipment():
    """
    创建出库单
    ---
    tags: [Shipments]
    summary: 创建出库单
    parameters:
      - name: body
        in: body
        required: true
        schema:
          type: object
          properties:
            items:
              type: array
              items:
                type: object
                properties:
                  inventory_id: {type: integer}
                  quantity: {type: number}
                  order_id: {type: integer}
            remark: {type: string}
    responses: {200: {description: 创建成功}}
    security: [{Bearer: []}]
    """
    data = request.get_json(force=True, silent=True) or {}
    if not data:
        return jsonify({'error': '请求数据为空'}), 400
    try:
        sid, sno = ShipmentService.create_shipment(data, g.current_user['name'])
    except ValueError as e:
        return jsonify({'error': str(e)}), 409 if '已存在' in str(e) else 400
    audit_log('create', 'shipment', sid, f'创建出库单 {sno}')
    return jsonify({'message': '出库单创建成功', 'id': sid, 'shipment_no': sno})


@app.route('/api/shipments/<int:shipment_id>', methods=['GET'])
@check_auth
@check_permission('shipments:view')
def get_shipment(shipment_id):
    """
    出库单详情
    ---
    tags: [Shipments]
    summary: 出库单详情
    parameters:
      - name: shipment_id
        in: path
        type: integer
        required: true
    responses: {200: {description: 出库单详情}}
    security: [{Bearer: []}]
    """
    shipment = ShipmentService.get_shipment(shipment_id)
    if not shipment:
        return jsonify({'error': '出库单不存在'}), 404
    return jsonify(shipment)


@app.route('/api/shipments/<int:shipment_id>', methods=['PUT'])
@check_auth
@check_permission('shipments:edit')
def update_shipment(shipment_id):
    """
    更新出库单
    ---
    tags: [Shipments]
    summary: 更新出库单
    parameters:
      - name: shipment_id
        in: path
        type: integer
        required: true
      - name: body
        in: body
        required: true
        schema:
          type: object
    responses: {200: {description: 更新成功}}
    security: [{Bearer: []}]
    """
    data = request.get_json(force=True, silent=True) or {}
    try:
        ShipmentService.update_shipment(shipment_id, data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404 if '不存在' in str(e) else 400
    audit_log('update', 'shipment', shipment_id, '更新出库单')
    return jsonify({'message': '更新成功'})


@app.route('/api/shipments/<int:shipment_id>', methods=['DELETE'])
@check_auth
@check_permission('shipments:delete')
def delete_shipment(shipment_id):
    """
    删除出库单
    ---
    tags: [Shipments]
    summary: 删除出库单
    parameters:
      - name: shipment_id
        in: path
        type: integer
        required: true
    responses: {200: {description: 删除成功}}
    security: [{Bearer: []}]
    """
    try:
        sno = ShipmentService.delete_shipment(shipment_id, g.current_user)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    audit_log('delete', 'shipment', shipment_id, f'删除出库单 {sno}')
    return jsonify({'message': '删除成功'})


@app.route('/api/shipments/<int:shipment_id>/complete', methods=['POST'])
@check_auth
@check_permission('shipments:edit')
def complete_shipment(shipment_id):
    """
    完成出库
    ---
    tags: [Shipments]
    summary: 完成出库（扣减库存）
    parameters:
      - name: shipment_id
        in: path
        type: integer
        required: true
    responses:
      200: {description: 出库完成}
      409: {description: 已完成的出库单}
      400: {description: 库存不足}
    security: [{Bearer: []}]
    """
    try:
        sno = ShipmentService.complete_shipment(shipment_id, g.current_user)
    except ValueError as e:
        msg = str(e)
        return jsonify({'error': msg}), 409 if '已完成' in msg else (400 if '出库失败' in msg else 404)
    audit_log('complete', 'shipment', shipment_id, '完成出库 ' + sno)
    return jsonify({'message': '出库完成'})
