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
        SELECT ac.id, ac.process_id, COALESCE(ac.require_approval, 0) as require_approval,
               COALESCE(ac.approver_role, 'admin') as approver_role,
               COALESCE(ac.approval_level, 1) as approval_level,
               COALESCE(ac.approver_role_2, '') as approver_role_2,
               COALESCE(ac.approver_role_3, '') as approver_role_3,
               p.name as process_name, p.category
        FROM processes p
        LEFT JOIN approval_config ac ON ac.process_id = p.id
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
    from modules.services import BaseService
    data = get_json_body()
    configs = data.get("configs", [data] if "process_id" in data else [])

    with BaseService.transaction() as txn:
        for cfg in configs:
            pid = cfg["process_id"]
            require = 1 if cfg.get("require_approval") else 0
            role = cfg.get("approver_role", "admin")
            role2 = cfg.get("approver_role_2", "")
            role3 = cfg.get("approver_role_3", "")
            level = cfg.get("approval_level", 1)

            existing = txn.execute(
                "SELECT id FROM approval_config WHERE process_id = ?", (pid,)
            ).fetchone()

            if existing:
                txn.execute(
                    "UPDATE approval_config SET require_approval=?, approver_role=?, approver_role_2=?, approver_role_3=?, approval_level=? WHERE process_id=?",
                    (require, role, role2, role3, level, pid)
                )
            else:
                if require:
                    txn.execute(
                        "INSERT INTO approval_config (process_id, require_approval, approver_role, approver_role_2, approver_role_3, approval_level) VALUES (?,?,?,?,?,?)",
                        (pid, require, role, role2, role3, level)
                    )

            # If require_approval is turned off, delete the config row
            if not require and existing:
                txn.execute("DELETE FROM approval_config WHERE process_id = ?", (pid,))

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
    db = get_db()
    pending = db.execute("SELECT COUNT(*) FROM approval_records WHERE status='pending'").fetchone()[0]
    avg_row = db.execute("""
        SELECT ROUND(AVG(
            (julianday(processed_at) - julianday(created_at)) * 24
        ), 1) as avg_hours
        FROM approval_records
        WHERE status != 'pending' AND processed_at IS NOT NULL
    """).fetchone()
    pending_over = db.execute("""
        SELECT COUNT(*) FROM approval_records
        WHERE status='pending' AND created_at < datetime('now','localtime','-24 hours')
    """).fetchone()[0]
    total = db.execute("SELECT COUNT(*) FROM approval_records").fetchone()[0]
    return jsonify({
        "pending": pending,
        "avg_hours": avg_row["avg_hours"] or 0,
        "pending_over_24h": pending_over,
        "total": total
    })
