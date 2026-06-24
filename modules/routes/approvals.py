"""
qr-system ? ???????Refactored: SQL ? ApprovalService?
"""
from flask import request, jsonify, g

from modules.app import app
from modules.middleware.audit import audit_log
from modules.middleware.auth import check_auth, check_permission
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


@app.route('/api/approvals/config', methods=['GET'])
@check_auth
@check_permission('approvals:edit')
def get_approval_config():
    """Return all approval_config rows with process names."""
    return jsonify(ApprovalService.list_configs())


@app.route('/api/approvals/config', methods=['POST'])
@check_auth
@check_permission('approvals:edit')
def save_approval_config():
    """Save approval_config: {process_id: int, require_approval: 1|0, approver_role: str, approval_level: int}
    Also supports batch: {"configs": [{...}, ...]}
    """
    data = get_json_body()
    configs = data.get("configs", [data] if "process_id" in data else [])
    ApprovalService.save_configs(configs)
    return jsonify({"message": "保存成功"})

@app.route("/api/approvals/batch", methods=["POST"])
@check_auth
@check_permission("approvals:edit")
def batch_approval():
    """Batch approve/reject: {"ids": [1,2,3], "action": "approve|reject"}"""
    data = get_json_body()
    ids = data.get("ids", [])
    action = data.get("action", "")
    if not ids or action not in ("approve", "reject"):
        return jsonify({"error": "参数错误"}), 400
    try:
        count, failed = ApprovalService.batch_handle(
            ids, action,
            approver={"id": g.current_user["id"], "name": g.current_user["name"]},
            comment=data.get("comment", "")
        )
        if failed:
            return jsonify({
                "message": f"已处理 {count}/{len(ids)} 条",
                "count": count,
                "total": len(ids),
                "failed": failed
            })
        return jsonify({"message": f"已处理 {count} 条", "count": count, "total": len(ids)})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/approvals/stats", methods=["GET"])
@check_auth
@check_permission("approvals:view")
def approval_stats():
    """Approval statistics: avg time, pending > 24h, etc."""
    return jsonify(ApprovalService.get_stats())
