"""
qr-system — 物料管理路由

注：当前无 Service 层（架构债务），SQL 直接内联在路由中。
后续应参照 products.py 模式抽取 MaterialService。
"""
from flask import request, jsonify, g

from modules.app import app
from modules.db import get_db
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.error_handler import handle_unexpected_error
from modules.middleware.helpers import get_json_body


@app.route('/api/materials', methods=['GET'])
@check_auth
@check_permission('materials:view')
def list_materials():
    try:
        db = get_db()
        rows = db.execute(
            '''SELECT m.*, s.name as supplier_name
               FROM materials m LEFT JOIN suppliers s ON m.supplier_id = s.id
               ORDER BY m.id DESC'''
        ).fetchall()
        return jsonify({'materials': [dict(r) for r in rows]})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/materials', methods=['POST'])
@check_auth
@check_permission('materials:manage')  # 物料模块使用 manage 通配权限（非细分 create/edit/delete）
def create_material():
    data = get_json_body()
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': '物料名称不能为空'}), 400
    db = get_db()
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute(
            'INSERT INTO materials (name, spec, unit, quantity, unit_price, safe_stock, location, supplier_id, remark) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
            (name,
             data.get('spec', '').strip(),
             data.get('unit', '件').strip(),
             float(data.get('quantity', 0)),
             float(data.get('unit_price', 0)),
             float(data.get('safe_stock', 0)),
             data.get('location', '').strip(),
             data.get('supplier_id') or None,
             data.get('remark', '').strip())
        )
        db.commit()
    except Exception as e:
        db.execute('ROLLBACK')
        return jsonify({'error': str(e)}), 400
    return jsonify({'message': 'created'})


@app.route('/api/materials/<int:mid>', methods=['PUT'])
@check_auth
@check_permission('materials:manage')
def update_material(mid):
    data = get_json_body()
    db = get_db()
    try:
        row = db.execute('SELECT id FROM materials WHERE id = ?', (mid,)).fetchone()
        if not row:
            return jsonify({'error': '物料不存在'}), 404
        fields = []
        values = []
        # 列名来自硬编码白名单，安全（不可从用户输入派生）
        for k in ['name', 'spec', 'unit', 'location', 'remark']:
            if k in data:
                fields.append(f'{k} = ?')
                values.append(str(data[k]).strip())
        for k in ['quantity', 'unit_price', 'safe_stock', 'supplier_id']:
            if k in data:
                fields.append(f'{k} = ?')
                values.append(float(data[k]))
        if not fields:
            return jsonify({'error': 'no fields to update'}), 400
        fields.append("updated_at = datetime('now','localtime')")
        values.append(mid)
        set_clause = ', '.join(fields)
        db.execute("BEGIN IMMEDIATE")
        db.execute(f'UPDATE materials SET {set_clause} WHERE id = ?', values)
        db.commit()
        return jsonify({'message': 'updated'})
    except Exception as e:
        db.execute('ROLLBACK')
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/materials/<int:mid>', methods=['DELETE'])
@check_auth
@check_permission('materials:manage')
def delete_material(mid):
    db = get_db()
    try:
        db.execute("BEGIN IMMEDIATE")
        db.execute('DELETE FROM materials WHERE id = ?', (mid,))
        db.commit()
        return jsonify({'message': 'deleted'})
    except Exception as e:
        db.execute('ROLLBACK')
        return handle_unexpected_error(e, 'database operation')


# Material logs (stock in/out)
@app.route('/api/materials/<int:mid>/logs', methods=['GET'])
@check_auth
@check_permission('materials:view')
def material_logs(mid):
    try:
        db = get_db()
        rows = db.execute(
            'SELECT * FROM material_logs WHERE material_id = ? ORDER BY created_at DESC LIMIT 100',
            (mid,)
        ).fetchall()
        return jsonify({'logs': [dict(r) for r in rows]})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/materials/<int:mid>/stock', methods=['POST'])
@check_auth
@check_permission('materials:manage')
def material_stock(mid):
    data = get_json_body()
    change_type = data.get('type', '').strip()  # 'in' or 'out'
    quantity = float(data.get('quantity', 0))
    remark = data.get('remark', '').strip()
    operator_name = data.get('operator_name', '').strip()

    if change_type not in ('in', 'out'):
        return jsonify({'error': '类型必须是 in 或 out'}), 400
    if quantity <= 0:
        return jsonify({'error': '数量必须大于0'}), 400

    db = get_db()
    row = db.execute('SELECT id, quantity FROM materials WHERE id = ?', (mid,)).fetchone()
    if not row:
        return jsonify({'error': '物料不存在'}), 404

    new_qty = row['quantity'] + quantity if change_type == 'in' else row['quantity'] - quantity
    if new_qty < 0 and change_type == 'out':
        current_qty = row['quantity']
        return jsonify({'error': f'库存不足，当前库存 {current_qty}'}), 400

    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('UPDATE materials SET quantity = ?, updated_at = datetime(\"now\",\"localtime\") WHERE id = ?',
                   (new_qty, mid))
        db.execute(
            'INSERT INTO material_logs (material_id, type, quantity, remark, operator_name) VALUES (?, ?, ?, ?, ?)',
            (mid, change_type, quantity, remark, operator_name)
        )
        db.commit()
    except Exception as e:
        db.execute('ROLLBACK')
        return jsonify({'error': str(e)}), 400

    return jsonify({'message': 'ok', 'new_quantity': new_qty})


# ===== 物料消耗关联 =====

@app.route('/api/materials/<int:mid>/consumptions', methods=['GET'])
@check_auth
@check_permission('materials:view')
def material_consumptions(mid):
    try:
        db = get_db()
        rows = db.execute('''
            SELECT mc.*, o.order_no, o.product_name, p.name as process_name
            FROM material_consumptions mc
            LEFT JOIN orders o ON mc.order_id = o.id AND o.deleted_at IS NULL
            LEFT JOIN processes p ON mc.process_id = p.id
            WHERE mc.material_id = ?
            ORDER BY mc.created_at DESC LIMIT 100
        ''', (mid,)).fetchall()
        return jsonify({'consumptions': [dict(r) for r in rows]})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/materials/<int:mid>/consumptions', methods=['POST'])
@check_auth
@check_permission('materials:manage')
def material_consumption_create(mid):
    db = get_db()
    mat = db.execute('SELECT id, quantity FROM materials WHERE id=?', (mid,)).fetchone()
    if not mat:
        return jsonify({'error': '物料不存在'}), 404

    data = get_json_body()
    order_id = data.get('order_id')
    process_id = data.get('process_id')
    quantity = float(data.get('quantity', 0))
    notes = data.get('notes', '').strip()
    operator_name = data.get('operator_name', '').strip()

    if quantity <= 0:
        return jsonify({'error': '数量必须大于0'}), 400
    if mat['quantity'] < quantity:
        return jsonify({'error': f'库存不足，当前库存 {mat["quantity"]}'}), 400

    # 校验订单存在且未被软删除
    if order_id:
        order = db.execute('SELECT id, deleted_at FROM orders WHERE id = ?', (order_id,)).fetchone()
        if not order:
            return jsonify({'error': '订单不存在'}), 404
        if order['deleted_at'] is not None:
            return jsonify({'error': '订单已删除，无法记录消耗'}), 400

    user = g.current_user
    op_name = operator_name or user.get('name', user.get('nickname', ''))

    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('''INSERT INTO material_consumptions
            (material_id, order_id, process_id, quantity, operator_id, operator_name, notes)
            VALUES (?,?,?,?,?,?,?)''',
            (mid, order_id or None, process_id or None, quantity, user.get('id'), op_name, notes))
        new_qty = mat['quantity'] - quantity
        db.execute("UPDATE materials SET quantity=?, updated_at=datetime('now','localtime') WHERE id=?", (new_qty, mid))
        db.execute('INSERT INTO material_logs (material_id, type, quantity, remark, operator_name) VALUES (?,?,?,?,?)',
                   (mid, 'out', quantity, f'消耗: {notes}' if notes else '消耗', op_name))
        db.commit()
    except Exception as e:
        db.execute('ROLLBACK')
        return jsonify({'error': str(e)}), 400

    return jsonify({'ok': True, 'message': '消耗已记录', 'new_quantity': new_qty})


@app.route('/api/materials/consumptions/<int:cid>', methods=['DELETE'])
@check_auth
@check_permission('materials:manage')
def material_consumption_delete(cid):
    db = get_db()
    mc = db.execute('SELECT * FROM material_consumptions WHERE id=?', (cid,)).fetchone()
    if not mc:
        return jsonify({'error': '记录不存在'}), 404
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('UPDATE materials SET quantity=quantity+?, updated_at=datetime("now","localtime") WHERE id=?',
                   (mc['quantity'], mc['material_id']))
        db.execute('DELETE FROM material_consumptions WHERE id=?', (cid,))
        db.commit()
    except Exception as e:
        db.execute('ROLLBACK')
        return jsonify({'error': str(e)}), 400
    return jsonify({'ok': True, 'message': '已撤销消耗'})


# ===== 供应商管理 =====
# 注：供应商 API 混入 materials.py（架构债务），后续应拆分到 routes/suppliers.py

@app.route('/api/suppliers', methods=['GET'])
@check_auth
@check_permission('materials:view')
def list_suppliers():
    try:
        db = get_db()
        rows = db.execute('SELECT * FROM suppliers ORDER BY name').fetchall()
        return jsonify({'suppliers': [dict(r) for r in rows]})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/suppliers', methods=['POST'])
@check_auth
@check_permission('materials:manage')
def create_supplier():
    try:
        data = get_json_body()
        name = data.get('name', '').strip()
        if not name:
            return jsonify({'error': '供应商名称不能为空'}), 400
        db = get_db()
        db.execute("BEGIN IMMEDIATE")
        db.execute('INSERT INTO suppliers (name, contact, phone, address, remark) VALUES (?,?,?,?,?)',
                   (name, data.get('contact', '').strip(), data.get('phone', '').strip(),
                    data.get('address', '').strip(), data.get('remark', '').strip()))
        db.commit()
        rid = db.execute('SELECT last_insert_rowid()').fetchone()[0]
        return jsonify({'ok': True, 'id': rid, 'message': '供应商已添加'})
    except Exception as e:
        db.execute('ROLLBACK')
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/suppliers/<int:sid>', methods=['PUT'])
@check_auth
@check_permission('materials:manage')
def update_supplier(sid):
    try:
        data = get_json_body()
        db = get_db()
        row = db.execute('SELECT id FROM suppliers WHERE id=?', (sid,)).fetchone()
        if not row:
            return jsonify({'error': '供应商不存在'}), 404
        db.execute("BEGIN IMMEDIATE")
        db.execute('UPDATE suppliers SET name=?, contact=?, phone=?, address=?, remark=? WHERE id=?',
                   (data.get('name', '').strip(), data.get('contact', '').strip(),
                    data.get('phone', '').strip(), data.get('address', '').strip(),
                    data.get('remark', '').strip(), sid))
        db.commit()
        return jsonify({'ok': True, 'message': '已更新'})
    except Exception as e:
        db.execute('ROLLBACK')
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/suppliers/<int:sid>', methods=['DELETE'])
@check_auth
@check_permission('materials:manage')
def delete_supplier(sid):
    try:
        db = get_db()
        db.execute("BEGIN IMMEDIATE")
        db.execute('DELETE FROM suppliers WHERE id=?', (sid,))
        db.commit()
        return jsonify({'ok': True, 'message': '已删除'})
    except Exception as e:
        db.execute('ROLLBACK')
        return handle_unexpected_error(e, 'database operation')
