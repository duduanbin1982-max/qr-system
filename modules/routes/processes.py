"""
qr-system — 工序管理（路由层）

薄层：HTTP 解析 → 调用 ProcessService → 格式化响应。
"""
from flask import request, jsonify

from modules.app import app
from modules.middleware.audit import audit_log
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.helpers import get_json_body
from modules.middleware.validate import validate_json
from modules.services.process_service import ProcessService


@app.route('/api/processes', methods=['GET'])
@check_auth
@check_permission('processes:view')
def list_processes():
    """
    ---
    tags:
      - Processes
    summary: List Processes
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    category = request.args.get('category', '').strip()
    search = request.args.get('search', '').strip()
    sort_by = request.args.get('sort_by', 'seq_order')
    sort_dir = request.args.get('sort_dir', 'asc')
    limit = request.args.get('limit')
    offset = request.args.get('offset', 0)
    if limit:
        try:
            limit = int(limit)
            offset = int(offset)
        except (ValueError, TypeError):
            limit = None
            offset = 0
    else:
        limit = None
    try:
        result = ProcessService.list_processes(category, search, sort_by, sort_dir, limit, offset)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify(result)


@app.route('/api/processes', methods=['POST'])
@check_auth
@check_permission('processes:create')
@validate_json('create_process')
def create_process():
    """
    ---
    tags:
      - Processes
    summary: Create Process
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    data = get_json_body()
    try:
        pid = ProcessService.create_process(data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    try:
        audit_log('create_process', 'process', pid, data.get('name', ''))
    except Exception as e:
        app.logger.warning('audit_log failed: %s', e)
    return jsonify({'message': '添加成功', 'id': pid})


@app.route('/api/processes/<int:pid>', methods=['PUT'])
@check_auth
@check_permission('processes:edit')
@validate_json('update_process')
def update_process(pid):
    """
    ---
    tags:
      - Processes
    summary: Update Process
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    data = get_json_body()
    try:
        ProcessService.update_process(pid, data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404 if '不存在' in str(e) else 400
    try:
        audit_log('update_process', 'process', pid, str(data))
    except Exception as e:
        app.logger.warning('audit_log failed: %s', e)
    return jsonify({'message': '更新成功'})


@app.route('/api/processes/<int:pid>/impact', methods=['GET'])
@check_auth
@check_permission('processes:view')
def process_impact(pid):
    """查询删除工序的影响范围（不实际删除）。"""
    try:
        return jsonify(ProcessService.check_impact(pid))
    except ValueError as e:
        return jsonify({'error': str(e)}), 404


@app.route('/api/processes/<int:pid>', methods=['DELETE'])
@check_auth
@check_permission('processes:delete')
def delete_process(pid):
    """
    ---
    tags:
      - Processes
    summary: Delete Process
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    try:
        result = ProcessService.delete_process(pid)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    try:
        audit_log('delete_process', 'process', pid,
                  f'name={result.get("name","")} impact={result.get("impact",{})}')
    except Exception as e:
        app.logger.warning('audit_log failed: %s', e)
    return jsonify({'message': '删除成功', 'impact': result.get('impact', {})})
