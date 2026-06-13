"""
qr-system ? ???????Refactored: SQL ? ApprovalService?
"""
from flask import request, jsonify, g

from modules.app import app
from modules.middleware.auth import check_auth, check_permission, audit_log
from modules.middleware.helpers import get_json_body, parse_pagination
from modules.middleware.validate import validate_json
from modules.services.approval_service import ApprovalService


@app.route('/api/approvals/pending', methods=['GET'])
@check_auth
@check_permission('approvals:view')
def get_pending_approvals():
    p = parse_pagination()
    result = ApprovalService.list_pending(page=p['page'], limit=p['limit'])
    return jsonify(result)


@app.route('/api/approvals/history', methods=['GET'])
@check_auth
@check_permission('approvals:view')
def get_approval_history():
    p = parse_pagination()
    result = ApprovalService.list_history(page=p['page'], limit=p['limit'])
    return jsonify(result)


@app.route('/api/approvals/<int:record_id>/<action>', methods=['POST'])
@check_auth
@check_permission('approvals:edit')
@validate_json('approval_action')
def handle_approval(record_id, action):
    data = get_json_body()
    try:
        ApprovalService.handle(
            record_id, action,
            approver={'id': g.current_user['id'], 'name': g.current_user['name']},
            comment=data.get('comment', '')
        )
        try:
            audit_log(
                'approve_' + action, 'approval', record_id,
                f'{g.current_user["name"]} {action} approval {record_id}'
            )
        except Exception:
            pass
        return jsonify({'message': '????'})
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
