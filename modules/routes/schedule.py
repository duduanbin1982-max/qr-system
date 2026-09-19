"""
qr-system - production schedule routes (Refactored: SQL -> Service/Repository)
"""
from flask import g, jsonify, request
from modules.route_decorators import (
    app,
    check_auth,
    check_permission,
    get_json_body,
    require_production_node_write,
    safe_audit_log,
    validate_json,
)
from modules.services.schedule_service import (
    ScheduleConflictError,
    ScheduleNotFoundError,
    ScheduleService,
)
from modules.services.production_line_service import ProductionLineService
from modules.services.schedule_capacity_service import ScheduleCapacityService
from modules.domain.errors import DomainError
from modules.domain.production_node_scheduling import NodeSchedulingError


def _schedule_workflow_response(callback):
    try:
        return jsonify(callback())
    except NodeSchedulingError as exc:
        return jsonify(exc.to_payload()), 409
    except DomainError as exc:
        return jsonify(exc.to_payload()), exc.status_code
    except ValueError as exc:
        message = str(exc)
        status = 404 if "不存在" in message else 400
        return jsonify({"error": message}), status


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
@check_permission("schedules:adjust")
def schedule_update_order(order_id):
    """drag to adjust schedule: update order plan start/end dates"""
    try:
        data = get_json_body()
        plan_start = data.get("plan_start", "")
        plan_end = data.get("plan_end", "")
        ScheduleService.update_order_schedule(
            order_id,
            plan_start,
            plan_end,
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
@check_permission("schedules:adjust")
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


@app.route("/api/schedule/auto-plan", methods=["POST"])
@check_auth
@check_permission("schedules:generate")
def schedule_auto_plan():
    """Generate a priority-ordered plan with an auditable idempotency key."""
    try:
        data = get_json_body()
        result = ScheduleCapacityService.auto_plan_orders(
            start_date=data.get("start_date"),
            auto_plan_key=data.get("auto_plan_key", ""),
            limit=data.get("limit", 100),
            actor_id=g.current_user.get("id") if g.current_user else None,
        )
        safe_audit_log(
            "auto_plan_schedule", "schedule_auto_plan",
            0,
            f"key={result.get('auto_plan_key', '')}; "
            f"status={result.get('status')}; queue={result.get('queue_count', 0)}",
        )
        return jsonify(result)
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
@check_permission("schedules:approve")
def schedule_revision_publish(revision_id):
    try:
        return jsonify(ScheduleCapacityService.publish_revision(
            revision_id, published_by=g.current_user.get("id")
        ))
    except NodeSchedulingError as exc:
        return jsonify(exc.to_payload()), 409
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/schedule/revision-items/<int:revision_item_id>/lock", methods=["POST"])
@check_auth
@check_permission("schedules:lock")
@require_production_node_write
@validate_json("schedule_workflow_action")
def schedule_revision_item_lock(revision_item_id):
    data = get_json_body()
    return _schedule_workflow_response(lambda: ScheduleCapacityService.lock_schedule_item(
        revision_item_id, data["reason"], data["idempotency_key"], g.current_user.get("id")
    ))


@app.route("/api/schedule/revision-items/<int:revision_item_id>/unlock", methods=["POST"])
@check_auth
@check_permission("schedules:unlock")
@require_production_node_write
@validate_json("schedule_workflow_action")
def schedule_revision_item_unlock(revision_item_id):
    data = get_json_body()
    return _schedule_workflow_response(lambda: ScheduleCapacityService.unlock_schedule_item(
        revision_item_id, data["reason"], data["idempotency_key"], g.current_user.get("id")
    ))


@app.route("/api/schedule/revision-items/<int:revision_item_id>/adjust", methods=["POST"])
@check_auth
@check_permission("schedules:adjust")
@require_production_node_write
@validate_json("schedule_revision_item_adjust")
def schedule_revision_item_adjust(revision_item_id):
    data = get_json_body()
    return _schedule_workflow_response(lambda: ScheduleCapacityService.adjust_schedule_item(
        revision_item_id, data["production_node_id"], data["planned_start_at"],
        data["reason"], data["row_version"], data["idempotency_key"],
        g.current_user.get("id"),
    ))


def _revision_workflow(revision_id, operation):
    data = get_json_body()
    method = getattr(ScheduleCapacityService, f"{operation}_revision")
    return _schedule_workflow_response(lambda: method(
        revision_id, data["reason"], data["idempotency_key"], g.current_user.get("id")
    ))


@app.route("/api/schedule/revisions/<int:revision_id>/submit", methods=["POST"])
@check_auth
@check_permission("schedules:submit")
@validate_json("schedule_workflow_action")
def schedule_revision_submit(revision_id):
    return _revision_workflow(revision_id, "submit")


@app.route("/api/schedule/revisions/<int:revision_id>/approve", methods=["POST"])
@check_auth
@check_permission("schedules:approve")
@validate_json("schedule_workflow_action")
def schedule_revision_approve(revision_id):
    return _revision_workflow(revision_id, "approve")


@app.route("/api/schedule/revisions/<int:revision_id>/reject", methods=["POST"])
@check_auth
@check_permission("schedules:reject")
@validate_json("schedule_workflow_action")
def schedule_revision_reject(revision_id):
    return _revision_workflow(revision_id, "reject")


@app.route("/api/schedule/order/<int:order_id>/generate", methods=["POST"])
@check_auth
@check_permission("schedules:generate")
def schedule_generate_operations(order_id):
    try:
        data = get_json_body()
        return jsonify(ScheduleCapacityService.generate_order_schedule(
            order_id,
            start_date=data.get("start_date"),
            schedule_run_key=data.get("schedule_run_key", ""),
            actor_id=g.current_user.get("id") if g.current_user else None,
        ))
    except NodeSchedulingError as exc:
        return jsonify(exc.to_payload()), 409
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/schedule/order/<int:order_id>/shadow-plan", methods=["POST"])
@check_auth
@check_permission("schedules:generate")
@require_production_node_write
@validate_json("schedule_shadow_generate")
def schedule_generate_shadow_plan(order_id):
    data = get_json_body()
    result = ScheduleCapacityService.generate_shadow_order_schedule(
        order_id,
        data["shadow_run_key"],
        start_date=data.get("start_date"),
        actor_id=g.current_user.get("id") if g.current_user else None,
    )
    safe_audit_log(
        "generate_node_shadow_schedule", "order", order_id,
        f"shadow_run_key={data['shadow_run_key']}; shadow_run_id={result.get('shadow_run_id')}",
    )
    return jsonify(result)


@app.route("/api/schedule/order/<int:order_id>/shadow-runs", methods=["GET"])
@check_auth
@check_permission("schedule:view")
def schedule_list_shadow_runs(order_id):
    try:
        return jsonify(ScheduleCapacityService.list_shadow_runs(
            order_id, request.args.get("limit", 100)
        ))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/schedule/shadow-runs/<int:run_id>", methods=["GET"])
@check_auth
@check_permission("schedule:view")
def schedule_shadow_run_detail(run_id):
    try:
        return jsonify(ScheduleCapacityService.get_shadow_run(run_id))
    except DomainError as exc:
        return jsonify(exc.to_payload()), exc.status_code
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/schedule/order/<int:order_id>/dynamic-replan", methods=["POST"])
@check_auth
@check_permission("schedules:generate")
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
    except NodeSchedulingError as exc:
        return jsonify(exc.to_payload()), 409
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/schedule/downtime", methods=["GET"])
@check_auth
def schedule_downtime():
    try:
        return jsonify(ScheduleCapacityService.list_downtime_events(
            production_node_id=request.args.get("production_node_id", type=int),
            process_line_id=request.args.get("process_line_id", type=int),
            start_at=request.args.get("start_at", ""),
            end_at=request.args.get("end_at", ""),
            limit=request.args.get("limit", 1000, type=int),
        ))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/schedule/downtime", methods=["POST"])
@check_auth
@check_permission("production_nodes:downtime_manage")
@require_production_node_write
def schedule_downtime_create():
    try:
        data = get_json_body()
        result = ScheduleCapacityService.create_downtime_event(
            data.get("production_node_id"), data.get("start_at"), data.get("end_at"),
            data.get("reason", ""), created_by=g.current_user.get("id") if g.current_user else None,
        )
        safe_audit_log("create_schedule_downtime", "schedule_downtime", result["event"]["id"],
                       f"node={data.get('production_node_id')}; {data.get('start_at')}~{data.get('end_at')}")
        return jsonify(result)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/schedule/downtime/<int:event_id>", methods=["DELETE"])
@check_auth
@check_permission("production_nodes:downtime_manage")
@require_production_node_write
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
