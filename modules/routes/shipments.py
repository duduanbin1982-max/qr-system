"""qr-system — 出库管理（路由层）"""
from flask import request, jsonify, g, send_file
from datetime import datetime
from modules.app import app
from modules.db import get_page_size
from modules.middleware.audit import audit_log
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.helpers import get_json_body, parse_pagination
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
    try:
        sid, sno = ShipmentService.create_shipment(data, g.current_user['name'])
    except ValueError as e:
        return jsonify({'error': str(e)}), 409 if '已存在' in str(e) else 400
    try:
        audit_log('create', 'shipment', sid, f'创建出库单 {sno}')
    except Exception:
        pass
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
    try:
        ShipmentService.update_shipment(shipment_id, data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404 if '不存在' in str(e) else 400
    try:
        audit_log('update', 'shipment', shipment_id, '更新出库单')
    except Exception:
        pass
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
    try:
        audit_log('delete', 'shipment', shipment_id, f'删除出库单 {sno}')
    except Exception:
        pass
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
    try:
        audit_log('complete', 'shipment', shipment_id, '完成出库 ' + sno)
    except Exception:
        pass
    return jsonify({'message': '出库完成'})



# ── P1: 批量操作 ──
@app.route("/api/shipments/batch-complete", methods=["POST"])
@check_auth
@check_permission("shipments:edit")
def batch_complete_shipments():
    data = get_json_body()
    try:
        result = ShipmentService.batch_complete(
            ids=data.get("ids", []),
            current_user={"id": g.current_user.get("id"), "name": g.current_user.get("name")}
        )
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/shipments/batch-delete", methods=["POST"])
@check_auth
@check_permission("shipments:delete")
def batch_delete_shipments():
    data = get_json_body()
    try:
        result = ShipmentService.batch_delete(
            ids=data.get("ids", []),
            current_user={"id": g.current_user.get("id"), "name": g.current_user.get("name")}
        )
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# ── P1: 物流信息 ──
@app.route("/api/shipments/<int:shipment_id>/logistics", methods=["PUT"])
@check_auth
@check_permission("shipments:edit")
def update_shipment_logistics(shipment_id):
    data = get_json_body()
    try:
        ShipmentService.update_logistics(shipment_id, data)
        return jsonify({"message": "物流信息更新成功"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# ── P1: 取消出库单 ──
@app.route("/api/shipments/<int:shipment_id>/receive", methods=["POST"])
@check_auth
@check_permission("shipments:edit")
def receive_shipment(shipment_id):
    data = get_json_body()
    try:
        sno = ShipmentService.receive_shipment(
            shipment_id, g.current_user,
            receiver=data.get("receiver", ""),
            receive_date=data.get("receive_date", "")
        )
        audit_log("receive", "shipment", shipment_id, "签收 " + sno)
        return jsonify({"message": "签收成功", "shipment_no": sno})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/shipments/<int:shipment_id>/payment", methods=["POST"])
@check_auth
@check_permission("shipments:edit")
def record_shipment_payment(shipment_id):
    data = get_json_body()
    try:
        sno = ShipmentService.record_payment(
            shipment_id, g.current_user,
            amount=data.get("amount", 0),
            method=data.get("method", ""),
            remark=data.get("remark", "")
        )
        audit_log("payment", "shipment", shipment_id, f"收款 {data.get('amount',0)} {sno}")
        return jsonify({"message": "收款成功", "shipment_no": sno})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/shipments/<int:shipment_id>/cancel", methods=["POST"])
@check_auth
@check_permission("shipments:edit")
def cancel_shipment(shipment_id):
    try:
        sno = ShipmentService.cancel_shipment(
            shipment_id,
            current_user={"id": g.current_user.get("id"), "name": g.current_user.get("name")}
        )
        return jsonify({"message": "出库单已取消", "shipment_no": sno})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400



# P2: stats
@app.route("/api/shipments/stats", methods=["GET"])
@check_auth
@check_permission("shipments:view")
def shipment_stats():
    return jsonify(ShipmentService.get_stats())



@app.route("/api/shipments/order-items/<int:order_id>", methods=["GET"])
@check_auth
@check_permission("shipments:view")
def shipment_order_items(order_id):
    try:
        return jsonify(ShipmentService.get_order_stock(order_id))
    except ValueError as e:
        return jsonify({"error": str(e)}), 404

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
    from modules.export_utils import style_header, auto_width, THIN_BORDER, CELL_ALIGN
    from openpyxl import Workbook
    from io import BytesIO
    keyword = request.args.get("keyword", "")
    status = request.args.get("status", "")
    result = ShipmentService.list_shipments(keyword=keyword, status=status, page=1, limit=99999)
    items = result.get("shipments", [])
    wb = Workbook()
    ws = wb.active
    ws.title = "发货清单"
    headers = ["出库单号", "客户", "联系人", "电话", "地址", "状态", "总数量", "物流公司", "运单号", "应收金额", "已收金额", "收款状态", "备注", "创建时间", "完成时间"]
    style_header(ws, headers)
    status_map = {"pending": "待出库", "partial": "部分出库", "completed": "已出库", "cancelled": "已取消"}
    for row_idx, item in enumerate(items, 2):
        pay_map = {"unpaid":"未收款","partial":"部分收","paid":"已收清"}
        vals = [item.get("shipment_no",""), item.get("customer",""), item.get("contact_person",""), item.get("contact_phone",""), item.get("address",""), status_map.get(item.get("status",""), item.get("status","")), item.get("total_quantity",0), item.get("logistics_company",""), item.get("tracking_no",""), item.get("receivable_amount",0), item.get("paid_amount",0), pay_map.get(item.get("payment_status",""), item.get("payment_status","") or "未收款"), item.get("remark",""), (item.get("created_at") or "")[:19], (item.get("completed_at") or "")[:19]]
        for col_idx, val in enumerate(vals, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=val)
            cell.border = THIN_BORDER
            cell.alignment = CELL_ALIGN
    auto_width(ws)
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return send_file(output, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", as_attachment=True, download_name=f"shipments_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
