"""
qr-system — 生产排程路由（Refactored: SQL → ScheduleService）
"""
from flask import jsonify, request
from modules.app import app
from modules.middleware.audit import audit_log
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.helpers import get_json_body
from modules.middleware.error_handler import handle_unexpected_error
from modules.services.schedule_service import ScheduleService
from modules.db import get_db


@app.route("/api/schedule/gantt", methods=["GET"])
@check_auth
@check_permission("schedule:view")
def schedule_gantt():
    try:
        return jsonify(ScheduleService.get_gantt_data())
    except Exception as e:
        return handle_unexpected_error(e, "database operation")


@app.route("/api/schedule/order/<int:order_id>", methods=["PUT"])
@check_auth
@check_permission("schedule:view")
def schedule_update_order(order_id):
    """拖拽调整排程：更新订单的计划开始/结束日期"""
    try:
        data = get_json_body()
        plan_start = data.get("plan_start", "").strip()
        plan_end = data.get("plan_end", "").strip()

        if not plan_start or not plan_end:
            return jsonify({"error": "计划开始和结束日期不能为空"}), 400

        ScheduleService.update_order_schedule(order_id, plan_start, plan_end)
        audit_log("update_schedule", "order", order_id,
                  f"plan: {plan_start} ~ {plan_end}")
        return jsonify({"ok": True, "message": "排程已更新"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return handle_unexpected_error(e, "database operation")

@app.route("/api/schedule/batch-shift", methods=["POST"])
@check_auth
@check_permission("schedule:view")
def schedule_batch_shift():
    """批量偏移排程: {order_ids: [1,2,3], days: 3}"""
    try:
        data = get_json_body()
        ids = data.get("order_ids", [])
        days = int(data.get("days", 0))
        if not ids or days == 0:
            return jsonify({"error": "参数错误"}), 400

        count = ScheduleService.batch_shift(ids, days)
        audit_log("batch_shift_schedule", "orders", 0,
                  f"shifted {count} orders by {days} days")
        return jsonify({"ok": True, "count": count, "message": f"已偏移 {count} 个订单 {days} 天"})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return handle_unexpected_error(e, "database operation")
@app.route("/api/production-lines", methods=["GET"])
@check_auth
def list_production_lines():
    """List all production lines"""
    db = get_db()
    rows = db.execute(
        "SELECT * FROM production_lines ORDER BY name"
    ).fetchall()
    return jsonify({"lines": [dict(r) for r in rows]})


@app.route("/api/production-lines", methods=["POST"])
@check_auth
@check_permission("settings:edit")
def create_production_line():
    """Create a production line"""
    data = get_json_body()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "产线名称不能为空"}), 400
    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO production_lines (name, capacity_per_day, remark) VALUES (?, ?, ?)",
            (name, data.get("capacity_per_day", 10), data.get("remark", ""))
        )
        db.commit()
        return jsonify({"id": cur.lastrowid, "message": "创建成功"})
    except Exception as e:
        if "UNIQUE" in str(e):
            return jsonify({"error": "产线名称已存在"}), 400
        raise


@app.route("/api/production-lines/<int:line_id>", methods=["PUT"])
@check_auth
@check_permission("settings:edit")
def update_production_line(line_id):
    """Update a production line"""
    data = get_json_body()
    db = get_db()
    db.execute(
        "UPDATE production_lines SET name=?, capacity_per_day=?, remark=?, status=? WHERE id=?",
        (data.get("name", ""), data.get("capacity_per_day", 10),
         data.get("remark", ""), data.get("status", "active"), line_id)
    )
    db.commit()
    return jsonify({"message": "更新成功"})


@app.route("/api/production-lines/<int:line_id>", methods=["DELETE"])
@check_auth
@check_permission("settings:edit")
def delete_production_line(line_id):
    """Delete a production line (only if no orders reference it)"""
    db = get_db()
    used = db.execute(
        "SELECT COUNT(*) FROM orders WHERE production_line_id = ? AND deleted_at IS NULL",
        (line_id,)
    ).fetchone()[0]
    if used:
        return jsonify({"error": f"该产线被 {used} 个订单使用，无法删除"}), 400
    db.execute("DELETE FROM production_lines WHERE id = ?", (line_id,))
    db.commit()
    return jsonify({"message": "已删除"})
