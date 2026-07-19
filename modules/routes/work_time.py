"""Work time management routes."""

from flask import jsonify, request, g

from modules.route_decorators import (
    app,
    check_auth,
    check_permission,
    get_json_body,
    handle_unexpected_error,
    safe_audit_log,
)
from modules.services.work_time_service import WorkTimeService


def _page_arg():
    return max(request.args.get("page", 1, type=int), 1)


def _limit_arg():
    return min(max(request.args.get("limit", request.args.get("per_page", 20), type=int), 1), 200)


@app.route("/api/work-time/stats", methods=["GET"])
@check_auth
@check_permission("work_time:view")
def work_time_stats():
    try:
        return jsonify({"ok": True, **WorkTimeService.stats()})
    except Exception as exc:
        return handle_unexpected_error(exc, "database operation")


@app.route("/api/work-time/standards", methods=["GET"])
@check_auth
@check_permission("work_time:view")
def work_time_list_standards():
    try:
        filters = {
            "keyword": request.args.get("keyword", request.args.get("search", "")),
            "status": request.args.get("status", ""),
            "product_id": request.args.get("product_id", type=int),
            "process_id": request.args.get("process_id", type=int),
            "route_id": request.args.get("route_id", type=int),
        }
        return jsonify(WorkTimeService.list_standards(filters, _page_arg(), _limit_arg()))
    except Exception as exc:
        return handle_unexpected_error(exc, "database operation")


@app.route("/api/work-time/standards/routes", methods=["GET"])
@check_auth
@check_permission("work_time:view")
def work_time_list_standard_routes():
    try:
        filters = {
            "keyword": request.args.get("keyword", request.args.get("search", "")),
            "status": request.args.get("status", ""),
            "process_id": request.args.get("process_id", type=int),
            "route_id": request.args.get("route_id", type=int),
        }
        return jsonify(WorkTimeService.list_standard_routes(filters, _page_arg(), _limit_arg()))
    except Exception as exc:
        return handle_unexpected_error(exc, "database operation")


@app.route("/api/work-time/standards/route", methods=["POST"])
@check_auth
@check_permission("work_time:edit")
def work_time_save_route_standards():
    try:
        data = get_json_body()
        result = WorkTimeService.save_route_standards(
            data.get("route_id"),
            data.get("items", []),
            g.current_user.get("id"),
            data.get("effective_from", ""),
        )
        safe_audit_log(
            "work_time_route_standards_save",
            "work_time_standard",
            result.get("route_id"),
            "batch saved",
        )
        return jsonify({"ok": True, "message": "路线标准工时已保存", **result})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return handle_unexpected_error(exc, "database operation")


@app.route("/api/work-time/standards", methods=["POST"])
@check_auth
@check_permission("work_time:create")
def work_time_create_standard():
    try:
        standard_id = WorkTimeService.create_standard(get_json_body(), g.current_user.get("id"))
        safe_audit_log("work_time_standard_create", "work_time_standard", standard_id, "created")
        return jsonify({"ok": True, "id": standard_id, "message": "标准工时已创建"})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return handle_unexpected_error(exc, "database operation")


@app.route("/api/work-time/standards/<int:standard_id>", methods=["PUT"])
@check_auth
@check_permission("work_time:edit")
def work_time_update_standard(standard_id):
    try:
        WorkTimeService.update_standard(standard_id, get_json_body(), g.current_user.get("id"))
        safe_audit_log("work_time_standard_update", "work_time_standard", standard_id, "updated")
        return jsonify({"ok": True, "message": "标准工时已更新"})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404 if "不存在" in str(exc) else 400
    except Exception as exc:
        return handle_unexpected_error(exc, "database operation")


@app.route("/api/work-time/standards/<int:standard_id>", methods=["DELETE"])
@check_auth
@check_permission("work_time:edit")
def work_time_delete_standard(standard_id):
    try:
        WorkTimeService.deactivate_standard(standard_id, g.current_user.get("id"))
        safe_audit_log("work_time_standard_deactivate", "work_time_standard", standard_id, "inactive")
        return jsonify({"ok": True, "message": "标准工时已停用"})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404
    except Exception as exc:
        return handle_unexpected_error(exc, "database operation")


@app.route("/api/work-time/records", methods=["GET"])
@check_auth
@check_permission("work_time:view")
def work_time_list_records():
    try:
        filters = {
            "keyword": request.args.get("keyword", request.args.get("search", "")),
            "status": request.args.get("status", ""),
            "review_status": request.args.get("review_status", ""),
            "user_id": request.args.get("user_id", type=int),
            "process_id": request.args.get("process_id", type=int),
            "order_id": request.args.get("order_id", type=int),
            "route_id": request.args.get("route_id", type=int),
            "standard_missing": request.args.get("standard_missing", ""),
            "date_from": request.args.get("from", request.args.get("date_from", "")),
            "date_to": request.args.get("to", request.args.get("date_to", "")),
        }
        return jsonify(WorkTimeService.list_records(filters, _page_arg(), _limit_arg()))
    except Exception as exc:
        return handle_unexpected_error(exc, "database operation")


@app.route("/api/work-time/records", methods=["POST"])
@check_auth
@check_permission("work_time:create")
def work_time_create_record():
    try:
        record_id = WorkTimeService.create_record(get_json_body(), g.current_user.get("id"))
        safe_audit_log("work_time_record_create", "work_time_record", record_id, "created")
        return jsonify({"ok": True, "id": record_id, "message": "工时流水已创建"})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return handle_unexpected_error(exc, "database operation")


@app.route("/api/work-time/records/<int:record_id>/review", methods=["POST"])
@check_auth
@check_permission("work_time:audit")
def work_time_review_record(record_id):
    try:
        WorkTimeService.review_record(record_id, get_json_body(), g.current_user.get("id"))
        safe_audit_log("work_time_record_review", "work_time_record", record_id, "reviewed")
        return jsonify({"ok": True, "message": "工时审核已保存"})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 404 if "不存在" in str(exc) else 400
    except Exception as exc:
        return handle_unexpected_error(exc, "database operation")
