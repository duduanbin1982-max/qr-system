"""
qr-system — 岗位管理（路由层）

注：Swagger docstring 仅供文档参考。
"""
from flask import request, jsonify
from modules.app import app
from modules.middleware.audit import audit_log
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.helpers import get_json_body
from modules.middleware.validate import validate_json
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
    page = max(request.args.get('page', 1, type=int), 1)
    limit = min(max(request.args.get('limit', 100, type=int), 1), 500)
    return jsonify(PositionService.list_positions(page, limit))


@app.route('/api/positions', methods=['POST'])
@check_auth
@check_permission('positions:create')
@validate_json('create_position')
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
    data = get_json_body()
    try:
        pos_id = PositionService.create_position(data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 409 if '已存在' in str(e) else 400
    try:
        audit_log('create_position', 'position', pos_id, data.get('name', ''))
    except Exception as e:
        app.logger.warning('audit_log failed: %s', e)
    return jsonify({'message': '创建成功', 'id': pos_id})


@app.route('/api/positions/<int:pos_id>', methods=['PUT'])
@check_auth
@check_permission('positions:edit')
@validate_json('update_position')
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
    data = get_json_body()
    try:
        PositionService.update_position(pos_id, data)
    except ValueError as e:
        code = 404 if '不存在' in str(e) else (409 if '已存在' in str(e) else 400)
        return jsonify({'error': str(e)}), code
    try:
        audit_log('update_position', 'position', pos_id, data.get('name', ''))
    except Exception as e:
        app.logger.warning('audit_log failed: %s', e)
    return jsonify({'message': '更新成功'})


@app.route('/api/positions/<int:pos_id>/impact', methods=['GET'])
@check_auth
@check_permission('positions:view')
def position_impact(pos_id):
    try:
        return jsonify(PositionService.check_impact(pos_id))
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


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
    try:
        audit_log('delete_position', 'position', pos_id, name)
    except Exception as e:
        app.logger.warning('audit_log failed: %s', e)
    return jsonify({'message': '删除成功'})
