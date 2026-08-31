"""Persistence for process-level production-line pools and operation schedules."""

import hashlib
import json

from modules.repositories.context import resolve_db
from modules.schedule_capacity_config import (
    DEFAULT_DAILY_MINUTES,
    DEFAULT_PROCESS_LINE_COUNTS,
)


class ScheduleCapacityRepository:
    @staticmethod
    def ensure_order_version_bindings(order_id, db):
        """Materialize exact route/process revisions for a schedulable order.

        This is deliberately idempotent: legacy rows are upgraded only when a
        single route/process topology can prove the binding.
        """
        order = db.execute(
            "SELECT id,route_id,route_version_id,route_name_snapshot FROM orders "
            "WHERE id=? AND deleted_at IS NULL", (order_id,)
        ).fetchone()
        if not order:
            return None
        route_version_id = order["route_version_id"]
        route_name = order["route_name_snapshot"] or ""
        if route_version_id is not None:
            route_binding = db.execute(
                "SELECT process_route_id,name FROM process_route_versions WHERE id=?",
                (route_version_id,),
            ).fetchone()
            if route_binding is None or route_binding["process_route_id"] != order["route_id"]:
                raise ValueError("订单—路线版本绑定不一致")
            if not route_name:
                route_name = route_binding["name"] or ""
        if order["route_id"] is not None and route_version_id is None:
            route = db.execute(
                "SELECT current_effective_version_id FROM process_routes WHERE id=?",
                (order["route_id"],),
            ).fetchone()
            route_version_id = route["current_effective_version_id"] if route else None
            if route_version_id is None:
                route = db.execute(
                    "SELECT id FROM process_route_versions WHERE process_route_id=? "
                    "ORDER BY CASE WHEN status='published' THEN 0 ELSE 1 END,version DESC,id DESC LIMIT 1",
                    (order["route_id"],),
                ).fetchone()
                route_version_id = route["id"] if route else None
            if route_version_id is None:
                raise ValueError("订单路线尚未绑定有效路线版本")
        if route_version_id is not None and not route_name:
            route_row = db.execute("SELECT name FROM process_route_versions WHERE id=?", (route_version_id,)).fetchone()
            route_name = route_row["name"] if route_row else ""

        ops = db.execute(
            "SELECT id,process_id,process_version_id FROM order_processes WHERE order_id=? ORDER BY seq_order,id",
            (order_id,),
        ).fetchall()
        for op in ops:
            process_version_id = op["process_version_id"]
            if route_version_id is not None:
                item = db.execute(
                    "SELECT process_version_id FROM process_route_version_items "
                    "WHERE route_version_id=? AND process_id=?",
                    (route_version_id, op["process_id"]),
                ).fetchone()
                if item is None:
                    raise ValueError("订单—路线—工序版本绑定不一致")
                if op["process_version_id"] is not None and op["process_version_id"] != item["process_version_id"]:
                    raise ValueError("订单—路线—工序版本绑定不一致")
                process_version_id = item["process_version_id"]
            if process_version_id is None:
                row = db.execute(
                    "SELECT current_effective_version_id FROM processes WHERE id=?",
                    (op["process_id"],),
                ).fetchone()
                process_version_id = row["current_effective_version_id"] if row else None
            if process_version_id is None:
                row = db.execute(
                    "SELECT id FROM process_versions WHERE process_id=? "
                    "ORDER BY CASE WHEN status='published' THEN 0 ELSE 1 END,version DESC,id DESC LIMIT 1",
                    (op["process_id"],),
                ).fetchone()
                process_version_id = row["id"] if row else None
            version = db.execute(
                "SELECT process_code_snapshot,name,category FROM process_versions WHERE id=? AND process_id=?",
                (process_version_id, op["process_id"]),
            ).fetchone() if process_version_id else None
            if version is None:
                raise ValueError("订单工序尚未绑定有效工序版本")
            db.execute(
                "UPDATE order_processes SET process_version_id=?,process_code_snapshot=?,"
                "process_name_snapshot=?,process_category_snapshot=? WHERE id=?",
                (process_version_id, version["process_code_snapshot"], version["name"], version["category"], op["id"]),
            )
        db.execute(
            "UPDATE orders SET route_version_id=?,route_name_snapshot=? WHERE id=?",
            (route_version_id, route_name, order_id),
        )
        return db.execute(
            "SELECT id,quantity,plan_start,product_code,product_name,route_id,route_version_id,route_name_snapshot "
            "FROM orders WHERE id=? AND deleted_at IS NULL", (order_id,)
        ).fetchone()

    @staticmethod
    def ensure_default_lines(process_id, process_name, db):
        count = DEFAULT_PROCESS_LINE_COUNTS.get(process_name)
        if not count:
            return 0
        profile = db.execute(
            "SELECT configured_line_count FROM process_capacity_profiles WHERE process_id=?",
            (process_id,),
        ).fetchone()
        if profile:
            return 0
        existing = db.execute(
            "SELECT id, line_code FROM process_production_lines WHERE process_id=? ORDER BY id",
            (process_id,),
        ).fetchall()
        # A pool belongs to the stable process root. If the display name changes,
        # never infer a new desired size and silently expand the pool.
        if existing:
            db.execute(
                "INSERT OR IGNORE INTO process_capacity_profiles "
                "(process_id,configured_line_count,source_process_name) VALUES (?,?,?)",
                (process_id, len(existing), process_name),
            )
            return 0
        used_codes = {row["line_code"] for row in existing}
        inserted = 0
        for index in range(1, count + 1):
            code = f"{process_name}-{index:02d}"
            if code in used_codes:
                continue
            cursor = db.execute(
                "INSERT OR IGNORE INTO process_production_lines "
                "(process_id,line_code,line_name,daily_minutes,remark) VALUES (?,?,?,?,?)",
                (process_id, code, f"{process_name}{index}线", DEFAULT_DAILY_MINUTES, "系统默认产线"),
            )
            inserted += cursor.rowcount
        db.execute(
            "INSERT OR IGNORE INTO process_capacity_profiles "
            "(process_id,configured_line_count,source_process_name) VALUES (?,?,?)",
            (process_id, count, process_name),
        )
        return inserted
    @staticmethod
    def list_schedulable_orders(limit=500, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id, order_no, quantity, product_code, product_name, plan_start, plan_end, "
            "deadline, status FROM orders WHERE deleted_at IS NULL "
            "AND status != 'completed' ORDER BY CASE WHEN deadline='' THEN 1 ELSE 0 END, "
            "deadline, plan_start, id LIMIT ?",
            (min(max(int(limit or 500), 1), 1000),),
        ).fetchall()
    @staticmethod
    def find_order(order_id, db):
        return db.execute(
            "SELECT id, quantity, plan_start, product_code, product_name, route_id, "
            "route_version_id, route_name_snapshot FROM orders "
            "WHERE id=? AND deleted_at IS NULL",
            (order_id,),
        ).fetchone()

    @staticmethod
    def find_active_standard(
        route_id, route_version_id, process_id, process_version_id, product_code, db
    ):
        """Resolve a valid standard, preferring exact route/process revisions."""
        base = (
            "SELECT id,version,setup_minutes,standard_minutes_per_unit,difficulty_factor,"
            "route_id,route_version_id,process_id,process_version_id "
            "FROM work_time_standards WHERE process_id=? AND status='active' "
            "AND standard_minutes_per_unit>0 "
            "AND (effective_from='' OR effective_from IS NULL OR effective_from<=date('now')) "
            "AND (effective_to='' OR effective_to IS NULL OR effective_to>=date('now')) "
        )
        params = (process_id,)
        if route_version_id and process_version_id:
            row = db.execute(
                base + "AND route_version_id=? AND process_version_id=? "
                "ORDER BY CASE WHEN product_code=? THEN 0 ELSE 1 END,id DESC LIMIT 1",
                params + (route_version_id, process_version_id, product_code or ""),
            ).fetchone()
            if row:
                return row
        if route_id:
            row = db.execute(
                base + "AND route_id=? AND (route_version_id IS NULL OR route_version_id=?) "
                "ORDER BY CASE WHEN product_code=? THEN 0 ELSE 1 END,id DESC LIMIT 1",
                params + (route_id, route_version_id, product_code or ""),
            ).fetchone()
            if row:
                return row
        return db.execute(
            base + "AND route_id IS NULL AND route_version_id IS NULL "
            "AND (process_version_id IS NULL OR process_version_id=?) "
            "ORDER BY CASE WHEN product_code=? THEN 0 ELSE 1 END,id DESC LIMIT 1",
            params + (process_version_id, product_code or ""),
        ).fetchone()

    @staticmethod
    def update_order_summary(order_id, start_date, end_date, db):
        db.execute(
            "UPDATE orders SET plan_start=?, plan_end=?, "
            "schedule_version=COALESCE(schedule_version,1)+1, "
            "updated_at=datetime('now','localtime') WHERE id=?",
            (start_date, end_date, order_id),
        )

    @staticmethod
    def list_process_lines(process_id=None, db=None, limit=1000):
        db = resolve_db(db)
        limit = min(max(int(limit or 1000), 1), 1000)
        if process_id is None:
            return db.execute(
                "SELECT pl.*, p.name AS process_name FROM process_production_lines pl "
                "JOIN processes p ON p.id=pl.process_id ORDER BY p.seq_order, p.id, pl.line_code LIMIT ?",
                (limit,)
            ).fetchall()
        return db.execute(
            "SELECT pl.*, p.name AS process_name FROM process_production_lines pl "
            "JOIN processes p ON p.id=pl.process_id WHERE pl.process_id=? "
            "ORDER BY pl.line_code LIMIT ?", (process_id, limit)
        ).fetchall()

    @staticmethod
    def find_line(line_id, db=None):
        db = resolve_db(db)
        return db.execute("SELECT * FROM process_production_lines WHERE id=?", (line_id,)).fetchone()

    @staticmethod
    def find_order_operations(order_id, db=None, limit=1000):
        db = resolve_db(db)
        limit = min(max(int(limit or 1000), 1), 1000)
        return db.execute(
            "SELECT op.id AS order_process_id, op.order_id, op.process_id, op.seq_order, "
            "op.status, op.completed, op.scrapped, op.process_version_id, "
            "op.process_code_snapshot, op.process_name_snapshot, op.process_category_snapshot, "
            "o.route_id, o.route_version_id, o.route_name_snapshot, p.name AS process_name, "
            "s.id AS schedule_id, s.process_line_id, s.quantity AS scheduled_quantity, "
            "s.route_version_id AS scheduled_route_version_id, s.process_version_id AS scheduled_process_version_id, "
            "s.standard_id, s.standard_version, s.process_name_snapshot AS scheduled_process_name_snapshot, "
            "s.route_name_snapshot AS scheduled_route_name_snapshot, s.standard_minutes_per_unit, "
            "s.setup_minutes, s.difficulty_factor, s.planned_minutes, s.plan_start, s.plan_end, "
            "s.status AS schedule_status, s.blocked_reason, s.schedule_run_key, s.schedule_run_id, pl.line_name "
            "FROM order_processes op JOIN orders o ON o.id=op.order_id JOIN processes p ON p.id=op.process_id "
            "LEFT JOIN order_process_schedules s ON s.order_process_id=op.id "
            "LEFT JOIN process_production_lines pl ON pl.id=s.process_line_id "
            "WHERE op.order_id=? ORDER BY op.seq_order, op.id LIMIT ?", (order_id, limit)
        ).fetchall()

    @staticmethod
    def clear_order_schedules(order_id, db):
        db.execute("DELETE FROM order_process_schedules WHERE order_id=?", (order_id,))

    @staticmethod
    def find_run(schedule_run_key, db=None):
        db = resolve_db(db)
        return db.execute("SELECT * FROM schedule_runs WHERE schedule_run_key=?", (schedule_run_key,)).fetchone()

    @staticmethod
    def create_run(order_id, schedule_run_key, start_date, db):
        cur = db.execute(
            "INSERT INTO schedule_runs (schedule_run_key,order_id,status,requested_start_date) VALUES (?,?,?,?)",
            (schedule_run_key, order_id, "started", start_date or ""),
        )
        return cur.lastrowid

    @staticmethod
    def complete_run(run_id, status, result, error_message="", db=None):
        db = resolve_db(db)
        payload = json.dumps(result or [], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        db.execute(
            "UPDATE schedule_runs SET status=?,result_json=?,result_digest=?,error_message=?,"
            "completed_at=datetime('now','localtime') WHERE id=?",
            (status, payload, digest, error_message or "", run_id),
        )

    @staticmethod
    def run_result(run):
        try:
            result = json.loads(run["result_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            result = []
        return result if isinstance(result, list) else []

    @staticmethod
    def line_available_dates(exclude_order_id, db):
        """Return the first free date after schedules belonging to other orders."""
        return db.execute(
            "SELECT s.process_line_id, MAX(s.plan_end) AS last_end "
            "FROM order_process_schedules s JOIN orders o ON o.id=s.order_id "
            "WHERE s.order_id != ? AND o.deleted_at IS NULL AND s.process_line_id IS NOT NULL "
            "AND s.status != 'blocked' GROUP BY s.process_line_id",
            (exclude_order_id,),
        ).fetchall()

    @staticmethod
    def insert_operation_schedule(data, db):
        binding = db.execute(
            "SELECT o.route_id,o.route_version_id,op.process_id,op.process_version_id "
            "FROM orders o JOIN order_processes op ON op.order_id=o.id AND op.id=? "
            "WHERE o.id=? AND o.deleted_at IS NULL",
            (data["order_process_id"], data["order_id"]),
        ).fetchone()
        if binding is None or binding["process_id"] != data["process_id"]:
            raise ValueError("订单、订单工序和工序归属关系不一致")
        if data.get("route_version_id") != binding["route_version_id"] or data.get("process_version_id") != binding["process_version_id"]:
            raise ValueError("订单—路线—工序版本绑定不一致")
        cur = db.execute(
            "INSERT INTO order_process_schedules (order_id,order_process_id,process_id,process_line_id,"
            "seq_order,quantity,standard_minutes_per_unit,setup_minutes,difficulty_factor,planned_minutes,plan_start,plan_end,"
            "status,blocked_reason,schedule_run_key,route_version_id,process_version_id,standard_id,standard_version,"
            "process_name_snapshot,route_name_snapshot,schedule_run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (data["order_id"], data["order_process_id"], data["process_id"], data.get("process_line_id"),
             data.get("seq_order", 0), data.get("quantity", 0), data.get("standard_minutes_per_unit", 0),
             data.get("setup_minutes", 0), data.get("difficulty_factor", 1), data.get("planned_minutes", 0), data["plan_start"], data["plan_end"],
             data.get("status", "planned"), data.get("blocked_reason", ""), data.get("schedule_run_key", ""),
             data.get("route_version_id"), data.get("process_version_id"), data.get("standard_id"), data.get("standard_version"),
             data.get("process_name_snapshot", ""), data.get("route_name_snapshot", ""), data.get("schedule_run_id")),
        )
        return cur.lastrowid

    @staticmethod
    def list_scheduled_operations(limit=500, db=None):
        db = resolve_db(db)
        limit = min(max(int(limit or 500), 1), 1000)
        return db.execute(
            "SELECT s.*, o.order_no, o.product_name, p.name AS process_name, pl.line_name "
            "FROM order_process_schedules s JOIN orders o ON o.id=s.order_id "
            "JOIN processes p ON p.id=s.process_id LEFT JOIN process_production_lines pl ON pl.id=s.process_line_id "
            "WHERE o.deleted_at IS NULL ORDER BY s.plan_start, s.seq_order, o.order_no LIMIT ?", (limit,)
        ).fetchall()
