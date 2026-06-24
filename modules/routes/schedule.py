"""
qr-system - production schedule routes (Refactored: SQL -> Service/Repository)
"""
from flask import jsonify, request
from modules.app import app
from modules.middleware.audit import audit_log
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.helpers import get_json_body
from modules.middleware.error_handler import handle_unexpected_error
from modules.services.schedule_service import ScheduleService
from modules.services.production_line_service import ProductionLineService


@app.route("/api/schedule/gantt", methods=["GET"])
@check_auth
@check_permission("schedule:view")
def schedule_gantt():
    try:
        limit = request.args.get("limit", 200, type=int)
        offset = request.args.get("offset", 0, type=int)
        return jsonify(ScheduleService.get_gantt_data(limit=limit, offset=offset))
    except Exception as e:
        return handle_unexpected_error(e, "database operation")


@app.route("/api/schedule/order/<int:order_id>", methods=["PUT"])
@check_auth
@check_permission("schedule:view")
def schedule_update_order(order_id):
    """drag to adjust schedule: update order plan start/end dates"""
    try:
        data = get_json_body()
        plan_start = data.get("plan_start", "").strip()
        plan_end = data.get("plan_end", "").strip()
        production_line_id = data.get("production_line_id") or None

        if not plan_start or not plan_end:
            return jsonify({"error": "plan start and end dates required"}), 400

        ScheduleService.update_order_schedule(order_id, plan_start, plan_end, production_line_id)
        audit_log("update_schedule", "order", order_id,
                  f"plan: {plan_start} ~ {plan_end}")
        return jsonify({"ok": True, "message": "schedule updated"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return handle_unexpected_error(e, "database operation")


@app.route("/api/schedule/batch-shift", methods=["POST"])
@check_auth
@check_permission("schedule:view")
def schedule_batch_shift():
    """batch shift schedule: {order_ids: [1,2,3], days: 3}"""
    try:
        data = get_json_body()
        ids = data.get("order_ids", [])
        days = int(data.get("days", 0))
        if not ids or days == 0:
            return jsonify({"error": "invalid params"}), 400
        if len(ids) > 50:
            return jsonify({"error": "max 50 orders per batch"}), 400
        if abs(days) > 30:
            return jsonify({"error": "max 30 days offset"}), 400

        count = ScheduleService.batch_shift(ids, days)
        audit_log("batch_shift_schedule", "orders", 0,
                  f"shifted {count} orders by {days} days")
        return jsonify({"ok": True, "count": count, "message": f"shifted {count} orders by {days} days"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return handle_unexpected_error(e, "database operation")


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
