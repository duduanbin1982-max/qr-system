"""Persistence for planning facts: orders, operations, capacity and calendars."""

import hashlib
import json
import sqlite3

from modules.repositories.context import resolve_db
from modules.schedule_capacity_config import (
    DEFAULT_DAILY_MINUTES,
    DEFAULT_PROCESS_LINE_COUNTS,
)
from modules.domain.schedule_order_priority import ScheduleOrderPriorityPolicy


class SchedulePlanningRepository:
    """Order, process, standard, node, calendar, capacity and occupancy facts."""

    @staticmethod
    def formal_schedule_digest(order_id, db=None):
        """Hash formal scheduling facts and node inputs, excluding shadow facts.

        The digest is used both as an idempotency input and as the isolation
        assertion around a shadow calculation.  Include the complete target
        order projection plus shared node capacity/occupancy inputs because a
        change to either can legitimately change a shadow result.
        """
        db = resolve_db(db)

        def rows(sql, params=()):
            return [dict(row) for row in db.execute(sql, params).fetchall()]

        snapshot = {
            "order": rows("SELECT * FROM orders WHERE id=?", (order_id,)),
            "order_processes": rows(
                "SELECT * FROM order_processes WHERE order_id=? ORDER BY id",
                (order_id,),
            ),
            "schedules": rows(
                "SELECT * FROM order_process_schedules WHERE order_id=? ORDER BY id",
                (order_id,),
            ),
            "segments": rows(
                "SELECT ss.* FROM order_process_schedule_segments ss "
                "JOIN order_process_schedules s ON s.id=ss.schedule_id "
                "WHERE s.order_id=? ORDER BY ss.id",
                (order_id,),
            ),
            "allocations": rows(
                "SELECT a.* FROM production_node_schedule_allocations a "
                "JOIN order_process_schedules s ON s.id=a.schedule_id "
                "WHERE s.order_id=? ORDER BY a.id",
                (order_id,),
            ),
            "runs": rows(
                "SELECT * FROM schedule_runs WHERE order_id=? ORDER BY id",
                (order_id,),
            ),
            "revisions": rows(
                "SELECT * FROM schedule_revisions WHERE order_id=? ORDER BY id",
                (order_id,),
            ),
            "revision_items": rows(
                "SELECT i.* FROM schedule_revision_items i "
                "JOIN schedule_revisions r ON r.id=i.revision_id "
                "WHERE r.order_id=? ORDER BY i.id",
                (order_id,),
            ),
            "nodes": rows("SELECT * FROM production_nodes ORDER BY id"),
            "capabilities": rows(
                "SELECT * FROM production_node_capabilities ORDER BY id"
            ),
            "calendar_overrides": rows(
                "SELECT * FROM production_node_calendar_overrides ORDER BY id"
            ),
            "calendars": rows("SELECT * FROM schedule_calendars ORDER BY id"),
            "shifts": rows("SELECT * FROM schedule_shifts ORDER BY id"),
            "standards": rows("SELECT * FROM work_time_standards ORDER BY id"),
            "other_node_occupancy": rows(
                "SELECT ss.production_node_id,ss.segment_start_at,ss.segment_end_at,"
                "ss.schedule_id FROM order_process_schedule_segments ss "
                "JOIN order_process_schedules s ON s.id=ss.schedule_id "
                "JOIN orders o ON o.id=s.order_id "
                "WHERE s.order_id<>? AND o.deleted_at IS NULL "
                "AND s.status<>'blocked' AND ss.production_node_id IS NOT NULL "
                "ORDER BY ss.production_node_id,ss.segment_start_at,ss.id",
                (order_id,),
            ),
        }
        encoded = json.dumps(
            snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    @staticmethod
    def list_order_serial_ids(order_id, db=None):
        """Return active serial-item identifiers for a schedulable order."""
        db = resolve_db(db)
        try:
            rows = db.execute(
                "SELECT serial_no FROM product_items "
                "WHERE order_id=? AND COALESCE(serial_no,'')<>'' "
                "AND COALESCE(status,'') NOT IN ('cancelled','void','deleted') "
                "ORDER BY position_no,id",
                (order_id,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [str(row["serial_no"]) for row in rows]
    @staticmethod
    def ensure_order_version_bindings(order_id, db):
        """Materialize exact route/process revisions for a schedulable order.

        This is deliberately idempotent: legacy rows are upgraded only when a
        single route/process topology can prove the binding.
        """
        order = db.execute(
            "SELECT id,route_id,route_version_id,route_name_snapshot,"
            "current_schedule_revision_id FROM orders "
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
            "SELECT id,quantity,completed,status,plan_start,plan_end,deadline,product_id,product_code,product_name,"
            "route_id,route_version_id,route_name_snapshot,current_schedule_revision_id "
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
        default_calendar = SchedulePlanningRepository.get_calendar(db=db)
        calendar_id = default_calendar["id"] if default_calendar else None
        inserted = 0
        for index in range(1, count + 1):
            code = f"{process_name}-{index:02d}"
            if code in used_codes:
                continue
            cursor = db.execute(
                "INSERT OR IGNORE INTO process_production_lines "
                "(process_id,line_code,line_name,daily_minutes,remark,calendar_id) VALUES (?,?,?,?,?,?)",
                (process_id, code, f"{process_name}{index}线", DEFAULT_DAILY_MINUTES,
                 "系统默认产线", calendar_id),
            )
            inserted += cursor.rowcount
        db.execute(
            "INSERT OR IGNORE INTO process_capacity_profiles "
            "(process_id,configured_line_count,source_process_name) VALUES (?,?,?)",
            (process_id, count, process_name),
        )
        return inserted
    @staticmethod
    def list_schedulable_orders(limit=500, db=None, now=None):
        db = resolve_db(db)
        bounded_limit = min(max(int(limit or 500), 1), 1000)
        rows = db.execute(
            "SELECT id, order_no, quantity, product_id, product_code, product_name, plan_start, plan_end, "
            "deadline, status, priority_level, is_expedited, previous_priority_level, "
            "previous_is_expedited, priority_effective_at, priority_version, schedule_policy, "
            "schedule_replan_required, schedule_replan_reason "
            "FROM orders WHERE deleted_at IS NULL AND status IN ('pending','producing')"
        ).fetchall()
        queue = []
        for raw in rows:
            row = dict(raw)
            if not ScheduleOrderPriorityPolicy.is_schedulable(row, now=now):
                continue
            intent = ScheduleOrderPriorityPolicy.effective_intent(row, now=now)
            row.update({
                "effective_priority_level": intent["priority_level"],
                "effective_is_expedited": int(intent["is_expedited"]),
                "pending_effective_change": intent["pending_effective_change"],
            })
            queue.append(row)
        return ScheduleOrderPriorityPolicy.order_queue(queue, now=now)[:bounded_limit]
    @staticmethod
    def find_order(order_id, db):
        return db.execute(
            "SELECT id, quantity, plan_start, product_id, product_code, product_name, route_id, "
            "route_version_id, route_name_snapshot FROM orders "
            "WHERE id=? AND deleted_at IS NULL",
            (order_id,),
        ).fetchone()
    @staticmethod
    def find_schedule(schedule_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM order_process_schedules WHERE id=?",
            (schedule_id,),
        ).fetchone()
    @staticmethod
    def find_standard(standard_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM work_time_standards WHERE id=?",
            (standard_id,),
        ).fetchone()
    @staticmethod
    def find_active_standard(
        route_id, route_version_id, process_id, process_version_id,
        product_id, product_code, as_of_date, db
    ):
        """Resolve a standard without ever borrowing another product's value.

        The precedence is exact route/process revision, route-level, then
        process-generic. Within each level, an exact product row wins over a
        genuinely generic row. Product-specific rows for any other product are
        deliberately ignored instead of being treated as a fallback.
        """
        effective_date = (as_of_date or "").strip() or None
        base = (
            "SELECT id,version,setup_minutes,standard_minutes_per_unit,difficulty_factor,"
            "route_id,route_version_id,process_id,process_version_id,product_id,product_code,"
            "{scope} AS match_scope FROM work_time_standards WHERE process_id=? AND status='active' "
            "AND standard_minutes_per_unit>0 "
            "AND (effective_from='' OR effective_from IS NULL OR (? IS NULL OR effective_from<=?)) "
            "AND (effective_to='' OR effective_to IS NULL OR (? IS NULL OR effective_to>=?)) "
        )
        params = (process_id, effective_date, effective_date, effective_date, effective_date)

        if product_id is not None:
            product_condition = "product_id=?"
            product_params = (product_id,)
        elif product_code:
            product_condition = "product_id IS NULL AND product_code=?"
            product_params = (product_code,)
        else:
            product_condition = "0=1"
            product_params = ()
        generic_condition = "COALESCE(product_id,0)=0 AND COALESCE(product_code,'')=''"

        scopes = []
        if route_version_id and process_version_id:
            scopes.append((
                "route_version",
                "AND route_version_id=? AND process_version_id=?",
                (route_version_id, process_version_id),
            ))
        if route_id:
            scopes.append((
                "route",
                "AND route_id=? AND (route_version_id IS NULL OR route_version_id=?)",
                (route_id, route_version_id),
            ))
        scopes.append((
            "process",
            "AND route_id IS NULL AND route_version_id IS NULL "
            "AND (process_version_id IS NULL OR process_version_id=?)",
            (process_version_id,),
        ))

        # Product-specific standards always win over generic standards, even
        # when the generic row is scoped to a more specific route revision.
        # This makes the business rule deterministic: exact product first,
        # then generic; scope specificity only breaks ties within a class.
        for match_kind, condition, condition_params in (
            ("product", product_condition, product_params),
            ("generic", generic_condition, ()),
        ):
            for level, relation, relation_params in scopes:
                candidate = db.execute(
                    base.format(scope=f"'{level}:{match_kind}'") + relation + " AND " + condition +
                    " ORDER BY version DESC,id DESC LIMIT 1",
                    params + relation_params + condition_params,
                ).fetchone()
                if candidate:
                    return candidate
        return None
    @staticmethod
    def find_execution_policy(route_version_id, process_version_id, db):
        if not route_version_id or not process_version_id:
            return None
        try:
            return db.execute(
                "SELECT * FROM route_process_execution_policies "
                "WHERE route_version_id=? AND process_version_id=? AND status='active'",
                (route_version_id, process_version_id),
            ).fetchone()
        except sqlite3.OperationalError:
            # Read-only pre-v085 clones remain compatible with the scheduler.
            return None
    @staticmethod
    def affected_order_ids_for_downtime(
        production_node_id, start_at, end_at, db=None,
    ):
        db = resolve_db(db)
        rows = db.execute(
            "SELECT DISTINCT interval.order_id FROM schedule_effective_capacity_intervals interval "
            "JOIN orders o ON o.id=interval.order_id "
            "WHERE interval.production_node_id=? AND interval.start_at<? "
            "AND interval.end_at>? AND o.deleted_at IS NULL "
            "AND o.status IN ('pending','producing') ORDER BY interval.order_id",
            (int(production_node_id), str(end_at), str(start_at)),
        ).fetchall()
        return [int(row["order_id"]) for row in rows]
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
            "op.status, op.completed, op.scrapped, op.rework, op.process_version_id, "
            "op.process_code_snapshot, op.process_name_snapshot, op.process_category_snapshot, "
            "o.route_id, o.route_version_id, o.route_name_snapshot, p.name AS process_name, "
            "s.id AS schedule_id, s.process_line_id, s.production_node_id, "
            "s.node_code_snapshot, s.node_name_snapshot, s.capacity_mode_snapshot, "
            "s.quantity AS scheduled_quantity, "
            "s.route_version_id AS scheduled_route_version_id, s.process_version_id AS scheduled_process_version_id, "
            "s.standard_id, s.standard_version, s.process_name_snapshot AS scheduled_process_name_snapshot, "
            "s.route_name_snapshot AS scheduled_route_name_snapshot, s.standard_minutes_per_unit, "
            "s.setup_minutes, s.difficulty_factor, s.planned_minutes, s.plan_start, s.plan_end, "
            "s.planned_start_at, s.planned_end_at, s.occupied_minutes, s.capacity_snapshot_json, "
            "s.standard_match_scope, s.calendar_id, s.shift_snapshot_json, s.line_name_snapshot, "
            "s.execution_mode, s.schedule_revision_id, "
            "COALESCE(op.completed,0) AS actual_completed_qty, "
            "COALESCE((SELECT MIN(COALESCE(NULLIF(wr.actual_completed_at,''),wr.created_at)) "
            "FROM work_records wr WHERE wr.order_id=op.order_id AND wr.process_id=op.process_id "
            "AND wr.status='approved'),'') AS actual_start_at, "
            "COALESCE((SELECT MAX(COALESCE(NULLIF(wr.actual_completed_at,''),wr.created_at)) "
            "FROM work_records wr WHERE wr.order_id=op.order_id AND wr.process_id=op.process_id "
            "AND wr.status='approved'),'') AS actual_last_report_at, "
            "CASE WHEN COALESCE(op.completed,0)>=COALESCE(o.quantity,0) AND COALESCE(o.quantity,0)>0 "
            "THEN COALESCE((SELECT MAX(COALESCE(NULLIF(wr.actual_completed_at,''),wr.created_at)) "
            "FROM work_records wr WHERE wr.order_id=op.order_id AND wr.process_id=op.process_id "
            "AND wr.status='approved'),'') ELSE '' END AS actual_end_at, "
            "s.status AS schedule_status, s.blocked_reason, s.blocked_code, s.schedule_run_key, s.schedule_run_id, pl.line_name "
            "FROM order_processes op JOIN orders o ON o.id=op.order_id JOIN processes p ON p.id=op.process_id "
            "LEFT JOIN order_process_schedules s ON s.order_process_id=op.id "
            "LEFT JOIN process_production_lines pl ON pl.id=s.process_line_id "
            "WHERE op.order_id=? ORDER BY op.seq_order, op.id LIMIT ?", (order_id, limit)
        ).fetchall()
    @staticmethod
    def list_node_occupancy_for_adjustment(production_node_id, exclude_schedule_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT ss.id,ss.production_node_id,ss.segment_start_at AS start_at,"
            "ss.segment_end_at AS end_at,CASE WHEN s.locked=1 OR EXISTS ("
            "SELECT 1 FROM schedule_revision_items ri "
            "JOIN schedule_node_task_locks l ON l.revision_item_id=ri.id AND l.status='active' "
            "WHERE ri.revision_id=o.current_schedule_revision_id "
            "AND ri.source_schedule_id=s.id) THEN 1 ELSE 0 END AS locked,"
            "'schedule' AS fact_type FROM order_process_schedule_segments ss "
            "JOIN order_process_schedules s ON s.id=ss.schedule_id "
            "JOIN orders o ON o.id=s.order_id "
            "WHERE ss.production_node_id=? AND ss.schedule_id<>? AND s.status<>'blocked' "
            "AND o.deleted_at IS NULL UNION ALL "
            "SELECT s.id,s.production_node_id,s.planned_start_at,s.planned_end_at,"
            "CASE WHEN s.locked=1 OR EXISTS ("
            "SELECT 1 FROM schedule_revision_items ri "
            "JOIN schedule_node_task_locks l ON l.revision_item_id=ri.id AND l.status='active' "
            "WHERE ri.revision_id=o.current_schedule_revision_id "
            "AND ri.source_schedule_id=s.id) THEN 1 ELSE 0 END AS locked,"
            "'schedule' AS fact_type "
            "FROM order_process_schedules s JOIN orders o ON o.id=s.order_id "
            "WHERE s.production_node_id=? AND s.id<>? AND s.status<>'blocked' "
            "AND o.deleted_at IS NULL AND NOT EXISTS ("
            "SELECT 1 FROM order_process_schedule_segments ss WHERE ss.schedule_id=s.id) UNION ALL "
            "SELECT d.id,d.production_node_id,d.start_at,d.end_at,0 AS locked,"
            "'downtime' AS fact_type FROM schedule_downtime_events d "
            "WHERE d.production_node_id=? AND d.status='active' "
            "ORDER BY start_at,end_at,id",
            (production_node_id, exclude_schedule_id or 0,
             production_node_id, exclude_schedule_id or 0,
             production_node_id),
        ).fetchall()
    @staticmethod
    def list_downtime_events(process_line_id=None, production_node_id=None,
                             start_at="", end_at="", db=None, limit=1000):
        db = resolve_db(db)
        limit = min(max(int(limit or 1000), 1), 5000)
        where = ["d.status='active'"]
        params = []
        if process_line_id not in (None, ""):
            where.append("d.process_line_id=?")
            params.append(int(process_line_id))
        if production_node_id not in (None, ""):
            where.append("d.production_node_id=?")
            params.append(int(production_node_id))
        if start_at:
            where.append("d.end_at>?" )
            params.append(start_at)
        if end_at:
            where.append("d.start_at<?")
            params.append(end_at)
        return db.execute(
            "SELECT d.*,pl.line_code,pl.line_name,n.node_code,n.node_name,"
            "COALESCE(np.name,p.name) AS process_name "
            "FROM schedule_downtime_events d "
            "JOIN process_production_lines pl ON pl.id=d.process_line_id "
            "JOIN processes p ON p.id=pl.process_id "
            "LEFT JOIN production_nodes n ON n.id=d.production_node_id "
            "LEFT JOIN processes np ON np.id=n.process_id "
            "WHERE " + " AND ".join(where) + " ORDER BY d.start_at,d.id LIMIT ?",
            params + [limit],
        ).fetchall()
    @staticmethod
    def create_downtime_event(process_line_id, start_at, end_at, reason, created_by=None,
                              production_node_id=None, db=None):
        db = resolve_db(db)
        line = db.execute(
            "SELECT id,status FROM process_production_lines WHERE id=?", (process_line_id,)
        ).fetchone()
        if not line:
            raise ValueError("产线不存在")
        if line["status"] != "active":
            raise ValueError("产线已停用")
        cur = db.execute(
            "INSERT INTO schedule_downtime_events "
            "(process_line_id,production_node_id,start_at,end_at,reason,status,source_type,created_by) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (process_line_id, production_node_id, start_at, end_at, reason or "",
             "active", "manual", created_by),
        )
        return cur.lastrowid
    @staticmethod
    def find_downtime_event(event_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT d.*,pl.line_code,pl.line_name,n.node_code,n.node_name,"
            "COALESCE(np.name,p.name) AS process_name "
            "FROM schedule_downtime_events d "
            "JOIN process_production_lines pl ON pl.id=d.process_line_id "
            "JOIN processes p ON p.id=pl.process_id "
            "LEFT JOIN production_nodes n ON n.id=d.production_node_id "
            "LEFT JOIN processes np ON np.id=n.process_id WHERE d.id=?",
            (event_id,),
        ).fetchone()
    @staticmethod
    def cancel_downtime_event(event_id, db=None):
        db = resolve_db(db)
        cur = db.execute(
            "UPDATE schedule_downtime_events SET status='cancelled',"
            "updated_at=datetime('now','localtime') WHERE id=? AND status='active'",
            (event_id,),
        )
        return cur.rowcount
    @staticmethod
    def dynamic_replan_order_context(order_id, db=None, *, use_nodes=False):
        """Load immutable-bound operations and current execution facts."""
        db = resolve_db(db)
        order = db.execute(
            "SELECT id,order_no,quantity,completed,status,plan_start,plan_end,deadline,product_id,product_code,"
            "product_name,route_id,route_version_id,route_name_snapshot,"
            "current_schedule_revision_id,schedule_replan_required,schedule_replan_reason "
            "FROM orders WHERE id=? AND deleted_at IS NULL", (order_id,)
        ).fetchone()
        if not order:
            return None
        operations = db.execute(
            "SELECT op.id AS order_process_id,op.order_id,op.process_id,op.seq_order,op.status,"
            "COALESCE(op.completed,0) AS completed_quantity,COALESCE(op.scrapped,0) AS scrapped_quantity,"
            "COALESCE(op.rework,0) AS rework_total,op.process_version_id,op.process_code_snapshot,"
            "op.process_name_snapshot,op.process_category_snapshot,p.name AS process_name,"
            "o.quantity AS order_quantity,o.route_id,o.route_version_id,o.route_name_snapshot "
            "FROM order_processes op JOIN orders o ON o.id=op.order_id "
            "JOIN processes p ON p.id=op.process_id WHERE op.order_id=? "
            "ORDER BY op.seq_order,op.id", (order_id,)
        ).fetchall()
        work_reports = [dict(row) for row in db.execute(
            "SELECT wr.id,op.id AS order_process_id,wr.process_id,wr.type,wr.status,"
            "wr.quantity,wr.serial_no,wr.actual_completed_at,wr.created_at "
            "FROM work_records wr JOIN order_processes op "
            "ON op.order_id=wr.order_id AND op.process_id=wr.process_id "
            "WHERE wr.order_id=? ORDER BY wr.id",
            (order_id,),
        ).fetchall()]
        scrap_records = [dict(row) for row in db.execute(
            "SELECT sr.id,op.id AS order_process_id,sr.process_id,sr.quantity,"
            "'recorded' AS status,sr.created_at FROM scrap_records sr "
            "JOIN order_processes op ON op.order_id=sr.order_id AND op.process_id=sr.process_id "
            "WHERE sr.order_id=? ORDER BY sr.id",
            (order_id,),
        ).fetchall()]
        rework_records = [dict(row) for row in db.execute(
            "SELECT rw.id,op.id AS order_process_id,rw.process_id,rw.quantity,rw.status,"
            "rw.source_ncr_id,rw.result,rw.completed_at,rw.created_at "
            "FROM rework_records rw JOIN order_processes op "
            "ON op.order_id=rw.order_id AND op.process_id=rw.process_id "
            "WHERE rw.order_id=? ORDER BY rw.id",
            (order_id,),
        ).fetchall()]
        approved_by_operation = {}
        for report in work_reports:
            if report["type"] == "normal" and report["status"] == "approved":
                approved_by_operation[report["order_process_id"]] = (
                    approved_by_operation.get(report["order_process_id"], 0)
                    + int(report["quantity"] or 0)
                )
        pending_rework_by_operation = {}
        for record in rework_records:
            if record["status"] == "pending":
                pending_rework_by_operation[record["order_process_id"]] = (
                    pending_rework_by_operation.get(record["order_process_id"], 0)
                    + int(record["quantity"] or 0)
                )
        enriched = []
        for operation in operations:
            operation_id = int(operation["order_process_id"])
            approved = int(approved_by_operation.get(operation_id, 0))
            pending = int(pending_rework_by_operation.get(operation_id, 0))
            enriched.append({
                **dict(operation),
                "approved_report_quantity": approved,
                "completed_quantity": max(
                    int(operation["completed_quantity"] or 0), approved
                ),
                "rework_quantity": pending,
            })
        if use_nodes:
            occupancy = [dict(row) for row in db.execute(
                "SELECT ss.production_node_id,ss.process_line_id,"
                "ss.segment_start_at AS start_at,ss.segment_end_at AS end_at,"
                "ss.schedule_id FROM order_process_schedule_segments ss "
                "JOIN order_process_schedules s ON s.id=ss.schedule_id "
                "JOIN orders o ON o.id=s.order_id "
                "WHERE s.order_id<>? AND o.deleted_at IS NULL "
                "AND s.status<>'blocked' AND ss.production_node_id IS NOT NULL "
                "UNION ALL "
                "SELECT s.production_node_id,s.process_line_id,s.planned_start_at,"
                "s.planned_end_at,s.id FROM order_process_schedules s "
                "JOIN orders o ON o.id=s.order_id "
                "WHERE s.order_id<>? AND o.deleted_at IS NULL "
                "AND s.status<>'blocked' AND s.production_node_id IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM order_process_schedule_segments ss WHERE ss.schedule_id=s.id) "
                "ORDER BY start_at,end_at,schedule_id",
                (order_id, order_id),
            ).fetchall()]
        else:
            occupancy = [
                dict(row)
                for row in SchedulePlanningRepository.list_line_occupancy(order_id, db)
            ]
        downtime = [
            dict(row)
            for row in SchedulePlanningRepository.list_downtime_events(db=db)
        ]
        prior = db.execute(
            "SELECT * FROM order_process_schedules WHERE order_id=? ORDER BY seq_order,id", (order_id,)
        ).fetchall()
        current_revision = None
        current_revision_items = []
        current_revision_id = order["current_schedule_revision_id"]
        if current_revision_id:
            current_revision = db.execute(
                "SELECT * FROM schedule_revisions WHERE id=? AND order_id=?",
                (current_revision_id, order_id),
            ).fetchone()
            current_revision_items = db.execute(
                "SELECT * FROM schedule_revision_items WHERE revision_id=? "
                "ORDER BY seq_order,id",
                (current_revision_id,),
            ).fetchall()
        # Keep this as a read-only trigger snapshot so the planning context is
        # complete without making the planning repository depend on the
        # evidence repository; trigger writes remain evidence-owned.
        replan_triggers = db.execute(
            "SELECT * FROM schedule_replan_triggers WHERE order_id=? "
            "ORDER BY created_at DESC,id DESC LIMIT 200",
            (int(order_id),),
        ).fetchall()
        return {"order": dict(order), "operations": enriched, "occupancy": occupancy,
                "downtime": downtime, "prior_schedules": [dict(row) for row in prior],
                "work_reports": work_reports, "scrap_records": scrap_records,
                "rework_records": rework_records,
                "current_revision": dict(current_revision) if current_revision else None,
                "current_revision_items": [dict(row) for row in current_revision_items],
                "replan_triggers": [dict(row) for row in replan_triggers]}
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
    def list_line_occupancy(exclude_order_id, db):
        """Return timestamp segments occupying lines for other live orders.

        Legacy date-only facts are returned as a fallback; the precision
        scheduler expands them to the configured working slots before use.
        """
        return db.execute(
            """
            SELECT ss.process_line_id, ss.segment_start_at AS start_at,
                   ss.segment_end_at AS end_at, ss.schedule_id
            FROM order_process_schedule_segments ss
            JOIN order_process_schedules s ON s.id=ss.schedule_id
            JOIN orders o ON o.id=s.order_id
            WHERE s.order_id != ? AND o.deleted_at IS NULL
              AND s.status != 'blocked' AND s.process_line_id IS NOT NULL
            UNION ALL
            SELECT s.process_line_id,
                   CASE WHEN COALESCE(s.planned_start_at,'')<>''
                        THEN s.planned_start_at ELSE s.plan_start || ' 00:00' END,
                   CASE WHEN COALESCE(s.planned_end_at,'')<>''
                        THEN s.planned_end_at ELSE s.plan_end || ' 23:59' END,
                   s.id
            FROM order_process_schedules s
            JOIN orders o ON o.id=s.order_id
            WHERE s.order_id != ? AND o.deleted_at IS NULL
              AND s.status != 'blocked' AND s.process_line_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM order_process_schedule_segments ss
                  WHERE ss.schedule_id=s.id
              )
            """,
            (exclude_order_id, exclude_order_id),
        ).fetchall()
    @staticmethod
    def get_calendar(calendar_id=None, db=None):
        db = resolve_db(db)
        try:
            if calendar_id is None:
                return db.execute(
                    "SELECT * FROM schedule_calendars WHERE calendar_code='DEFAULT' AND status='active'"
                ).fetchone()
            return db.execute(
                "SELECT * FROM schedule_calendars WHERE id=? AND status='active'",
                (calendar_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
    @staticmethod
    def list_calendar_shifts(calendar_id, db=None):
        db = resolve_db(db)
        try:
            return db.execute(
                "SELECT * FROM schedule_shifts WHERE calendar_id=? AND status='active' "
                "ORDER BY start_minute,id",
                (calendar_id,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    @staticmethod
    def get_calendar_exception(calendar_id, work_date, db=None):
        db = resolve_db(db)
        try:
            return db.execute(
                "SELECT * FROM schedule_calendar_exceptions WHERE calendar_id=? AND work_date=?",
                (calendar_id, work_date),
            ).fetchone()
        except sqlite3.OperationalError:
            return None
    @staticmethod
    def list_calendars(db=None):
        db = resolve_db(db)
        try:
            calendars = db.execute(
                "SELECT * FROM schedule_calendars WHERE status='active' ORDER BY calendar_code"
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        result = []
        for calendar in calendars:
            result.append({
                **dict(calendar),
                "shifts": [
                    dict(row)
                    for row in SchedulePlanningRepository.list_calendar_shifts(
                        calendar["id"], db=db
                    )
                ],
            })
        return result
    @staticmethod
    def list_effective_capacity_intervals(exclude_order_id=None, db=None):
        """Return the published node-native capacity projection.

        V093's view enforces segment-first fallback, filters blocked/external
        work and ignores unpublished candidate projections.  Production-node
        identity is retained when present; legacy lines are only a fallback.
        """
        db = resolve_db(db)
        where = ""
        params = []
        if exclude_order_id not in (None, ""):
            where = " WHERE fact.order_id<>?"
            params.append(int(exclude_order_id))
        try:
            return db.execute(
                "SELECT fact.* FROM schedule_effective_capacity_intervals fact"
                + where
                + " ORDER BY fact.start_at,fact.end_at,fact.fact_key",
                params,
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    @staticmethod
    def list_capacity_unavailability(db=None):
        """Return active downtime and non-overtime node calendar overrides."""
        db = resolve_db(db)
        try:
            return db.execute(
                "SELECT d.id,d.production_node_id,d.process_line_id,d.start_at,d.end_at,"
                "'downtime' AS unavailable_type,d.reason "
                "FROM schedule_downtime_events d WHERE d.status='active' "
                "UNION ALL "
                "SELECT o.id,o.production_node_id,NULL,o.start_at,o.end_at,"
                "o.override_type,o.reason FROM production_node_calendar_overrides o "
                "WHERE o.status='active' AND o.override_type<>'overtime' "
                "ORDER BY start_at,end_at,id"
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    @staticmethod
    def list_line_loads(db=None):
        """Summarize persisted load facts for every configured process line."""
        db = resolve_db(db)
        try:
            return db.execute(
                """
                SELECT pl.id AS process_line_id, pl.line_code, pl.line_name,
                       pl.process_id, p.name AS process_name,
                       (
                         SELECT COUNT(*) FROM order_process_schedules s
                         JOIN orders o ON o.id=s.order_id
                         WHERE s.process_line_id=pl.id
                           AND s.status != 'blocked' AND o.deleted_at IS NULL
                       ) AS scheduled_operations,
                       (
                         SELECT COALESCE(SUM(ss.occupied_minutes),0)
                         FROM order_process_schedule_segments ss
                         JOIN order_process_schedules s ON s.id=ss.schedule_id
                         JOIN orders o ON o.id=s.order_id
                         WHERE ss.process_line_id=pl.id
                           AND s.status != 'blocked' AND o.deleted_at IS NULL
                       ) + (
                         SELECT COALESCE(SUM(s.occupied_minutes),0)
                         FROM order_process_schedules s
                         JOIN orders o ON o.id=s.order_id
                         WHERE s.process_line_id=pl.id
                           AND s.status != 'blocked' AND o.deleted_at IS NULL
                           AND NOT EXISTS (
                             SELECT 1 FROM order_process_schedule_segments ss
                             WHERE ss.schedule_id=s.id
                           )
                       ) AS occupied_minutes,
                       (
                         SELECT MIN(CASE WHEN COALESCE(s.planned_start_at,'')<>''
                                         THEN s.planned_start_at ELSE s.plan_start || ' 00:00' END)
                         FROM order_process_schedules s
                         JOIN orders o ON o.id=s.order_id
                         WHERE s.process_line_id=pl.id
                           AND s.status != 'blocked' AND o.deleted_at IS NULL
                       ) AS first_start_at,
                       (
                         SELECT MAX(CASE WHEN COALESCE(s.planned_end_at,'')<>''
                                         THEN s.planned_end_at ELSE s.plan_end || ' 23:59' END)
                         FROM order_process_schedules s
                         JOIN orders o ON o.id=s.order_id
                         WHERE s.process_line_id=pl.id
                           AND s.status != 'blocked' AND o.deleted_at IS NULL
                       ) AS last_end_at
                FROM process_production_lines pl
                JOIN processes p ON p.id=pl.process_id
                ORDER BY p.seq_order, p.id, pl.line_code
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    @staticmethod
    def list_scheduled_operations(limit=500, db=None):
        db = resolve_db(db)
        limit = min(max(int(limit or 500), 1), 1000)
        try:
            return db.execute(
                "SELECT s.*,o.order_no,o.product_name,p.name AS process_name,"
                "pl.line_name,ri.id AS revision_item_id,"
                "ri.row_version AS revision_item_row_version,"
                "r.status AS revision_status,"
                "r.approval_status AS revision_approval_status,"
                "CASE WHEN l.id IS NULL THEN 0 ELSE 1 END AS locked,"
                "l.id AS task_lock_id,"
                "COALESCE(NULLIF(s.node_code_snapshot,''),n.node_code,'') AS node_code,"
                "COALESCE(NULLIF(s.node_name_snapshot,''),n.node_name,'') AS node_name "
                "FROM order_process_schedules s "
                "JOIN orders o ON o.id=s.order_id "
                "JOIN processes p ON p.id=s.process_id "
                "LEFT JOIN process_production_lines pl ON pl.id=s.process_line_id "
                "LEFT JOIN schedule_revision_items ri "
                "ON ri.revision_id=s.schedule_revision_id "
                "AND ri.order_process_id=s.order_process_id "
                "LEFT JOIN schedule_revisions r ON r.id=ri.revision_id "
                "LEFT JOIN schedule_node_task_locks l "
                "ON l.revision_item_id=ri.id AND l.status='active' "
                "LEFT JOIN production_nodes n ON n.id=s.production_node_id "
                "WHERE o.deleted_at IS NULL "
                "ORDER BY s.plan_start,s.seq_order,o.order_no LIMIT ?",
                (limit,),
            ).fetchall()
        except sqlite3.OperationalError:
            # V089 is additive. Read-only replicas that have not reached the
            # workflow migration must retain the legacy query contract.
            return db.execute(
                "SELECT s.*,o.order_no,o.product_name,p.name AS process_name,"
                "pl.line_name,NULL AS revision_item_id,NULL AS revision_item_row_version,"
                "NULL AS revision_status,NULL AS revision_approval_status,0 AS locked,"
                "NULL AS task_lock_id,'' AS node_code,'' AS node_name "
                "FROM order_process_schedules s JOIN orders o ON o.id=s.order_id "
                "JOIN processes p ON p.id=s.process_id "
                "LEFT JOIN process_production_lines pl ON pl.id=s.process_line_id "
                "WHERE o.deleted_at IS NULL "
                "ORDER BY s.plan_start,s.seq_order,o.order_no LIMIT ?",
                (limit,),
            ).fetchall()
    @staticmethod
    def list_schedule_allocations(schedule_ids, db=None):
        """Return immutable split facts for the requested schedule rows."""
        db = resolve_db(db)
        normalized = sorted({
            int(schedule_id)
            for schedule_id in (schedule_ids or [])
            if str(schedule_id or "").isdigit() and int(schedule_id) > 0
        })
        if not normalized:
            return []
        placeholders = ",".join("?" for _ in normalized)
        try:
            return db.execute(
                "SELECT a.id,a.schedule_id,a.segment_id,a.production_node_id,"
                "a.quantity,a.serial_id,a.batch_key,a.changeover_minutes,"
                "a.allocation_start_at,a.allocation_end_at,"
                "n.node_code,n.node_name "
                "FROM production_node_schedule_allocations a "
                "LEFT JOIN production_nodes n ON n.id=a.production_node_id "
                f"WHERE a.schedule_id IN ({placeholders}) "
                "ORDER BY a.schedule_id,a.allocation_start_at,a.id",
                normalized,
            ).fetchall()
        except sqlite3.OperationalError:
            # V088 is additive; old read-only database copies have no split
            # allocation table and should expose an empty detail list.
            return []
    @staticmethod
    def list_schedule_segments(schedule_ids, db=None):
        """Return minute-level execution intervals for formal schedule rows."""
        db = resolve_db(db)
        normalized = sorted({
            int(schedule_id)
            for schedule_id in (schedule_ids or [])
            if str(schedule_id or "").isdigit() and int(schedule_id) > 0
        })
        if not normalized:
            return []
        placeholders = ",".join("?" for _ in normalized)
        try:
            return db.execute(
                "SELECT ss.id,ss.schedule_id,ss.process_line_id,"
                "ss.production_node_id,ss.segment_start_at,ss.segment_end_at,"
                "ss.occupied_minutes,ss.shift_id,ss.quantity,"
                "n.node_code,n.node_name "
                "FROM order_process_schedule_segments ss "
                "LEFT JOIN production_nodes n ON n.id=ss.production_node_id "
                f"WHERE ss.schedule_id IN ({placeholders}) "
                "ORDER BY ss.schedule_id,ss.segment_start_at,ss.id",
                normalized,
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    @staticmethod
    def list_capacity_overrides(db=None):
        """Return active node calendar overrides, including additive overtime."""
        db = resolve_db(db)
        try:
            return db.execute(
                "SELECT o.id,o.production_node_id,o.start_at,o.end_at,"
                "o.override_type,o.reason,o.status,n.node_code,n.node_name "
                "FROM production_node_calendar_overrides o "
                "LEFT JOIN production_nodes n ON n.id=o.production_node_id "
                "WHERE o.status='active' ORDER BY o.start_at,o.end_at,o.id"
            ).fetchall()
        except sqlite3.OperationalError:
            return []
