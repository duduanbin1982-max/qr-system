"""qr-system — 操作日忖路由
"""
from flask import g, request, jsonify
from modules.route_decorators import (
    app,
    check_auth,
    check_permission,
    get_json_body,
    has_permission,
)
from modules.services.audit_log_service import AuditLogService
from modules.services.audit_retention_service import AuditRetentionService
from modules.audit_query import parse_audit_query
from modules.audit_policy import AUDIT_MIN_RETENTION_DAYS
from modules.audit_action_catalog import AUDIT_CATEGORY_LABELS, category_options


def _require_audit_admin():
    if not has_permission(g.current_user, "users:admin"):
        return jsonify({"error": "仅审计管理员可以管理日志保留策略"}), 403
    return None


@app.route("/api/logs", methods=["GET"])
@check_auth
@check_permission("logs:view")
def list_logs():
    try:
        query = parse_audit_query(
            page=request.args.get("page", "1"),
            limit=request.args.get("limit", "50"),
            date_from=request.args.get("date_from", ""),
            date_to=request.args.get("date_to", ""),
            keyword=request.args.get("keyword", ""),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    category = request.args.get("category", "").strip()
    if category and category not in AUDIT_CATEGORY_LABELS:
        return jsonify({"error": "无效的日志分类"}), 400
    result = AuditLogService.list_logs(
        page=query["page"],
        limit=query["limit"],
        action=request.args.get("action", "").strip(),
        keyword=query["keyword"],
        user_id=request.args.get("user_id", type=int),
        category=category,
        date_from=query["date_from"],
        date_to=query["date_to"],
    )
    return jsonify(result)


@app.route("/api/logs/categories", methods=["GET"])
@check_auth
@check_permission("logs:view")
def list_log_categories():
    return jsonify({"items": category_options()})


@app.route("/api/logs/clear", methods=["POST"])
@check_auth
@check_permission("logs:delete")
def clear_logs():
    denied = _require_audit_admin()
    if denied:
        return denied
    data = get_json_body()
    days = data.get("before_days", AUDIT_MIN_RETENTION_DAYS) if data else AUDIT_MIN_RETENTION_DAYS
    reason = data.get("reason", "") if data else ""
    if not isinstance(days, int) or days < AUDIT_MIN_RETENTION_DAYS or days > 3650:
        return jsonify({"error": f"before_days must be {AUDIT_MIN_RETENTION_DAYS}-3650"}), 400
    try:
        result = AuditRetentionService.request_cleanup(days, reason, g.current_user)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({
        "message": "清理申请已提交，待审计管理员批准后执行",
        "request_id": result["id"],
        "before_at": result["before_at"],
        "affected_count": result["affected_count"],
    }), 202


@app.route("/api/logs/cleanup-requests", methods=["GET"])
@check_auth
@check_permission("logs:delete")
def list_cleanup_requests():
    denied = _require_audit_admin()
    if denied:
        return denied
    try:
        items = AuditRetentionService.list_requests(
            status=request.args.get("status", "").strip(),
            limit=request.args.get("limit", 100, type=int) or 100,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"items": items})


@app.route("/api/logs/cleanup-requests/<int:request_id>/approve", methods=["POST"])
@check_auth
@check_permission("logs:delete")
def approve_cleanup_request(request_id):
    denied = _require_audit_admin()
    if denied:
        return denied
    data = get_json_body()
    try:
        result = AuditRetentionService.approve_and_execute(
            request_id, g.current_user, data.get("reason", "")
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({
        "message": "清理申请已批准并完成归档清理",
        **result,
    })


@app.route("/api/logs/cleanup-requests/<int:request_id>/reject", methods=["POST"])
@check_auth
@check_permission("logs:delete")
def reject_cleanup_request(request_id):
    denied = _require_audit_admin()
    if denied:
        return denied
    data = get_json_body()
    try:
        AuditRetentionService.reject_request(
            request_id, g.current_user, data.get("reason", "")
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"message": "清理申请已驳回"})
