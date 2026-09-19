"""Persistence for process-level production-line pools and operation schedules."""

import hashlib
import json
import sqlite3

from modules.repositories.context import resolve_db
from modules.schedule_capacity_config import (
    DEFAULT_DAILY_MINUTES,
    DEFAULT_PROCESS_LINE_COUNTS,
)
from modules.domain.schedule_order_priority import ScheduleOrderPriorityPolicy


class ScheduleCapacityRepository:
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
            "SELECT id,quantity,completed,status,plan_start,plan_end,deadline,product_id,product_code,product_name,"
            "route_id,route_version_id,route_name_snapshot "
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
        default_calendar = ScheduleCapacityRepository.get_calendar(db=db)
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
    def update_order_summary(order_id, start_date, end_date, db):
        db.execute(
            "UPDATE orders SET plan_start=?, plan_end=?, "
            "schedule_version=COALESCE(schedule_version,1)+1, "
            "updated_at=datetime('now','localtime') WHERE id=?",
            (start_date, end_date, order_id),
        )

    @staticmethod
    def clear_schedule_replan_flag(order_id, db):
        """Clear the pending replan marker only after a successful plan."""
        db.execute(
            "UPDATE orders SET schedule_replan_required=0,schedule_replan_reason='',"
            "updated_at=datetime('now','localtime') WHERE id=? AND deleted_at IS NULL",
            (order_id,),
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
            "s.execution_mode, "
            "s.status AS schedule_status, s.blocked_reason, s.blocked_code, s.schedule_run_key, s.schedule_run_id, pl.line_name "
            "FROM order_processes op JOIN orders o ON o.id=op.order_id JOIN processes p ON p.id=op.process_id "
            "LEFT JOIN order_process_schedules s ON s.order_process_id=op.id "
            "LEFT JOIN process_production_lines pl ON pl.id=s.process_line_id "
            "WHERE op.order_id=? ORDER BY op.seq_order, op.id LIMIT ?", (order_id, limit)
        ).fetchall()

    @staticmethod
    def clear_order_schedules(order_id, db):
        """Clear the mutable compatibility projection only.

        Immutable revision items are written before this projection is cleared,
        so regeneration never destroys the historical schedule result.
        """
        db.execute("DELETE FROM order_process_schedules WHERE order_id=?", (order_id,))

    @staticmethod
    def create_revision(order_id, schedule_run_id, source_run_key, db, created_by=None,
                        *, replan_reason="", replan_source_digest="", replanned_at=""):
        row = db.execute(
            "SELECT COALESCE(MAX(revision_no),0)+1 AS next_revision FROM schedule_revisions WHERE order_id=?",
            (order_id,),
        ).fetchone()
        revision_no = int(row["next_revision"] if row else 1)
        order = db.execute(
            "SELECT priority_level,is_expedited,previous_priority_level,"
            "previous_is_expedited,priority_effective_at,priority_version,schedule_policy "
            "FROM orders WHERE id=? AND deleted_at IS NULL",
            (order_id,),
        ).fetchone()
        if order is None:
            raise ValueError("订单不存在")
        intent = ScheduleOrderPriorityPolicy.effective_intent(dict(order))
        cur = db.execute(
            "INSERT INTO schedule_revisions "
            "(order_id,schedule_run_id,revision_no,status,source_run_key,created_by,replan_reason,replan_source_digest,replanned_at,"
            "priority_level_snapshot,is_expedited_snapshot,priority_version_snapshot,priority_effective_at_snapshot,schedule_policy_snapshot) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (order_id, schedule_run_id, revision_no, "draft", source_run_key or "", created_by,
             replan_reason or "", replan_source_digest or "", replanned_at or "",
             intent["priority_level"], int(intent["is_expedited"]),
             int(order["priority_version"] or 1), order["priority_effective_at"] or "",
             order["schedule_policy"] or "auto"),
        )
        return cur.lastrowid

    @staticmethod
    def publish_revision(revision_id, db, published_by=None):
        revision = db.execute(
            "SELECT id,order_id,status,approval_status FROM schedule_revisions WHERE id=?", (revision_id,)
        ).fetchone()
        if revision is None:
            raise ValueError("排程版本不存在")
        if revision["status"] not in ("draft", "published"):
            raise ValueError("排程版本当前状态不可发布")
        if revision["approval_status"] != "approved":
            raise ValueError("排程版本必须先经独立审批后才能发布")
        expected_operation_ids = {
            row["id"] for row in db.execute(
                "SELECT id FROM order_processes WHERE order_id=?",
                (revision["order_id"],),
            ).fetchall()
        }
        item_operation_ids = [
            row["order_process_id"] for row in db.execute(
                "SELECT order_process_id FROM schedule_revision_items WHERE revision_id=?",
                (revision_id,),
            ).fetchall()
        ]
        if len(item_operation_ids) != len(expected_operation_ids) or set(item_operation_ids) != expected_operation_ids:
            raise ValueError("排程版本条目不完整，不能发布")
        current = db.execute(
            "SELECT current_schedule_revision_id FROM orders WHERE id=?",
            (revision["order_id"],),
        ).fetchone()
        current_id = current["current_schedule_revision_id"] if current else None
        # Replaying an already-current published revision is a true no-op.  In
        # particular, do not rewrite published_at or published_by on retries.
        if revision["status"] == "published" and current_id == revision_id:
            return
        if current_id and current_id != revision_id:
            db.execute(
                "UPDATE schedule_revisions SET status='superseded',superseded_by=?,"
                "superseded_at=datetime('now','localtime') WHERE id=? AND status='published'",
                (revision_id, current_id),
            )
        db.execute(
            "UPDATE schedule_revisions SET status='published',published_by=?,"
            "published_at=datetime('now','localtime') WHERE id=?",
            (published_by, revision_id),
        )
        db.execute(
            "UPDATE orders SET current_schedule_revision_id=? WHERE id=?",
            (revision_id, revision["order_id"]),
        )

    @staticmethod
    def find_revision_item(revision_item_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT i.*,r.order_id,r.status AS revision_status,r.approval_status,"
            "r.created_by,r.revision_no FROM schedule_revision_items i "
            "JOIN schedule_revisions r ON r.id=i.revision_id WHERE i.id=?",
            (revision_item_id,),
        ).fetchone()

    @staticmethod
    def find_active_task_lock(revision_item_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM schedule_node_task_locks WHERE revision_item_id=? AND status='active'",
            (revision_item_id,),
        ).fetchone()

    @staticmethod
    def list_active_order_task_locks(order_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT l.*,i.order_process_id,i.revision_id,i.process_id,i.process_line_id,"
            "i.production_node_id AS item_production_node_id,i.seq_order,i.quantity,"
            "i.status AS item_status,i.planned_start_at,i.planned_end_at,"
            "i.occupied_minutes,i.payload_json,i.payload_digest,r.revision_no "
            "FROM schedule_node_task_locks l "
            "JOIN schedule_revision_items i ON i.id=l.revision_item_id "
            "JOIN schedule_revisions r ON r.id=i.revision_id "
            "WHERE r.order_id=? AND r.status IN ('draft','published') "
            "AND l.status='active' ORDER BY r.revision_no DESC,l.id DESC",
            (order_id,),
        ).fetchall()

    @staticmethod
    def find_revision_item_by_source_schedule(revision_id, source_schedule_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM schedule_revision_items "
            "WHERE revision_id=? AND source_schedule_id=? ORDER BY id DESC LIMIT 1",
            (revision_id, source_schedule_id),
        ).fetchone()

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
    def find_workflow_event(idempotency_key, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM schedule_node_workflow_events WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()

    @staticmethod
    def create_workflow_event(*, revision_id, revision_item_id=None, event_type, actor_id,
                              reason, before_json, after_json, input_digest, idempotency_key, db):
        cursor = db.execute(
            "INSERT INTO schedule_node_workflow_events "
            "(revision_id,revision_item_id,event_type,actor_id,reason,before_json,after_json,input_digest,idempotency_key) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (revision_id, revision_item_id, event_type, actor_id, reason or '',
             before_json, after_json, input_digest, idempotency_key),
        )
        return db.execute(
            "SELECT * FROM schedule_node_workflow_events WHERE id=?", (cursor.lastrowid,)
        ).fetchone()

    @staticmethod
    def create_task_lock(revision_item_id, production_node_id, actor_id, reason, db):
        cursor = db.execute(
            "INSERT INTO schedule_node_task_locks "
            "(revision_item_id,production_node_id,locked_by,reason) VALUES (?,?,?,?)",
            (revision_item_id, production_node_id, actor_id, reason),
        )
        return db.execute(
            "SELECT * FROM schedule_node_task_locks WHERE id=?", (cursor.lastrowid,)
        ).fetchone()

    @staticmethod
    def release_task_lock(revision_item_id, actor_id, reason, db):
        cursor = db.execute(
            "UPDATE schedule_node_task_locks SET status='released',released_by=?,"
            "released_at=datetime('now','localtime'),release_reason=? "
            "WHERE revision_item_id=? AND status='active'",
            (actor_id, reason, revision_item_id),
        )
        return cursor.rowcount

    @staticmethod
    def transition_revision(revision_id, expected_status, new_status, actor_id, reason, db):
        field_prefix = {
            "submitted": "submitted",
            "approved": "approved",
            "rejected": "rejected",
        }[new_status]
        cursor = db.execute(
            f"UPDATE schedule_revisions SET approval_status=?,{field_prefix}_by=?,"
            f"{field_prefix}_at=datetime('now','localtime'),{field_prefix}_reason=? "
            "WHERE id=? AND approval_status=? AND status='draft'",
            (new_status, actor_id, reason, revision_id, expected_status),
        )
        return cursor.rowcount

    @staticmethod
    def clone_revision_with_override(revision_id, override_item_id=None, overrides=None,
                                     created_by=None, reason='', db=None):
        db = resolve_db(db)
        source = db.execute(
            "SELECT * FROM schedule_revisions WHERE id=?", (revision_id,)
        ).fetchone()
        if source is None:
            raise ValueError("排程版本不存在")
        next_no = db.execute(
            "SELECT COALESCE(MAX(revision_no),0)+1 FROM schedule_revisions WHERE order_id=?",
            (source['order_id'],),
        ).fetchone()[0]
        rev_columns = [r[1] for r in db.execute("PRAGMA table_info(schedule_revisions)").fetchall()]
        excluded = {'id','created_at','published_at','superseded_at','submitted_at','approved_at','rejected_at'}
        values = {c: source[c] for c in rev_columns if c not in excluded}
        values.update({
            'revision_no': next_no, 'status': 'draft', 'approval_status': 'draft',
            'created_by': created_by, 'published_by': None, 'superseded_by': None,
            'source_run_key': f"manual:{revision_id}:{next_no}",
            'result_digest': '', 'submitted_by': None, 'submitted_reason': '',
            'approved_by': None, 'approved_reason': '', 'rejected_by': None,
            'rejected_reason': '',
            'replan_reason': (
                reason or source['replan_reason']
                if 'replan_reason' in rev_columns else reason or ''
            ),
        })
        for timestamp_column in ('submitted_at', 'approved_at', 'rejected_at'):
            if timestamp_column in rev_columns:
                values[timestamp_column] = ''
        for risk_column, empty_value in {
            'deadline_snapshot': '',
            'projected_completion_at_snapshot': '',
            'risk_level': 'unassessed',
            'delay_minutes': 0,
            'risk_reason': '',
            'risk_assessed_at': '',
        }.items():
            if risk_column in rev_columns:
                values[risk_column] = empty_value
        cols = list(values)
        cur = db.execute(
            f"INSERT INTO schedule_revisions ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
            [values[c] for c in cols],
        )
        new_revision_id = cur.lastrowid
        item_columns = [r[1] for r in db.execute("PRAGMA table_info(schedule_revision_items)").fetchall()]
        item_id_map = {}
        source_items = db.execute(
            "SELECT * FROM schedule_revision_items WHERE revision_id=? ORDER BY seq_order,id",
            (revision_id,),
        ).fetchall()
        for item in source_items:
            item_values = {c: item[c] for c in item_columns if c not in {'id','revision_id','created_at'}}
            if 'row_version' in item_values:
                item_values['row_version'] = 1
            if item['id'] == override_item_id:
                item_values.update(overrides or {})
            item_values['revision_id'] = new_revision_id
            cols = list(item_values)
            item_cursor = db.execute(
                f"INSERT INTO schedule_revision_items ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
                [item_values[c] for c in cols],
            )
            item_id_map[item['id']] = item_cursor.lastrowid
        for source_item_id, target_item_id in item_id_map.items():
            lock = db.execute(
                "SELECT production_node_id,locked_by,reason FROM schedule_node_task_locks "
                "WHERE revision_item_id=? AND status='active'",
                (source_item_id,),
            ).fetchone()
            if lock:
                db.execute(
                    "INSERT INTO schedule_node_task_locks "
                    "(revision_item_id,production_node_id,locked_by,reason) VALUES (?,?,?,?)",
                    (target_item_id, lock['production_node_id'], lock['locked_by'], lock['reason']),
                )
        return new_revision_id, item_id_map

    @staticmethod
    def list_revisions(order_id, db=None, limit=100):
        db = resolve_db(db)
        limit = min(max(int(limit or 100), 1), 1000)
        return db.execute(
            "SELECT * FROM schedule_revisions WHERE order_id=? ORDER BY revision_no DESC LIMIT ?",
            (order_id, limit),
        ).fetchall()

    @staticmethod
    def list_revision_items(revision_id, db=None, limit=1000):
        db = resolve_db(db)
        limit = min(max(int(limit or 1000), 1), 1000)
        return db.execute(
            "SELECT * FROM schedule_revision_items WHERE revision_id=? ORDER BY seq_order,id LIMIT ?",
            (revision_id, limit),
        ).fetchall()

    @staticmethod
    def find_revision(revision_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT r.*,o.order_no,o.product_id,o.product_code,o.product_name "
            "FROM schedule_revisions r JOIN orders o ON o.id=r.order_id WHERE r.id=?",
            (revision_id,),
        ).fetchone()

    @staticmethod
    def find_revision_by_run(schedule_run_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM schedule_revisions WHERE schedule_run_id=? ORDER BY id DESC LIMIT 1",
            (schedule_run_id,),
        ).fetchone()

    @staticmethod
    def find_run(schedule_run_key, db=None):
        db = resolve_db(db)
        return db.execute("SELECT * FROM schedule_runs WHERE schedule_run_key=?", (schedule_run_key,)).fetchone()

    @staticmethod
    def find_auto_plan_run(auto_plan_key, db=None):
        """Return the immutable automatic-plan attempt for an idempotency key."""
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM schedule_auto_plan_runs WHERE auto_plan_key=?",
            (str(auto_plan_key or "").strip(),),
        ).fetchone()

    @staticmethod
    def create_auto_plan_run(
        auto_plan_key, requested_start_date, input_digest, input_json,
        created_by=None, db=None,
    ):
        """Create an automatic-plan ledger row without overwriting history."""
        db = resolve_db(db)
        if isinstance(input_json, str):
            encoded_input = input_json
        else:
            encoded_input = json.dumps(
                input_json or {}, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            )
        cur = db.execute(
            "INSERT INTO schedule_auto_plan_runs "
            "(auto_plan_key,requested_start_date,status,input_digest,input_json,created_by) "
            "VALUES (?,?,?,?,?,?)",
            (
                str(auto_plan_key or "").strip(),
                str(requested_start_date or ""),
                "started",
                str(input_digest or ""),
                encoded_input,
                created_by,
            ),
        )
        return cur.lastrowid

    @staticmethod
    def complete_auto_plan_run(
        run_id, status, result, error_message="", db=None,
    ):
        """Freeze the result of an automatic-plan attempt with a digest."""
        db = resolve_db(db)
        if isinstance(result, str):
            encoded_result = result
        else:
            encoded_result = json.dumps(
                result if result is not None else {}, ensure_ascii=False,
                sort_keys=True, separators=(",", ":"),
            )
        digest = hashlib.sha256(encoded_result.encode("utf-8")).hexdigest()
        db.execute(
            "UPDATE schedule_auto_plan_runs SET status=?,result_json=?,"
            "result_digest=?,error_message=?,completed_at=datetime('now','localtime') "
            "WHERE id=?",
            (status, encoded_result, digest, error_message or "", run_id),
        )
        return digest

    @staticmethod
    def auto_plan_result(run):
        """Decode a stored automatic-plan result without trusting its shape."""
        if run is None:
            return {}
        try:
            result = json.loads(run["result_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            return {}
        return result if isinstance(result, dict) else {}

    @staticmethod
    def create_run(order_id, schedule_run_key, start_date, db, *, run_type="generate",
                   trigger_source="", input_digest="", replan_reason=""):
        cur = db.execute(
            "INSERT INTO schedule_runs "
            "(schedule_run_key,order_id,status,requested_start_date,run_type,trigger_source,input_digest,replan_reason) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (schedule_run_key, order_id, "started", start_date or "", run_type or "generate",
             trigger_source or "", input_digest or "", replan_reason or ""),
        )
        return cur.lastrowid

    @staticmethod
    def update_run_input(run_id, *, input_digest="", trigger_source="", replan_reason="", db=None):
        db = resolve_db(db)
        db.execute(
            "UPDATE schedule_runs SET input_digest=?,trigger_source=?,replan_reason=? WHERE id=?",
            (input_digest or "", trigger_source or "", replan_reason or "", run_id),
        )

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
            "product_name,route_id,route_version_id,route_name_snapshot "
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
        enriched = []
        for operation in operations:
            pending = db.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM rework_records "
                "WHERE order_id=? AND process_id=? AND status='pending'",
                (order_id, operation["process_id"]),
            ).fetchone()[0]
            approved = db.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM work_records "
                "WHERE order_id=? AND process_id=? AND type='normal' AND status='approved'",
                (order_id, operation["process_id"]),
            ).fetchone()[0]
            enriched.append({**dict(operation),
                             "completed_quantity": max(int(operation["completed_quantity"] or 0), int(approved or 0)),
                             "rework_quantity": int(pending or 0)})
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
            occupancy = [dict(row) for row in ScheduleCapacityRepository.list_line_occupancy(order_id, db)]
        downtime = [dict(row) for row in ScheduleCapacityRepository.list_downtime_events(db=db)]
        prior = db.execute(
            "SELECT * FROM order_process_schedules WHERE order_id=? ORDER BY seq_order,id", (order_id,)
        ).fetchall()
        return {"order": dict(order), "operations": enriched, "occupancy": occupancy,
                "downtime": downtime, "prior_schedules": [dict(row) for row in prior]}

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
    def set_revision_digest(revision_id, digest, db):
        db.execute(
            "UPDATE schedule_revisions SET result_digest=? WHERE id=?",
            (digest, revision_id),
        )

    @staticmethod
    def set_revision_risk_snapshot(revision_id, risk, assessed_at, db):
        cursor = db.execute(
            "UPDATE schedule_revisions SET deadline_snapshot=?,"
            "projected_completion_at_snapshot=?,risk_level=?,delay_minutes=?,"
            "risk_reason=?,risk_assessed_at=? WHERE id=? AND risk_assessed_at=''",
            (
                risk.get("deadline", ""),
                risk.get("projected_completion_at", ""),
                risk.get("level", "unassessed"),
                max(int(risk.get("delay_minutes") or 0), 0),
                risk.get("reason", ""),
                assessed_at,
                revision_id,
            ),
        )
        if cursor.rowcount != 1:
            raise ValueError("排程版本风险快照已冻结")

    @staticmethod
    def cancel_revision(revision_id, db):
        db.execute(
            "UPDATE schedule_revisions SET status='cancelled' WHERE id=?",
            (revision_id,),
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
                "shifts": [dict(row) for row in ScheduleCapacityRepository.list_calendar_shifts(calendar["id"], db=db)],
            })
        return result

    @staticmethod
    def list_schedule_conflicts(db=None):
        """Find overlapping precision segments on the same production line."""
        db = resolve_db(db)
        try:
            return db.execute(
                """
                SELECT a.process_line_id, a.schedule_id AS first_schedule_id,
                       b.schedule_id AS second_schedule_id,
                       a.segment_start_at AS first_start_at,
                       a.segment_end_at AS first_end_at,
                       b.segment_start_at AS second_start_at,
                       b.segment_end_at AS second_end_at
                FROM order_process_schedule_segments a
                JOIN order_process_schedule_segments b
                  ON a.process_line_id=b.process_line_id
                 AND a.id < b.id
                 AND a.segment_start_at < b.segment_end_at
                 AND b.segment_start_at < a.segment_end_at
                JOIN order_process_schedules sa ON sa.id=a.schedule_id
                JOIN order_process_schedules sb ON sb.id=b.schedule_id
                JOIN orders oa ON oa.id=sa.order_id AND oa.deleted_at IS NULL
                JOIN orders ob ON ob.id=sb.order_id AND ob.deleted_at IS NULL
                WHERE sa.status != 'blocked' AND sb.status != 'blocked'
                ORDER BY a.process_line_id,a.segment_start_at
                """
            ).fetchall()
        except sqlite3.OperationalError:
            return []

    @staticmethod
    def list_schedule_risk_inputs(limit=1000, db=None):
        """Return one precision delivery-risk input row per live order."""
        db = resolve_db(db)
        limit = min(max(int(limit or 1000), 1), 1000)
        try:
            return db.execute(
                """
                SELECT o.id AS order_id, o.order_no, o.deadline, o.plan_end,
                       o.status AS order_status, o.quantity, o.completed,
                       COALESCE(MAX(CASE WHEN s.status != 'blocked'
                                         THEN NULLIF(s.planned_end_at,'') END), '')
                           AS projected_completion_at,
                       COALESCE(SUM(CASE WHEN s.status='blocked' THEN 1 ELSE 0 END),0)
                           AS blocked_count,
                       COALESCE(GROUP_CONCAT(CASE WHEN s.status='blocked'
                                                  THEN NULLIF(s.blocked_reason,'') END, '；'),'')
                           AS blocked_reasons,
                       COALESCE((
                           SELECT COUNT(DISTINCT CASE
                               WHEN first_schedule.order_id=o.id THEN first_schedule.id
                               ELSE second_schedule.id
                           END)
                           FROM order_process_schedule_segments first_segment
                           JOIN order_process_schedule_segments second_segment
                             ON first_segment.process_line_id=second_segment.process_line_id
                            AND first_segment.id < second_segment.id
                            AND first_segment.segment_start_at < second_segment.segment_end_at
                            AND second_segment.segment_start_at < first_segment.segment_end_at
                           JOIN order_process_schedules first_schedule
                             ON first_schedule.id=first_segment.schedule_id
                           JOIN order_process_schedules second_schedule
                             ON second_schedule.id=second_segment.schedule_id
                           JOIN orders first_order ON first_order.id=first_schedule.order_id
                           JOIN orders second_order ON second_order.id=second_schedule.order_id
                           WHERE first_schedule.status != 'blocked'
                             AND second_schedule.status != 'blocked'
                             AND first_order.deleted_at IS NULL
                             AND second_order.deleted_at IS NULL
                             AND (first_schedule.order_id=o.id OR second_schedule.order_id=o.id)
                       ),0) AS conflict_count
                FROM orders o
                JOIN order_process_schedules s ON s.order_id=o.id
                WHERE o.deleted_at IS NULL
                GROUP BY o.id
                ORDER BY o.order_no DESC,o.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []

    @staticmethod
    def find_schedule_risk_input(order_id, db=None):
        """Return the precise delivery-risk input for one live order."""
        db = resolve_db(db)
        try:
            return db.execute(
                """
                SELECT o.id AS order_id, o.order_no, o.deadline, o.plan_end,
                       o.status AS order_status, o.quantity, o.completed,
                       COALESCE(MAX(CASE WHEN s.status != 'blocked'
                                         THEN NULLIF(s.planned_end_at,'') END), '')
                           AS projected_completion_at,
                       COALESCE(SUM(CASE WHEN s.status='blocked' THEN 1 ELSE 0 END),0)
                           AS blocked_count,
                       COALESCE(GROUP_CONCAT(CASE WHEN s.status='blocked'
                                                  THEN NULLIF(s.blocked_reason,'') END, '；'),'')
                           AS blocked_reasons,
                       COALESCE((
                           SELECT COUNT(DISTINCT CASE
                               WHEN first_schedule.order_id=o.id THEN first_schedule.id
                               ELSE second_schedule.id
                           END)
                           FROM order_process_schedule_segments first_segment
                           JOIN order_process_schedule_segments second_segment
                             ON first_segment.process_line_id=second_segment.process_line_id
                            AND first_segment.id < second_segment.id
                            AND first_segment.segment_start_at < second_segment.segment_end_at
                            AND second_segment.segment_start_at < first_segment.segment_end_at
                           JOIN order_process_schedules first_schedule
                             ON first_schedule.id=first_segment.schedule_id
                           JOIN order_process_schedules second_schedule
                             ON second_schedule.id=second_segment.schedule_id
                           JOIN orders first_order ON first_order.id=first_schedule.order_id
                           JOIN orders second_order ON second_order.id=second_schedule.order_id
                           WHERE first_schedule.status != 'blocked'
                             AND second_schedule.status != 'blocked'
                             AND first_order.deleted_at IS NULL
                             AND second_order.deleted_at IS NULL
                             AND (first_schedule.order_id=o.id OR second_schedule.order_id=o.id)
                       ),0) AS conflict_count
                FROM orders o
                JOIN order_process_schedules s ON s.order_id=o.id
                WHERE o.id=? AND o.deleted_at IS NULL
                GROUP BY o.id
                """,
                (order_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return None

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
            "INSERT INTO order_process_schedules (order_id,order_process_id,process_id,process_line_id,production_node_id,"
            "node_code_snapshot,node_name_snapshot,capacity_mode_snapshot,"
            "seq_order,quantity,standard_minutes_per_unit,setup_minutes,difficulty_factor,planned_minutes,plan_start,plan_end,"
            "status,blocked_reason,blocked_code,schedule_run_key,route_version_id,process_version_id,standard_id,standard_version,"
            "process_name_snapshot,route_name_snapshot,schedule_run_id,schedule_revision_id,planned_start_at,planned_end_at,occupied_minutes,"
            "capacity_snapshot_json,standard_match_scope,calendar_id,shift_snapshot_json,line_name_snapshot,execution_mode,"
            "completed_quantity_snapshot,rework_quantity_snapshot,remaining_quantity_snapshot,source_fact_digest) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (data["order_id"], data["order_process_id"], data["process_id"], data.get("process_line_id"),
             data.get("production_node_id"), data.get("node_code_snapshot", ""),
             data.get("node_name_snapshot", ""), data.get("capacity_mode_snapshot", ""),
             data.get("seq_order", 0), data.get("quantity", 0), data.get("standard_minutes_per_unit", 0),
             data.get("setup_minutes", 0), data.get("difficulty_factor", 1), data.get("planned_minutes", 0), data["plan_start"], data["plan_end"],
             data.get("status", "planned"), data.get("blocked_reason", ""), data.get("blocked_code", ""), data.get("schedule_run_key", ""),
             data.get("route_version_id"), data.get("process_version_id"), data.get("standard_id"), data.get("standard_version"),
            data.get("process_name_snapshot", ""), data.get("route_name_snapshot", ""), data.get("schedule_run_id"),
            data.get("schedule_revision_id"),
            data.get("planned_start_at", ""), data.get("planned_end_at", ""), data.get("occupied_minutes", 0),
             data.get("capacity_snapshot_json", "{}"), data.get("standard_match_scope", ""), data.get("calendar_id"),
             data.get("shift_snapshot_json", "[]"), data.get("line_name_snapshot", ""),
             data.get("execution_mode", "internal"),
             data.get("completed_quantity_snapshot", 0), data.get("rework_quantity_snapshot", 0),
             data.get("remaining_quantity_snapshot", data.get("quantity", 0)),
             data.get("source_fact_digest", "")),
        )
        segment_ids = []
        for segment in data.get("segments", ()):
            segment_cursor = db.execute(
                "INSERT INTO order_process_schedule_segments "
                "(schedule_id,process_line_id,production_node_id,segment_start_at,segment_end_at,occupied_minutes,shift_id,quantity) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (cur.lastrowid, segment.get("process_line_id", data.get("process_line_id")),
                 segment.get("production_node_id", data.get("production_node_id")),
                 segment["start_at"], segment["end_at"], segment["occupied_minutes"],
                 segment.get("shift_id"), segment.get("quantity", data.get("quantity", 0))),
            )
            segment_ids.append(segment_cursor.lastrowid)
        allocations = data.get("allocations", ())
        if allocations:
            try:
                for allocation in allocations:
                    node_id = allocation.get("production_node_id")
                    segment_id = None
                    for segment_id_candidate in segment_ids:
                        segment_row = db.execute(
                            "SELECT production_node_id,segment_start_at,segment_end_at "
                            "FROM order_process_schedule_segments WHERE id=?",
                            (segment_id_candidate,),
                        ).fetchone()
                        if not segment_row or segment_row["production_node_id"] != node_id:
                            continue
                        allocation_start = allocation.get("segment_start_at")
                        allocation_end = allocation.get("segment_end_at")
                        if not allocation_start or not allocation_end:
                            segment_id = segment_id_candidate
                            break
                        # One allocation may span multiple calendar segments;
                        # retain the first overlapping segment as its anchor.
                        if (
                            segment_row["segment_start_at"] < allocation_end
                            and segment_row["segment_end_at"] > allocation_start
                        ):
                            segment_id = segment_id_candidate
                            break
                    db.execute(
                        "INSERT INTO production_node_schedule_allocations "
                        "(schedule_id,segment_id,production_node_id,quantity,serial_id,batch_key,"
                        "changeover_minutes,allocation_start_at,allocation_end_at) "
                        "VALUES (?,?,?,?,?,?,?,?,?)",
                        (cur.lastrowid, segment_id, node_id, int(allocation.get("quantity") or 0),
                         allocation.get("serial_id"), allocation.get("batch_key") or "",
                         float(allocation.get("changeover_minutes") or 0),
                         allocation.get("segment_start_at") or "", allocation.get("segment_end_at") or ""),
                    )
            except sqlite3.OperationalError:
                # V088 is additive; keep read-only V087 clones compatible.
                pass
        if data.get("schedule_revision_id"):
            ScheduleCapacityRepository.snapshot_revision_item(cur.lastrowid, data["schedule_revision_id"], db)
        return cur.lastrowid

    @staticmethod
    def snapshot_revision_item(schedule_id, revision_id, db):
        row = db.execute(
            "SELECT * FROM order_process_schedules WHERE id=? AND schedule_revision_id=?",
            (schedule_id, revision_id),
        ).fetchone()
        if row is None:
            raise ValueError("排程事实与版本不一致")
        keys = set(row.keys())
        payload = dict(row)
        payload["segments"] = [
            dict(segment) for segment in db.execute(
                "SELECT * FROM order_process_schedule_segments WHERE schedule_id=? ORDER BY id",
                (schedule_id,),
            ).fetchall()
        ]
        try:
            payload["allocations"] = [
                dict(allocation) for allocation in db.execute(
                    "SELECT * FROM production_node_schedule_allocations "
                    "WHERE schedule_id=? ORDER BY id", (schedule_id,)
                ).fetchall()
            ]
        except sqlite3.OperationalError:
            payload["allocations"] = []
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        db.execute(
            "INSERT OR IGNORE INTO schedule_revision_items "
            "(revision_id,source_schedule_id,order_process_id,process_id,process_line_id,production_node_id,"
            "node_code_snapshot,node_name_snapshot,capacity_mode_snapshot,seq_order,quantity,status,"
            "planned_start_at,planned_end_at,occupied_minutes,payload_json,payload_digest,"
            "execution_mode,completed_quantity_snapshot,rework_quantity_snapshot,remaining_quantity_snapshot,source_fact_digest) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (revision_id, schedule_id, row["order_process_id"], row["process_id"], row["process_line_id"],
             row["production_node_id"] if "production_node_id" in keys else None,
             row["node_code_snapshot"] if "node_code_snapshot" in keys else "",
             row["node_name_snapshot"] if "node_name_snapshot" in keys else "",
             row["capacity_mode_snapshot"] if "capacity_mode_snapshot" in keys else "",
             row["seq_order"], row["quantity"], row["status"], row["planned_start_at"],
             row["planned_end_at"], row["occupied_minutes"], encoded, digest,
             row["execution_mode"] if "execution_mode" in keys else "internal",
             int(row["completed_quantity_snapshot"] or 0) if "completed_quantity_snapshot" in keys else 0,
             int(row["rework_quantity_snapshot"] or 0) if "rework_quantity_snapshot" in keys else 0,
             int(row["remaining_quantity_snapshot"] or row["quantity"] or 0) if "remaining_quantity_snapshot" in keys else int(row["quantity"] or 0),
             row["source_fact_digest"] if "source_fact_digest" in keys else ""),
        )

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
                "AND ri.source_schedule_id=s.id "
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
