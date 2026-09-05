"""
qr-system - production schedule routes (Refactored: SQL -> Service/Repository)
"""
from flask import g, jsonify, request
from modules.route_decorators import (
    app,
    check_auth,
    check_permission,
    get_json_body,
    has_permission,
    safe_audit_log,
)
from modules.services.schedule_service import (
    ScheduleConflictError,
    ScheduleNotFoundError,
    ScheduleService,
)
from modules.services.production_line_service import ProductionLineService
from modules.services.schedule_capacity_service import ScheduleCapacityService


@app.route("/api/schedule/gantt", methods=["GET"])
@check_auth
@check_permission("schedule:view")
def schedule_gantt():
    limit = request.args.get("limit", 200, type=int)
    offset = request.args.get("offset", 0, type=int)
    schedule_scope = request.args.get("status", "active")
    return jsonify(ScheduleService.get_gantt_data(
        limit=limit, offset=offset, schedule_scope=schedule_scope
    ))


@app.route("/api/schedule/order/<int:order_id>", methods=["PUT", "PATCH"])
@check_auth
@check_permission("schedule:edit")
def schedule_update_order(order_id):
    """drag to adjust schedule: update order plan start/end dates"""
    try:
        data = get_json_body()
        plan_start = data.get("plan_start", "")
        plan_end = data.get("plan_end", "")
        update_kwargs = {}
        if "production_line_id" in data:
            update_kwargs["production_line_id"] = data.get("production_line_id")

        ScheduleService.update_order_schedule(
            order_id,
            plan_start,
            plan_end,
            **update_kwargs,
        )
        safe_audit_log("update_schedule", "order", order_id,
                       f"plan: {plan_start} ~ {plan_end}")
        return jsonify({"ok": True, "message": "排程已更新"})
    except ScheduleNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except ScheduleConflictError as e:
        return jsonify({"error": str(e)}), 409
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/schedule/batch-shift", methods=["POST"])
@check_auth
@check_permission("schedule:edit")
def schedule_batch_shift():
    """batch shift schedule: {order_ids: [1,2,3], days: 3}"""
    try:
        data = get_json_body()
        days = data.get("days", 0)
        count = ScheduleService.batch_shift(data.get("order_ids", []), days)
        safe_audit_log("batch_shift_schedule", "orders", 0,
                       f"shifted {count} orders by {days} days")
        return jsonify({"ok": True, "count": count, "message": f"已调整 {count} 个订单，共 {days} 天"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/schedule/capacity-lines", methods=["GET"])
@check_auth
@check_permission("schedule:view")
def schedule_capacity_lines():
    try:
        process_id = request.args.get("process_id", type=int)
        return jsonify(ScheduleCapacityService.list_lines(
            process_id, request.args.get("limit", 500)
        ))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/schedule/calendars", methods=["GET"])
@check_auth
@check_permission("schedule:view")
def schedule_calendars():
    return jsonify(ScheduleCapacityService.list_calendars())


@app.route("/api/schedule/capacity-orders", methods=["GET"])
@check_auth
@check_permission("schedule:view")
def schedule_capacity_orders():
    try:
        return jsonify(ScheduleCapacityService.list_schedulable_orders(
            request.args.get("limit", 500)
        ))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/schedule/order/<int:order_id>/operations", methods=["GET"])
@check_auth
@check_permission("schedule:view")
def schedule_order_operations(order_id):
    try:
        return jsonify(ScheduleCapacityService.list_order_schedule(
            order_id, request.args.get("limit", 500)
        ))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/schedule/order/<int:order_id>/revisions", methods=["GET"])
@check_auth
@check_permission("schedule:view")
def schedule_order_revisions(order_id):
    try:
        return jsonify(ScheduleCapacityService.list_order_revisions(
            order_id, request.args.get("limit", 100)
        ))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/schedule/revisions/<int:revision_id>", methods=["GET"])
@check_auth
@check_permission("schedule:view")
def schedule_revision_detail(revision_id):
    try:
        return jsonify(ScheduleCapacityService.get_revision(
            revision_id, request.args.get("limit", 1000)
        ))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/schedule/revisions/<int:revision_id>/publish", methods=["POST"])
@check_auth
@check_permission("schedule:edit")
def schedule_revision_publish(revision_id):
    try:
        return jsonify(ScheduleCapacityService.publish_revision(
            revision_id, published_by=g.current_user.get("id")
        ))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/schedule/order/<int:order_id>/generate", methods=["POST"])
@check_auth
@check_permission("schedule:edit")
def schedule_generate_operations(order_id):
    try:
        data = get_json_body()
        return jsonify(ScheduleCapacityService.generate_order_schedule(
            order_id,
            start_date=data.get("start_date"),
            schedule_run_key=data.get("schedule_run_key", ""),
        ))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/schedule/order/<int:order_id>/dynamic-replan", methods=["POST"])
@check_auth
@check_permission("schedule:edit")
def schedule_dynamic_replan(order_id):
    """Replan unfinished work from approved reports, rework and downtime facts."""
    try:
        data = get_json_body()
        result = ScheduleCapacityService.dynamic_replan_order(
            order_id,
            start_at=data.get("start_at"),
            schedule_run_key=data.get("schedule_run_key", ""),
            reason=data.get("reason", ""),
            actor_id=g.current_user.get("id") if g.current_user else None,
        )
        safe_audit_log("dynamic_replan_schedule", "order", order_id,
                       f"run={data.get('schedule_run_key', '')}; reason={data.get('reason', '')}")
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/schedule/downtime", methods=["GET", "POST"])
@check_auth
def schedule_downtime():
    if request.method == "GET":
        try:
            return jsonify(ScheduleCapacityService.list_downtime_events(
                process_line_id=request.args.get("process_line_id", type=int),
                start_at=request.args.get("start_at", ""),
                end_at=request.args.get("end_at", ""),
                limit=request.args.get("limit", 1000, type=int),
            ))
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
    if not has_permission(g.current_user, "schedule:edit"):
        return jsonify({"error": "无权限"}), 403
    try:
        data = get_json_body()
        result = ScheduleCapacityService.create_downtime_event(
            data.get("process_line_id"), data.get("start_at"), data.get("end_at"),
            data.get("reason", ""), created_by=g.current_user.get("id") if g.current_user else None,
        )
        safe_audit_log("create_schedule_downtime", "schedule_downtime", result["event"]["id"],
                       f"line={data.get('process_line_id')}; {data.get('start_at')}~{data.get('end_at')}")
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/schedule/downtime/<int:event_id>", methods=["DELETE"])
@check_auth
@check_permission("schedule:edit")
def schedule_downtime_cancel(event_id):
    try:
        result = ScheduleCapacityService.cancel_downtime_event(event_id)
        safe_audit_log("cancel_schedule_downtime", "schedule_downtime", event_id, "status=cancelled")
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/schedule/operations", methods=["GET"])
@check_auth
@check_permission("schedule:view")
def schedule_operations():
    try:
        return jsonify(ScheduleCapacityService.list_schedules(
            request.args.get("limit", 500)
        ))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/schedule/capacity-audit", methods=["GET"])
@check_auth
@check_permission("schedule:view")
def schedule_capacity_audit():
    try:
        return jsonify(ScheduleCapacityService.audit_schedule_capacity(
            request.args.get("limit", 1000)
        ))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


# ========== Production Lines (via ProductionLineService) ==========

@app.route("/api/production-lines", methods=["GET"])
@check_auth
def list_production_lines():
    """List all production lines"""
    return jsonify(ProductionLineService.list_all())


@app.route("/api/production-lines", methods=["POST"])
@check_auth
@check_permission("settings:edit")
def create_production_line():
    """Create a production line"""
    try:
        data = get_json_body()
        result = ProductionLineService.create(
            name=data.get("name", ""),
            capacity_per_day=data.get("capacity_per_day", 10),
            remark=data.get("remark", "")
        )
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/production-lines/<int:line_id>", methods=["PUT"])
@check_auth
@check_permission("settings:edit")
def update_production_line(line_id):
    """Update a production line"""
    try:
        data = get_json_body()
        result = ProductionLineService.update(
            line_id=line_id,
            name=data.get("name", ""),
            capacity_per_day=data.get("capacity_per_day", 10),
            remark=data.get("remark", ""),
            status=data.get("status", "active")
        )
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404


@app.route("/api/production-lines/<int:line_id>", methods=["DELETE"])
@check_auth
@check_permission("settings:edit")
def delete_production_line(line_id):
    """Delete a production line (only if no orders reference it)"""
    try:
        result = ProductionLineService.delete(line_id)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
