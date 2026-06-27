"""
qr-system ? ???????Refactored: SQL ? ReworkService?
"""
from flask import request, jsonify, g, send_file
from datetime import datetime
from modules.app import app
from modules.middleware.audit import safe_audit_log
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.error_handler import handle_unexpected_error
from modules.services.rework_service import ReworkService


@app.route('/api/rework', methods=['GET'])
@check_auth
@check_permission('rework:view')
def rework_list():
    try:
        status = request.args.get('status', '')
        search = request.args.get('search', '')
        date_from = request.args.get('from', '')
        date_to = request.args.get('to', '')
        worker_id = request.args.get('worker_id', type=int)
        process_id = request.args.get('process_id', type=int)
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 50))
        result = ReworkService.list_rework(
            status=status, search=search, date_from=date_from, date_to=date_to,
            page=page, per_page=per_page, worker_id=worker_id, process_id=process_id
        )
        return jsonify(result)
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/rework', methods=['POST'])
@check_auth
@check_permission('rework:create')
def rework_create():
    try:
        data = request.get_json() or {}
        required = ['order_id', 'process_id', 'quantity']
        for field in required:
            if field not in data:
                return jsonify({'error': f'缺少必填字段: {field}'}), 400
        user = g.current_user if hasattr(g, 'current_user') else {}
        rework_id = ReworkService.create_rework(
            order_id=data['order_id'],
            process_id=data['process_id'],
            user_id=user.get('id'),
            quantity=data['quantity'],
            reason=data.get('reason', '')
        )
        safe_audit_log('rework_create', 'rework', rework_id, f'order={data["order_id"]}')
        return jsonify({'ok': True, 'id': rework_id, 'message': '返工记录已创建'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/rework/batch-complete', methods=['POST'])
@check_auth
@check_permission('rework:edit')
def rework_batch_complete():
    try:
        data = request.get_json() or {}
        ids = data.get('ids', [])
        if not ids:
            return jsonify({'error': '请选择返工记录'}), 400
        user = g.current_user if hasattr(g, 'current_user') else {}
        result = ReworkService.batch_complete(
            ids, data.get('reason', ''), user.get('id'),
            data.get('result', 'ok'), data.get('result_remark', '')
        )
        safe_audit_log('rework_batch', 'rework', 0, f'completed {result["completed"]} items')
        return jsonify({'ok': True, 'completed': result['completed'], 'errors': result['errors']})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/rework/export', methods=['GET'])
@check_auth
@check_permission('rework:view')
def rework_export():
    try:
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
    except Exception as e:
        return handle_unexpected_error(e, 'export operation')


@app.route('/api/rework/trend', methods=['GET'])
@check_auth
@check_permission('rework:view')
def rework_trend():
    try:
        period = request.args.get('period', 'week')
        months = request.args.get('months', 3, type=int)
        return jsonify({'ok': True, 'data': ReworkService.rework_trend(period, months)})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/rework/top-processes', methods=['GET'])
@check_auth
@check_permission('rework:view')
def rework_top_processes():
    try:
        top_n = request.args.get('n', 5, type=int)
        return jsonify({'ok': True, 'data': ReworkService.top_rework_processes(top_n)})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/rework/worker-stats', methods=['GET'])
@check_auth
@check_permission('rework:view')
def rework_worker_stats():
    try:
        return jsonify({'ok': True, 'data': ReworkService.worker_rework_stats()})
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/rework/stats', methods=['GET'])
@check_auth
@check_permission('rework:view')
def rework_stats():
    try:
        return jsonify(ReworkService.get_stats())
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/rework/<int:rework_id>', methods=['PUT'])
@check_auth
@check_permission('rework:edit')
def rework_update(rework_id):
    try:
        data = request.get_json() or {}
        if 'reason' not in data:
            return jsonify({'error': '缺少必填字段: reason'}), 400
        ReworkService.update_rework(rework_id, data['reason'])
        safe_audit_log('rework_edit', 'rework', rework_id, 'reason updated')
        return jsonify({'ok': True})
    except ValueError as e:
        msg = str(e)
        code = 404 if '不存在' in msg else 400
        return jsonify({'error': msg}), code
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')


@app.route('/api/rework/<int:rework_id>/complete', methods=['POST'])
@check_auth
@check_permission('rework:edit')
def rework_complete(rework_id):
    try:
        data = request.get_json() or {}
        user = g.current_user if hasattr(g, 'current_user') else {}
        ReworkService.complete_rework(
            rework_id, data.get('reason', ''),
            user.get('id'), data.get('result', ''),
            data.get('result_remark', '')
        )
        safe_audit_log('rework_complete', 'rework', rework_id, 'completed')
        return jsonify({'ok': True, 'message': '????'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')
