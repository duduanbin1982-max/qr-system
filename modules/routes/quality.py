"""qr-system — 质量检验路由（委托 QualityService）"""
from flask import request, jsonify, g
from modules.app import app
from modules.db import get_db
from modules.middleware.auth import check_auth, check_permission, audit_log
from modules.middleware.error_handler import handle_unexpected_error
from modules.middleware.helpers import get_json_body
from modules.middleware.validate import validate_json
from modules.services.quality_service import QualityService


def _safe_int(val, default):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


@app.route('/api/quality/inspections', methods=['GET'])
@check_auth
@check_permission('quality:view')
def quality_list():
    try:
        return jsonify(QualityService.list_inspections(
            order_id=request.args.get('order_id', type=int),
            process_id=request.args.get('process_id', type=int),
            inspection_type=request.args.get('type', ''),
            result=request.args.get('result', ''),
            search=request.args.get('search', ''),
            date_from=request.args.get('from', ''),
            date_to=request.args.get('to', ''),
            page=_safe_int(request.args.get('page', '1'), 1),
            per_page=_safe_int(request.args.get('limit') or request.args.get('per_page', '20'), 20),
        ))
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/quality/inspections', methods=['POST'])
@check_auth
@check_permission('quality:edit')
@validate_json('quality_inspection')
def quality_create():
    data = get_json_body()
    order_id = data.get('order_id')
    if not order_id or not data.get('process_id'):
        return jsonify({'error': '订单和工序必填'}), 400

    # Pre-checks (order existence + soft-delete)
    db = get_db()
    order = db.execute('SELECT id, deleted_at FROM orders WHERE id = ?', (order_id,)).fetchone()
    if not order:
        return jsonify({'error': '订单不存在'}), 404
    if order['deleted_at'] is not None:
        return jsonify({'error': '订单已删除，无法添加检验记录'}), 400

    try:
        inspection_id = QualityService.create_inspection(data, g.current_user['id'])
    except ValueError as e:
        return jsonify({'error': str(e)}), 400

    try:
        audit_log('quality_create', 'quality_inspection', inspection_id, 'created')
    except Exception as e:
        app.logger.warning('audit_log failed: %s', e)
    return jsonify({'ok': True, 'id': inspection_id})


@app.route('/api/quality/inspections/<int:inspection_id>', methods=['PUT'])
@check_auth
@check_permission('quality:edit')
@validate_json('quality_update')
def quality_update(inspection_id):
    data = get_json_body()
    try:
        result = QualityService.update_inspection(inspection_id, data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404 if '不存在' in str(e) else 400

    try:
        audit_log('quality_edit', 'quality_inspection', inspection_id, f'result={result}')
    except Exception as e:
        app.logger.warning('audit_log failed: %s', e)
    return jsonify({'ok': True, 'message': '已更新'})


@app.route('/api/quality/inspections/<int:inspection_id>', methods=['DELETE'])
@check_auth
@check_permission('quality:edit')
def quality_delete(inspection_id):
    try:
        QualityService.delete_inspection(inspection_id)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404

    try:
        audit_log('quality_delete', 'quality_inspection', inspection_id, 'deleted')
    except Exception as e:
        app.logger.warning('audit_log failed: %s', e)
    return jsonify({'ok': True, 'message': '已删除'})


@app.route('/api/quality/inspections/stats', methods=['GET'])
@check_auth
@check_permission('quality:view')
def quality_stats():
    try:
        return jsonify(QualityService.get_stats())
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/quality/defect-pareto', methods=['GET'])
@check_auth
@check_permission('quality:view')
def quality_defect_pareto():
    try:
        return jsonify(QualityService.defect_pareto(
            date_from=request.args.get('from', ''),
            date_to=request.args.get('to', ''),
        ))
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')
