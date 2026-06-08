"""
qr-system — 工序管理（路由层）

薄层：HTTP 解析 → 调用 ProcessService → 格式化响应。
"""
from flask import request, jsonify

from modules.app import app
from modules.middleware.auth import check_auth, check_permission, audit_log
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
    from modules.db import get_db
    db = get_db()
    existing = db.execute('SELECT id, name FROM processes WHERE id = ?', (pid,)).fetchone()
    if not existing:
        return jsonify({'error': '工序不存在'}), 404
    # Single UNION ALL query instead of 9 separate SELECT COUNT(*)
    union_parts = []
    for tbl in ['work_records','scrap_records','rework_records',
                'quality_inspections','process_prices','process_route_items',
                'order_processes','position_processes','material_consumptions']:
        union_parts.append(f"SELECT '{tbl}' as tbl, COUNT(*) as cnt FROM {tbl} WHERE process_id = ?")
    union_sql = ' UNION ALL '.join(union_parts)
    rows = db.execute(union_sql, [pid] * 9).fetchall()
    impact = {r['tbl']: r['cnt'] for r in rows if r['cnt'] > 0}
    return jsonify({'process_id': pid, 'name': existing['name'], 'impact': impact})


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
        return jsonify({'error': str(e)}), 404 if '???' in str(e) else 400
    try:
        audit_log('delete_process', 'process', pid,
                  f'name={result.get("name","")} impact={result.get("impact",{})}')
    except Exception as e:
        app.logger.warning('audit_log failed: %s', e)
    return jsonify({'message': '删除成功', 'impact': result.get('impact', {})})
