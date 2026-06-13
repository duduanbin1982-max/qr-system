"""
qr-system ? ???????Refactored: SQL ? ApprovalService?
"""
from flask import request, jsonify, g

from modules.app import app
from modules.middleware.auth import check_auth, check_permission, audit_log
from modules.middleware.helpers import get_json_body, parse_pagination
from modules.middleware.validate import validate_json
from modules.services.approval_service import ApprovalService
from modules.db import get_db


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
    db = get_db()
    rows = db.execute("""
        SELECT ac.id, ac.process_id, ac.require_approval, ac.approver_role,
               ac.approval_level, p.name as process_name, p.category
        FROM approval_config ac
        LEFT JOIN processes p ON ac.process_id = p.id
        ORDER BY p.name
    """).fetchall()
    return jsonify({"configs": [dict(r) for r in rows]})


@app.route('/api/approvals/config', methods=['POST'])
@check_auth
@check_permission('approvals:edit')
def save_approval_config():
    """Save approval_config: {process_id: int, require_approval: 1|0, approver_role: str, approval_level: int}
    Also supports batch: {"configs": [{...}, ...]}
    """
    db = get_db()
    data = get_json_body()
    configs = data.get("configs", [data] if "process_id" in data else [])

    for cfg in configs:
        pid = cfg["process_id"]
        require = 1 if cfg.get("require_approval") else 0
        role = cfg.get("approver_role", "admin")
        level = cfg.get("approval_level", 1)

        existing = db.execute(
            "SELECT id FROM approval_config WHERE process_id = ?", (pid,)
        ).fetchone()

        if existing:
            db.execute(
                "UPDATE approval_config SET require_approval=?, approver_role=?, approval_level=? WHERE process_id=?",
                (require, role, level, pid)
            )
        else:
            if require:
                db.execute(
                    "INSERT INTO approval_config (process_id, require_approval, approver_role, approval_level) VALUES (?,?,?,?)",
                    (pid, require, role, level)
                )
            # If require=0 and no existing row, skip (nothing to delete)

        # If require_approval is turned off, delete the config row
        if not require and existing:
            db.execute("DELETE FROM approval_config WHERE process_id = ?", (pid,))

    db.commit()
    return jsonify({"message": "保存成功"})
