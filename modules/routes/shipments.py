"""qr-system — 出库管理（路由层）"""
from flask import request, jsonify, g, send_file
from datetime import datetime
from modules.route_decorators import (
    app,
    check_auth,
    check_permission,
    get_json_body,
    parse_pagination,
    safe_audit_log,
    has_permission,
)
from modules.services.setting_service import SettingsService
from modules.services.shipment_service import ShipmentService


@app.route('/api/shipments/draft', methods=['GET'])
@check_auth
@check_permission('shipments:create')
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
    p = parse_pagination()
    page, limit = p['page'], p['limit']
    sort_by = request.args.get('sort_by', 'created_at')
    sort_dir = request.args.get('sort_dir', 'desc')
    return jsonify(ShipmentService.list_shipments(keyword, status, page, limit, sort_by, sort_dir))


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
    data = get_json_body()
    if not data:
        return jsonify({'error': '请求数据为空'}), 400
    sid, sno = ShipmentService.create_shipment(
        data,
        g.current_user,
        allow_unlinked=has_permission(g.current_user, 'shipments:unlinked'),
    )
    safe_audit_log('create', 'shipment', sid, f'创建出库单 {sno}')
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
    data = get_json_body()
    ShipmentService.update_shipment(shipment_id, data, g.current_user)
    safe_audit_log('update', 'shipment', shipment_id, '更新出库单')
    return jsonify({'message': '更新成功'})


@app.route('/api/shipments/<int:shipment_id>', methods=['DELETE'])
@check_auth
@check_permission('shipments:cancel')
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
    sno = ShipmentService.delete_shipment(shipment_id, g.current_user)
    shipment = ShipmentService.get_shipment(shipment_id)
    safe_audit_log('cancel', 'shipment', shipment_id, f'兼容删除入口取消/冲销出库单 {sno}')
    return jsonify({
        'message': '出库单已取消或冲销',
        'shipment_no': sno,
        'status': shipment['status'],
    })


@app.route('/api/shipments/<int:shipment_id>/complete', methods=['POST'])
@check_auth
@check_permission('shipments:complete')
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
    sno = ShipmentService.complete_shipment(shipment_id, g.current_user)
    safe_audit_log('complete', 'shipment', shipment_id, '完成出库 ' + sno)
    return jsonify({'message': '出库完成'})



# ── P1: 批量操作 ──
@app.route("/api/shipments/batch-complete", methods=["POST"])
@check_auth
@check_permission("shipments:complete")
def batch_complete_shipments():
    data = get_json_body()
    result = ShipmentService.batch_complete(
        ids=data.get("ids", []), current_user=g.current_user
    )
    for item in result["success"]:
        safe_audit_log("complete", "shipment", item["id"], "批量完成出库 " + item["shipment_no"])
    return jsonify(result)


@app.route("/api/shipments/batch-delete", methods=["POST"])
@check_auth
@check_permission("shipments:cancel")
def batch_delete_shipments():
    data = get_json_body()
    result = ShipmentService.batch_delete(ids=data.get("ids", []), current_user=g.current_user)
    for item in result["success"]:
        safe_audit_log("cancel", "shipment", item["id"], "批量取消/冲销 " + item["shipment_no"])
    return jsonify(result)


# ── P1: 物流信息 ──
@app.route("/api/shipments/<int:shipment_id>/logistics", methods=["PUT"])
@check_auth
@check_permission("shipments:logistics")
def update_shipment_logistics(shipment_id):
    data = get_json_body()
    ShipmentService.update_logistics(shipment_id, data, g.current_user)
    safe_audit_log("logistics", "shipment", shipment_id, "更新物流信息")
    return jsonify({"message": "物流信息更新成功"})


# ── P1: 取消出库单 ──
@app.route("/api/shipments/<int:shipment_id>/receive", methods=["POST"])
@check_auth
@check_permission("shipments:receive")
def receive_shipment(shipment_id):
    data = get_json_body()
    sno = ShipmentService.receive_shipment(
        shipment_id, g.current_user,
        receiver=data.get("receiver", ""), receive_date=data.get("receive_date", "")
    )
    safe_audit_log("receive", "shipment", shipment_id, "签收 " + sno)
    return jsonify({"message": "签收成功", "shipment_no": sno})

@app.route("/api/shipments/<int:shipment_id>/payment", methods=["POST"])
@check_auth
@check_permission("shipments:finance")
def record_shipment_payment(shipment_id):
    data = get_json_body()
    sno = ShipmentService.record_payment(
        shipment_id, g.current_user, amount=data.get("amount", 0),
        method=data.get("method", ""), remark=data.get("remark", ""),
        payment_date=data.get("payment_date", ""),
        idempotency_key=data.get("idempotency_key", "") or request.headers.get("Idempotency-Key", ""),
    )
    safe_audit_log("payment", "shipment", shipment_id, f"收款 {data.get('amount',0)} {sno}")
    return jsonify({"message": "收款成功", "shipment_no": sno})


@app.route("/api/shipments/<int:shipment_id>/refund", methods=["POST"])
@check_auth
@check_permission("shipments:finance")
def refund_shipment_payment(shipment_id):
    data = get_json_body()
    sno = ShipmentService.refund_payment(
        shipment_id, g.current_user, amount=data.get("amount", 0),
        method=data.get("method", ""), remark=data.get("remark", ""),
        payment_date=data.get("payment_date", ""),
        idempotency_key=data.get("idempotency_key", "") or request.headers.get("Idempotency-Key", ""),
    )
    safe_audit_log("refund", "shipment", shipment_id, f"退款 {data.get('amount',0)} {sno}")
    return jsonify({"message": "退款成功", "shipment_no": sno})


@app.route(
    "/api/shipments/<int:shipment_id>/payments/<int:payment_id>/reverse",
    methods=["POST"],
)
@check_auth
@check_permission("shipments:finance")
def reverse_shipment_payment(shipment_id, payment_id):
    data = get_json_body()
    sno = ShipmentService.reverse_payment(
        shipment_id, payment_id, g.current_user,
        idempotency_key=data.get("idempotency_key", "") or request.headers.get("Idempotency-Key", ""),
    )
    safe_audit_log("payment_reverse", "shipment", shipment_id, f"冲销收付款流水 {payment_id} {sno}")
    return jsonify({"message": "收付款流水已冲销", "shipment_no": sno})

@app.route("/api/shipments/<int:shipment_id>/cancel", methods=["POST"])
@check_auth
@check_permission("shipments:cancel")
def cancel_shipment(shipment_id):
    data = get_json_body()
    sno = ShipmentService.cancel_shipment(
        shipment_id, current_user=g.current_user, reason=data.get("reason", "")
    )
    shipment = ShipmentService.get_shipment(shipment_id)
    safe_audit_log(
        "cancel" if shipment["status"] == "cancelled" else "reverse",
        "shipment", shipment_id,
        ("取消 " if shipment["status"] == "cancelled" else "冲销 ") + sno,
    )
    return jsonify({
        "message": "出库单已取消" if shipment["status"] == "cancelled" else "出库单已冲销",
        "shipment_no": sno,
        "status": shipment["status"],
    })


@app.route("/api/shipments/<int:shipment_id>/events", methods=["GET"])
@check_auth
@check_permission("shipments:view")
def shipment_events(shipment_id):
    return jsonify({"events": ShipmentService.get_events(shipment_id)})


@app.route("/api/shipments/<int:shipment_id>/payments", methods=["GET"])
@check_auth
@check_permission("shipments:view")
def shipment_payments(shipment_id):
    return jsonify({"payments": ShipmentService.get_payments(shipment_id)})



# P2: stats
@app.route("/api/shipments/stats", methods=["GET"])
@check_auth
@check_permission("shipments:view")
def shipment_stats():
    return jsonify(ShipmentService.get_stats())




@app.route("/api/shipments/<int:shipment_id>/impact", methods=["GET"])
@check_auth
@check_permission("shipments:view")
def shipment_impact(shipment_id):
    """Check impact before deleting a shipment."""
    return jsonify(ShipmentService.get_impact(shipment_id))

@app.route("/api/shipments/order-items/<int:order_id>", methods=["GET"])
@check_auth
@check_permission("shipments:view")
def shipment_order_items(order_id):
    return jsonify(ShipmentService.get_order_stock(order_id))

# P2: customer history
@app.route("/api/shipments/customer-history", methods=["GET"])
@check_auth
@check_permission("shipments:view")
def customer_shipment_history():
    customer = request.args.get("customer", "")
    if not customer:
        return jsonify({"error": "请提供客户名称"}), 400
    limit = request.args.get("limit", 50, type=int)
    return jsonify(ShipmentService.get_customer_history(customer, limit))


# P2: Excel export
@app.route("/api/shipments/export", methods=["GET"])
@check_auth
@check_permission("shipments:view")
def export_shipments():
    keyword = request.args.get("keyword", "")
    status = request.args.get("status", "")
    output = ShipmentService.export_shipments(keyword=keyword, status=status)
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"shipments_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
    )
