"""
qr-system ? ???????Refactored: SQL ? ReworkService?
"""
from flask import request, jsonify, g
from modules.app import app
from modules.middleware.auth import check_auth, check_permission, audit_log
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
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 50))
        result = ReworkService.list_rework(
            status=status, search=search, date_from=date_from, date_to=date_to,
            page=page, per_page=per_page
        )
        return jsonify(result)
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
            return jsonify({'error': '?????'}), 400
        ReworkService.update_rework(rework_id, data['reason'])
        audit_log('rework_edit', 'rework', rework_id, 'reason updated')
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
        ReworkService.complete_rework(rework_id, data.get('reason', ''), user.get('id'))
        audit_log('rework_complete', 'rework', rework_id, 'completed')
        return jsonify({'ok': True, 'message': '????'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')
