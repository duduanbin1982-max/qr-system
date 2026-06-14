"""
qr-system ? ???????Refactored: all SQL ? MaterialService?
"""
from flask import request, jsonify, g

from modules.app import app
from modules.middleware.auth import check_auth, check_permission, audit_log
from modules.middleware.validate import validate_json
from modules.middleware.error_handler import handle_unexpected_error
from modules.middleware.helpers import get_json_body
from modules.services.material_service import MaterialService, SupplierService


# ============================================================
# ?? CRUD
# ============================================================

@app.route('/api/materials', methods=['GET'])
@check_auth
@check_permission('materials:view')
def list_materials():
    try:
        page = max(request.args.get('page', 1, type=int), 1)
        limit = min(max(request.args.get('limit', 100, type=int), 1), 500)
        result = MaterialService.list_materials(page=page, limit=limit)
        return jsonify(result)
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/materials', methods=['POST'])
@check_auth
@check_permission('materials:manage')
@validate_json('create_material')
def create_material():
    data = get_json_body()
    try:
        mid = MaterialService.create_material(data)
        try:
            audit_log('create', 'material', mid, f"material: {data.get('name', '').strip()}")
        except Exception:
            pass
        return jsonify({'message': 'created', 'id': mid})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/materials/<int:mid>', methods=['PUT'])
@check_auth
@check_permission('materials:manage')
@validate_json('update_material')
def update_material(mid):
    data = get_json_body()
    try:
        MaterialService.update_material(mid, data)
        try:
            audit_log('update', 'material', mid, 'material updated')
        except Exception:
            pass
        return jsonify({'message': 'updated'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/materials/<int:mid>/impact', methods=['GET'])
@check_auth
@check_permission('materials:view')
def material_impact(mid):
    try:
        return jsonify(MaterialService.check_impact(mid))
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@app.route('/api/materials/<int:mid>', methods=['DELETE'])
@check_auth
@check_permission('materials:manage')
def delete_material(mid):
    try:
        MaterialService.delete_material(mid)
        # Get name for audit log ? re-fetch not needed since delete_material validates first
        try:
            audit_log('delete', 'material', mid, f'deleted material {mid}')
        except Exception:
            pass
        return jsonify({'message': 'deleted'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 404 if '???' in str(e) else 409
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


# ============================================================
# ???????/?????
# ============================================================

@app.route('/api/materials/<int:mid>/logs', methods=['GET'])
@check_auth
@check_permission('materials:view')
def material_logs(mid):
    try:
        page = max(request.args.get('page', 1, type=int), 1)
        limit = min(max(request.args.get('limit', 100, type=int), 1), 500)
        result = MaterialService.get_logs(mid, page=page, limit=limit)
        return jsonify(result)
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/materials/<int:mid>/stock', methods=['POST'])
@check_auth
@check_permission('materials:manage')
def material_stock(mid):
    data = get_json_body()
    change_type = data.get('type', '').strip()
    quantity = float(data.get('quantity', 0))
    remark = data.get('remark', '').strip()
    operator_name = data.get('operator_name', '').strip()
    try:
        new_qty = MaterialService.stock_change(mid, change_type, quantity, remark, operator_name)
        try:
            audit_log('stock', 'material', mid, f'{change_type}: {quantity}, new: {new_qty}')
        except Exception:
            pass
        return jsonify({'ok': True, 'new_quantity': new_qty})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


# ============================================================
# ??????????
# ============================================================

@app.route('/api/materials/<int:mid>/consumptions', methods=['GET'])
@check_auth
@check_permission('materials:view')
def list_consumptions(mid):
    try:
        page = max(request.args.get('page', 1, type=int), 1)
        limit = min(max(request.args.get('limit', 100, type=int), 1), 500)
        result = MaterialService.list_consumptions(mid, page=page, limit=limit)
        return jsonify(result)
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/materials/<int:mid>/consumptions', methods=['POST'])
@check_auth
@check_permission('materials:manage')
def create_consumption(mid):
    data = get_json_body()
    order_id = data.get('order_id') or None
    process_id = data.get('process_id') or None
    quantity = float(data.get('quantity', 0))
    notes = data.get('notes', '').strip()
    uname = g.current_user.get('name', g.current_user.get('username', ''))
    uid = g.current_user.get('id')
    try:
        new_qty = MaterialService.create_consumption(
            mid, order_id, process_id, quantity,
            notes=notes, operator_name=uname, user_id=uid
        )
        try:
            audit_log('consume', 'material', mid, f'consumed {quantity}, remaining: {new_qty}')
        except Exception:
            pass
        return jsonify({'ok': True, 'new_quantity': new_qty})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/material-consumptions/<int:cid>', methods=['DELETE'])
@check_auth
@check_permission('materials:manage')
def delete_consumption(cid):
    try:
        MaterialService.delete_consumption(cid)
        try:
            audit_log('unconsume', 'material', cid, f'undone consumption {cid}')
        except Exception:
            pass
        return jsonify({'ok': True, 'message': '?????'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


# ============================================================
# ?????
# ============================================================

@app.route('/api/suppliers', methods=['GET'])
@check_auth
@check_permission('materials:view')
def list_suppliers():
    try:
        page = max(request.args.get('page', 1, type=int), 1)
        limit = min(max(request.args.get('limit', 100, type=int), 1), 500)
        result = SupplierService.list_suppliers(page=page, limit=limit)
        return jsonify(result)
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/suppliers', methods=['POST'])
@check_auth
@check_permission('materials:manage')
@validate_json('create_supplier')
def create_supplier():
    data = get_json_body()
    try:
        sid = SupplierService.create_supplier(data)
        try:
            audit_log('create', 'supplier', sid, f"supplier: {data.get('name', '').strip()}")
        except Exception:
            pass
        return jsonify({'ok': True, 'id': sid, 'message': '??????'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/suppliers/<int:sid>', methods=['PUT'])
@check_auth
@check_permission('materials:manage')
@validate_json('create_supplier')
def update_supplier(sid):
    data = get_json_body()
    try:
        SupplierService.update_supplier(sid, data)
        try:
            audit_log('update', 'supplier', sid, 'supplier updated')
        except Exception:
            pass
        return jsonify({'ok': True, 'message': '???'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/suppliers/<int:sid>', methods=['DELETE'])
@check_auth
@check_permission('materials:manage')
def delete_supplier(sid):
    try:
        SupplierService.delete_supplier(sid)
        try:
            audit_log('delete', 'supplier', sid, f'deleted supplier {sid}')
        except Exception:
            pass
        return jsonify({'ok': True, 'message': '???'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 404 if '???' in str(e) else 409
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')
