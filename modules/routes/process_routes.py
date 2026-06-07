"""
qr-system — 工序路线管理
"""
from flask import request, jsonify

from modules.app import app
from modules.middleware.auth import check_auth, check_permission, audit_log
from modules.middleware.helpers import get_json_body
from modules.services.route_service import ProcessRouteService


@app.route('/api/process-routes', methods=['GET'])
@check_auth
@check_permission('routes:view')
def get_process_routes():
    """获取所有工序路线（含工序明细），支持分类筛选"""
    category = request.args.get('category', '').strip()
    search = request.args.get('search', '').strip()
    limit = request.args.get('limit')
    offset = request.args.get('offset', 0)
    if limit:
        limit = int(limit)
        offset = int(offset)
    else:
        limit = None
    return jsonify(ProcessRouteService.list_routes(category, search, limit, offset))


@app.route('/api/process-routes', methods=['POST'])
@check_auth
@check_permission('routes:create')
def create_process_route():
    """创建工序路线"""
    data = get_json_body()
    try:
        rid = ProcessRouteService.create_route(data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    try:
        audit_log('create_process_route', 'process_route', rid, data.get('name', ''))
    except Exception:
        pass
    return jsonify({'message': '创建成功', 'id': rid})


@app.route('/api/process-routes/<int:rid>', methods=['PUT'])
@check_auth
@check_permission('routes:edit')
def update_process_route(rid):
    """更新工序路线"""
    data = get_json_body()
    if not data:
        return jsonify({'error': '无更新数据'}), 400
    try:
        ProcessRouteService.update_route(rid, data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404 if '不存在' in str(e) else 400
    try:
        audit_log('update_process_route', 'process_route', rid, data.get('name', ''))
    except Exception:
        pass
    return jsonify({'message': '更新成功'})


@app.route('/api/process-routes/<int:rid>', methods=['DELETE'])
@check_auth
@check_permission('routes:delete')
def delete_process_route(rid):
    """删除工序路线"""
    try:
        name = ProcessRouteService.delete_route(rid)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404 if '不存在' in str(e) else 400
    try:
        audit_log('delete_process_route', 'process_route', rid, name)
    except Exception:
        pass
    return jsonify({'message': '删除成功'})


@app.route('/api/process-routes/<int:rid>/apply', methods=['POST'])
@check_auth
@check_permission('routes:edit')
def apply_process_route(rid):
    """将工序路线应用到订单"""
    data = get_json_body()
    order_id = data.get('order_id')
    if not order_id:
        return jsonify({'error': '请指定订单'}), 400
    # 验证订单存在且未被删除
    from modules.db import get_db
    db = get_db()
    order = db.execute('SELECT id FROM orders WHERE id = ? AND deleted_at IS NULL', (order_id,)).fetchone()
    if not order:
        return jsonify({'error': '订单不存在或已删除'}), 404
    try:
        count = ProcessRouteService.apply_route(rid, order_id)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    try:
        audit_log('apply_process_route', 'order', order_id, f'route={rid}')
    except Exception:
        pass
    return jsonify({'message': '应用成功', 'processes_count': count})
