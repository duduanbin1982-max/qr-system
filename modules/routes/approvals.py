"""Approval workflow HTTP routes."""
from flask import g, jsonify, request

from modules.route_decorators import (
    app,
    check_auth,
    check_permission,
    get_json_body,
    parse_pagination,
    safe_audit_log,
    validate_json,
)
from modules.services.approval_service import ApprovalService
from modules.services.approval_policy_service import ApprovalPolicyService


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
@check_permission('approvals:decision')
@validate_json('approval_action')
def handle_approval(record_id, action):
    data = get_json_body()
    ApprovalService.handle(
        record_id,
        action,
        approver={
            'id': g.current_user['id'],
            'name': g.current_user['name'],
            'role': g.current_user.get('role', ''),
        },
        comment=data.get('comment', '')
    )
    safe_audit_log(
        'approve_' + action, 'approval', record_id,
        f'{g.current_user["name"]} {action} approval {record_id}'
    )
    return jsonify({'message': '审批操作成功'})


@app.route('/api/approvals/config', methods=['GET'])
@check_auth
@check_permission('approval_policies:view')
def get_approval_config():
    """Return all approval_config rows with process names."""
    return jsonify(ApprovalService.list_configs())


@app.route('/api/approval-policies', methods=['GET'])
@check_auth
@check_permission('approval_policies:view')
def list_approval_policies():
    return jsonify(ApprovalPolicyService.list(include_history=request.args.get('history') == '1'))


@app.route('/api/approval-policies/revisions', methods=['POST'])
@check_auth
@check_permission('approval_policies:create')
@validate_json('approval_policy_revision_payload')
def create_approval_policy_revision():
    row = ApprovalPolicyService.create_revision(
        get_json_body(), {'id': g.current_user['id'], 'name': g.current_user['name']}
    )
    return jsonify({'revision': row}), 201


@app.route('/api/approval-policies/<int:policy_id>/history', methods=['GET'])
@check_auth
@check_permission('approval_policies:history')
def approval_policy_history(policy_id):
    return jsonify(ApprovalPolicyService.history(policy_id))


def _transition_policy_revision(revision_id, target, permission):
    return ApprovalPolicyService.transition(
        revision_id, target, {'id': g.current_user['id'], 'name': g.current_user['name']}
    )


@app.route('/api/approval-policies/revisions/<int:revision_id>/submit', methods=['POST'])
@check_auth
@check_permission('approval_policies:submit')
def submit_approval_policy_revision(revision_id):
    return jsonify({'revision': _transition_policy_revision(revision_id, 'pending_approval', 'approval_policies:submit')})


@app.route('/api/approval-policies/revisions/<int:revision_id>/approve', methods=['POST'])
@check_auth
@check_permission('approval_policies:approve')
def approve_approval_policy_revision(revision_id):
    return jsonify({'revision': _transition_policy_revision(revision_id, 'published', 'approval_policies:approve')})


@app.route('/api/approval-policies/revisions/<int:revision_id>/reject', methods=['POST'])
@check_auth
@check_permission('approval_policies:reject')
def reject_approval_policy_revision(revision_id):
    return jsonify({'revision': _transition_policy_revision(revision_id, 'rejected', 'approval_policies:reject')})


@app.route('/api/approvals/config', methods=['POST'])
@check_auth
@check_permission('approval_policies:create')
@validate_json('approval_config_payload')
def save_approval_config():
    """Save approval_config: {process_id: int, require_approval: 1|0, approver_role: str, approval_level: int}
    Also supports batch: {"configs": [{...}, ...]}
    """
    data = get_json_body()
    configs = data.get('configs', [data] if 'process_id' in data else [])
    ApprovalService.save_configs(configs)
    return jsonify({'message': '保存成功'})


@app.route('/api/approvals/batch', methods=['POST'])
@check_auth
@check_permission('approvals:decision')
@validate_json('approval_batch_payload')
def batch_approval():
    """Batch approve/reject: {"ids": [1,2,3], "action": "approve|reject"}"""
    data = get_json_body()
    ids = data.get('ids', [])
    action = data.get('action', '')
    count, failed = ApprovalService.batch_handle(
        ids, action,
        approver={
            'id': g.current_user['id'],
            'name': g.current_user['name'],
            'role': g.current_user.get('role', ''),
        },
        comment=data.get('comment', '')
    )
    if failed:
        return jsonify({
            "message": f"已处理 {count}/{len(ids)} 条",
            "count": count,
            "total": len(ids),
            "failed": failed
        })
    return jsonify({"message": f"已处理 {count} 条", "count": count, "total": len(ids)})


@app.route('/api/approvals/stats', methods=['GET'])
@check_auth
@check_permission('approvals:view')
def approval_stats():
    """Approval statistics: avg time, pending > 24h, etc."""
    return jsonify(ApprovalService.get_stats())
