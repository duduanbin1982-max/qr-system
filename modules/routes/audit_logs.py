"""qr-system — 操作日志路由"""
from flask import request, jsonify
from modules.app import app
from modules.middleware.audit import audit_log
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.helpers import get_json_body
from modules.services.audit_log_service import AuditLogService


@app.route("/api/logs", methods=["GET"])
@check_auth
@check_permission("logs:view")
def list_logs():
    result = AuditLogService.list_logs(
        page=request.args.get("page", 1, type=int),
        limit=min(request.args.get("limit", 50, type=int), 200),
        action=request.args.get("action", "").strip(),
        keyword=request.args.get("keyword", "").strip(),
        user_id=request.args.get("user_id", type=int),
        category=request.args.get("category", "").strip(),
    )
    return jsonify(result)


@app.route("/api/logs/clear", methods=["POST"])
@check_auth
@check_permission("logs:delete")
def clear_logs():
    data = get_json_body()
    days = data.get("before_days", 90) if data else 90
    if not isinstance(days, int) or days < 1 or days > 3650:
        return jsonify({"error": "days must be 1-3650"}), 400
    count = AuditLogService.clear_logs(days)
    audit_log("clear_logs", detail=f"deleted {count} logs older than {days} days")
    return jsonify({"message": f"Cleared {count} logs", "deleted": count})
