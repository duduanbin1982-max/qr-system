"""
qr-system — 岗位管理（路由层）
"""
from flask import request, jsonify
from modules.app import app
from modules.middleware.auth import check_auth, check_permission, audit_log
from modules.services.position_service import PositionService


@app.route('/api/positions', methods=['GET'])
@check_auth
@check_permission('positions:view')
def list_positions():
    """
    ---
    tags:
      - Positions
    summary: List Positions
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    return jsonify(PositionService.list_positions())


@app.route('/api/positions', methods=['POST'])
@check_auth
@check_permission('positions:create')
def create_position():
    """
    ---
    tags:
      - Positions
    summary: Create Position
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    data = request.get_json(force=True, silent=True) or {}
    try:
        pos_id = PositionService.create_position(data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 409 if '已存在' in str(e) else 400
    audit_log('create_position', 'position', pos_id, data.get('name', ''))
    return jsonify({'message': '创建成功', 'id': pos_id})


@app.route('/api/positions/<int:pos_id>', methods=['PUT'])
@check_auth
@check_permission('positions:edit')
def update_position(pos_id):
    """
    ---
    tags:
      - Positions
    summary: Update Position
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    data = request.get_json(force=True, silent=True) or {}
    try:
        PositionService.update_position(pos_id, data)
    except ValueError as e:
        code = 404 if '不存在' in str(e) else (409 if '已存在' in str(e) else 400)
        return jsonify({'error': str(e)}), code
    audit_log('update_position', 'position', pos_id, data.get('name', ''))
    return jsonify({'message': '更新成功'})


@app.route('/api/positions/<int:pos_id>', methods=['DELETE'])
@check_auth
@check_permission('positions:delete')
def delete_position(pos_id):
    """
    ---
    tags:
      - Positions
    summary: Delete Position
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    try:
        name = PositionService.delete_position(pos_id)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    audit_log('delete_position', 'position', pos_id, name)
    return jsonify({'message': '删除成功'})
