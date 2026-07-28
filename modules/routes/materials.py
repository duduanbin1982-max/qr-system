"""Material and supplier HTTP routes."""
from flask import request, jsonify, g

from modules.route_decorators import (
    app,
    check_auth,
    check_permission,
    get_json_body,
    safe_audit_log,
    validate_json,
)
from modules.services.material_service import MaterialService, SupplierService, MaterialNotFoundError
# ============================================================
# Material CRUD
# ============================================================

@app.route('/api/materials', methods=['GET'])
@check_auth
@check_permission('materials:view')
def list_materials():
    page = max(request.args.get('page', 1, type=int), 1)
    limit = min(max(request.args.get('limit', 100, type=int), 1), 500)
    result = MaterialService.list_materials(page=page, limit=limit)
    return jsonify(result)


@app.route('/api/materials', methods=['POST'])
@check_auth
@check_permission('materials:create')
@validate_json('create_material')
def create_material():
    data = get_json_body()
    mid = MaterialService.create_material(data, g.current_user)
    safe_audit_log('create', 'material', mid, f"material: {data.get('name', '').strip()}")
    return jsonify({'message': 'created', 'id': mid})


@app.route('/api/materials/<int:mid>', methods=['PUT'])
@check_auth
@check_permission('materials:edit')
@validate_json('update_material')
def update_material(mid):
    data = get_json_body()
    MaterialService.update_material(mid, data)
    safe_audit_log('update', 'material', mid, 'material updated')
    return jsonify({'message': 'updated'})


@app.route('/api/materials/<int:mid>/impact', methods=['GET'])
@check_auth
@check_permission('materials:view')
def material_impact(mid):
    return jsonify(MaterialService.check_impact(mid))


@app.route('/api/materials/<int:mid>', methods=['DELETE'])
@check_auth
@check_permission('materials:delete')
def delete_material(mid):
    MaterialService.delete_material(mid)
    safe_audit_log('delete', 'material', mid, f'deleted material {mid}')
    return jsonify({'message': 'deleted'})


# ============================================================
# Material stock movements and logs
# ============================================================

@app.route('/api/materials/<int:mid>/logs', methods=['GET'])
@check_auth
@check_permission('materials:view')
def material_logs(mid):
    page = max(request.args.get('page', 1, type=int), 1)
    limit = min(max(request.args.get('limit', 100, type=int), 1), 500)
    result = MaterialService.get_logs(mid, page=page, limit=limit)
    return jsonify(result)


@app.route('/api/materials/<int:mid>/stock', methods=['POST'])
@check_auth
@check_permission('materials:stock')
def material_stock(mid):
    data = get_json_body()
    change_type = data.get('type', '').strip()
    quantity = float(data.get('quantity', 0))
    remark = data.get('remark', '').strip()
    operator_name = g.current_user.get('name') or g.current_user.get('username', '')
    operator_id = g.current_user.get('id')
    new_qty = MaterialService.stock_change(
        mid,
        change_type,
        quantity,
        remark,
        operator_name,
        operator_id,
    )
    safe_audit_log('stock', 'material', mid, f'{change_type}: {quantity}, new: {new_qty}')
    return jsonify({'ok': True, 'new_quantity': new_qty})


# ============================================================
# Material consumption records
# ============================================================

@app.route('/api/materials/<int:mid>/consumptions', methods=['GET'])
@check_auth
@check_permission('materials:view')
def list_consumptions(mid):
    page = max(request.args.get('page', 1, type=int), 1)
    limit = min(max(request.args.get('limit', 100, type=int), 1), 500)
    result = MaterialService.list_consumptions(mid, page=page, limit=limit)
    return jsonify(result)


@app.route('/api/materials/<int:mid>/consumptions', methods=['POST'])
@check_auth
@check_permission('materials:consume')
def create_consumption(mid):
    data = get_json_body()
    order_id = data.get('order_id') or None
    process_id = data.get('process_id') or None
    quantity = float(data.get('quantity', 0))
    notes = data.get('notes', '').strip()
    uname = g.current_user.get('name', g.current_user.get('username', ''))
    uid = g.current_user.get('id')
    new_qty = MaterialService.create_consumption(
        mid, order_id, process_id, quantity,
        notes=notes, operator_name=uname, user_id=uid
    )
    safe_audit_log('consume', 'material', mid, f'consumed {quantity}, remaining: {new_qty}')
    return jsonify({'ok': True, 'new_quantity': new_qty})


@app.route('/api/material-consumptions/<int:cid>', methods=['DELETE'])
@check_auth
@check_permission('materials:consume')
def delete_consumption(cid):
    data = get_json_body()
    result = MaterialService.delete_consumption(
        cid,
        data.get('reason', ''),
        g.current_user,
    )
    safe_audit_log(
        'unconsume',
        'material',
        result['material_id'],
        f'consumption={cid} reason={data.get("reason", "").strip()[:120]}',
    )
    return jsonify({'ok': True, 'message': '消耗记录已撤销', **result})


# ============================================================
# Supplier management
# ============================================================

@app.route('/api/suppliers', methods=['GET'])
@check_auth
@check_permission('suppliers:view')
def list_suppliers():
    page = max(request.args.get('page', 1, type=int), 1)
    limit = min(max(request.args.get('limit', 100, type=int), 1), 500)
    result = SupplierService.list_suppliers(page=page, limit=limit)
    return jsonify(result)


@app.route('/api/suppliers', methods=['POST'])
@check_auth
@check_permission('suppliers:create')
@validate_json('create_supplier')
def create_supplier():
    data = get_json_body()
    sid = SupplierService.create_supplier(data)
    safe_audit_log('create', 'supplier', sid, f"supplier: {data.get('name', '').strip()}")
    return jsonify({'ok': True, 'id': sid, 'message': '供应商创建成功'})


@app.route('/api/suppliers/<int:sid>', methods=['PUT'])
@check_auth
@check_permission('suppliers:edit')
@validate_json('create_supplier')
def update_supplier(sid):
    data = get_json_body()
    SupplierService.update_supplier(sid, data)
    safe_audit_log('update', 'supplier', sid, 'supplier updated')
    return jsonify({'ok': True, 'message': '更新成功'})


@app.route('/api/suppliers/<int:sid>', methods=['DELETE'])
@check_auth
@check_permission('suppliers:delete')
def delete_supplier(sid):
    SupplierService.delete_supplier(sid)
    safe_audit_log('delete', 'supplier', sid, f'deleted supplier {sid}')
    return jsonify({'ok': True, 'message': '删除成功'})
