"""
qr-system — 岗位管理（路由层）

注：Swagger docstring 仅供文档参考。
"""
from flask import g, request, jsonify
from modules import config
from modules.domain.position_versioning import PositionVersionedWriteDisabledError
from modules.route_decorators import (
    app,
    check_auth,
    check_permission,
    get_json_body,
    require_legacy_position_write,
    safe_audit_log,
    validate_json,
)
from modules.services.position_service import PositionService
from modules.services.position_version_service import PositionVersionService


def _actor():
    return getattr(g, 'current_user', {}) or {}


@validate_json('create_position')
def _create_legacy_position():
    data = get_json_body()
    pos_id = PositionService.create_position(data)
    safe_audit_log('create_position', 'position', pos_id, data.get('name', ''))
    return jsonify({'message': '创建成功', 'id': pos_id})


@validate_json('position_version_create')
def _create_versioned_position():
    result = PositionVersionService.create_position(
        get_json_body(),
        _actor(),
        request.headers.get('X-Request-ID', ''),
    )
    return jsonify(result), 201


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
    is_versioned_command = bool(
        data.get('idempotency_key') or data.get('revision_reason')
    )
    if config.POSITION_VERSIONED_WRITE_ENABLED:
        return _create_versioned_position()
    if is_versioned_command:
        raise PositionVersionedWriteDisabledError('岗位版本化写入尚未启用')
    return _create_legacy_position()


@app.route('/api/positions/<int:pos_id>', methods=['PUT'])
@check_auth
@check_permission('positions:edit')
@require_legacy_position_write
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
    PositionService.update_position(pos_id, data)
    safe_audit_log('update_position', 'position', pos_id, data.get('name', ''))
    return jsonify({'message': '更新成功'})


@app.route('/api/positions/<int:pos_id>/impact', methods=['GET'])
@check_auth
@check_permission('positions:impact')
def position_impact(pos_id):
    try:
        return jsonify(PositionService.check_impact(pos_id))
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@app.route('/api/positions/<int:pos_id>', methods=['DELETE'])
@check_auth
@check_permission('positions:delete')
@require_legacy_position_write
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
    safe_audit_log('delete_position', 'position', pos_id, name)
    return jsonify({'message': '删除成功'})
