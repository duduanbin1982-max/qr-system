"""
qr-system — 工序管理（路由层）

薄层：HTTP 解析 → 调用 ProcessService → 格式化响应。
"""
from flask import request, jsonify

from modules.app import app
from modules.middleware.auth import check_auth, check_permission, audit_log
from modules.middleware.helpers import get_json_body
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
    return jsonify(ProcessService.list_processes(category))


@app.route('/api/processes', methods=['POST'])
@check_auth
@check_permission('processes:create')
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
    audit_log('create_process', 'process', pid, data.get('name', ''))
    return jsonify({'message': '添加成功', 'id': pid})


@app.route('/api/processes/<int:pid>', methods=['PUT'])
@check_auth
@check_permission('processes:edit')
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
    safe_data = {k: v for k, v in data.items() if k not in ('password', 'token')}
    audit_log('update_process', 'process', pid, str(safe_data))
    return jsonify({'message': '更新成功'})


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
        ProcessService.delete_process(pid)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404 if '不存在' in str(e) else 400
    audit_log('delete_process', 'process', pid)
    return jsonify({'message': '删除成功'})
