"""Rework workflow HTTP routes."""
from flask import request, jsonify, g, send_file
from datetime import datetime
from modules.route_decorators import (
    app,
    check_auth,
    check_permission,
    get_json_body,
    safe_audit_log,
    validate_json,
)
from modules.services.rework_service import ReworkService


@app.route('/api/rework', methods=['GET'])
@check_auth
@check_permission('rework:view')
def rework_list():
    status = request.args.get('status', '')
    search = request.args.get('search', '')
    date_from = request.args.get('from', '')
    date_to = request.args.get('to', '')
    worker_id = request.args.get('worker_id', type=int)
    process_id = request.args.get('process_id', type=int)
    page = request.args.get('page', 1)
    per_page = request.args.get('per_page', 50)
    result = ReworkService.list_rework(
        status=status, search=search, date_from=date_from, date_to=date_to,
        page=page, per_page=per_page, worker_id=worker_id, process_id=process_id
    )
    return jsonify(result)


@app.route('/api/rework', methods=['POST'])
@check_auth
@check_permission('rework:create')
@validate_json('create_rework')
def rework_create():
    data = get_json_body()
    rework_id = ReworkService.create_rework(
        order_id=data['order_id'],
        process_id=data['process_id'],
        user_id=g.current_user['id'],
        quantity=data['quantity'],
        reason=data.get('reason', ''),
        reject_recent_duplicate=True,
    )
    safe_audit_log('rework_create', 'rework', rework_id, f'order={data["order_id"]}')
    return jsonify({'ok': True, 'id': rework_id, 'message': '返工记录已创建'})


@app.route('/api/rework/batch-complete', methods=['POST'])
@check_auth
@check_permission('rework:edit')
@validate_json('batch_complete_rework')
def rework_batch_complete():
    data = get_json_body()
    ids = data['ids']
    result = ReworkService.batch_complete(
        ids, data.get('reason', ''), g.current_user['id'],
        data['result'], data.get('result_remark', '')
    )
    safe_audit_log('rework_batch', 'rework', 0, f'completed {result["completed"]} items')
    return jsonify({'ok': True, 'completed': result['completed'], 'errors': result['errors']})


@app.route('/api/rework/export', methods=['GET'])
@check_auth
@check_permission('rework:view')
def rework_export():
    output = ReworkService.export_rework(
        status=request.args.get('status', ''),
        search=request.args.get('search', ''),
        date_from=request.args.get('from', ''),
        date_to=request.args.get('to', ''),
        worker_id=request.args.get('worker_id', type=int),
        process_id=request.args.get('process_id', type=int),
    )
    output.seek(0)
    return send_file(
        output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True, download_name=f'rework_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )


@app.route('/api/rework/trend', methods=['GET'])
@check_auth
@check_permission('rework:view')
def rework_trend():
    period = request.args.get('period', 'week')
    months = request.args.get('months', 3, type=int)
    return jsonify({'ok': True, 'data': ReworkService.rework_trend(period, months)})


@app.route('/api/rework/top-processes', methods=['GET'])
@check_auth
@check_permission('rework:view')
def rework_top_processes():
    top_n = request.args.get('n', 5, type=int)
    return jsonify({'ok': True, 'data': ReworkService.top_rework_processes(top_n)})


@app.route('/api/rework/worker-stats', methods=['GET'])
@check_auth
@check_permission('rework:view')
def rework_worker_stats():
    return jsonify({'ok': True, 'data': ReworkService.worker_rework_stats()})


@app.route('/api/rework/stats', methods=['GET'])
@check_auth
@check_permission('rework:view')
def rework_stats():
    return jsonify(ReworkService.get_stats())


@app.route('/api/rework/<int:rework_id>', methods=['PUT'])
@check_auth
@check_permission('rework:edit')
@validate_json('update_rework')
def rework_update(rework_id):
    data = get_json_body()
    ReworkService.update_rework(rework_id, data['reason'])
    safe_audit_log('rework_edit', 'rework', rework_id, 'reason updated')
    return jsonify({'ok': True, 'message': '返工原因已更新'})


@app.route('/api/rework/<int:rework_id>/complete', methods=['POST'])
@check_auth
@check_permission('rework:edit')
@validate_json('complete_rework')
def rework_complete(rework_id):
    data = get_json_body()
    ReworkService.complete_rework(
        rework_id, data.get('reason', ''),
        g.current_user['id'], data['result'],
        data.get('result_remark', '')
    )
    safe_audit_log('rework_complete', 'rework', rework_id, 'completed')
    return jsonify({'ok': True, 'message': '返工完成'})
