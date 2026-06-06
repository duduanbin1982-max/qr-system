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
    return jsonify(ProcessRouteService.list_routes(category))


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
    audit_log('create_process_route', 'process_route', rid, data.get('name', ''))
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
    audit_log('update_process_route', 'process_route', rid, data.get('name', ''))
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
    audit_log('delete_process_route', 'process_route', rid, name)
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
    try:
        count = ProcessRouteService.apply_route(rid, order_id)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    audit_log('apply_process_route', 'order', order_id, f'route={rid}')
    return jsonify({'message': '应用成功', 'processes_count': count})
