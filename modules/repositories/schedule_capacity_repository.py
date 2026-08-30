"""Persistence for process-level production-line pools and operation schedules."""

from modules.repositories.context import resolve_db


DEFAULT_PROCESS_LINE_COUNTS = {
    "下料": 1,
    "铆接": 4,
    "焊接": 10,
    "抛丸": 1,
    "打磨": 1,
    "镗孔": 2,
    "喷漆": 2,
}


class ScheduleCapacityRepository:
    @staticmethod
    def ensure_default_lines(process_id, process_name, db):
        count = DEFAULT_PROCESS_LINE_COUNTS.get(process_name)
        if not count:
            return 0
        existing = db.execute(
            "SELECT id, line_code FROM process_production_lines WHERE process_id=? ORDER BY id",
            (process_id,),
        ).fetchall()
        # Process roots are stable identities. Reuse their existing pool when a
        # process is renamed instead of creating a second pool under new codes.
        if len(existing) >= count:
            return 0
        used_codes = {row["line_code"] for row in existing}
        inserted = 0
        for index in range(1, count + 1):
            code = f"{process_name}-{index:02d}"
            if code in used_codes:
                continue
            cursor = db.execute(
                "INSERT OR IGNORE INTO process_production_lines "
                "(process_id,line_code,line_name,daily_minutes,remark) VALUES (?,?,?,480,'系统默认产线')",
                (process_id, code, f"{process_name}{index}线"),
            )
            inserted += cursor.rowcount
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
            "SELECT id, quantity, plan_start, product_code, route_id FROM orders "
            "WHERE id=? AND deleted_at IS NULL",
            (order_id,),
        ).fetchone()

    @staticmethod
    def find_active_standard(route_id, process_id, product_code, db):
        select = (
            "SELECT setup_minutes, standard_minutes_per_unit, difficulty_factor "
            "FROM work_time_standards WHERE process_id=? AND status='active' "
        )
        if route_id:
            exact = db.execute(
                select + "AND route_id=? ORDER BY CASE WHEN product_code=? THEN 0 ELSE 1 END, id DESC LIMIT 1",
                (process_id, route_id, product_code or ""),
            ).fetchone()
            if exact:
                return exact
        # A route-specific standard is preferred, but a generic process standard
        # remains a valid fallback when the route has not been configured yet.
        return db.execute(
            select + "AND route_id IS NULL ORDER BY CASE WHEN product_code=? THEN 0 ELSE 1 END, id DESC LIMIT 1",
            (process_id, product_code or ""),
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
    def list_process_lines(process_id=None, db=None):
        db = resolve_db(db)
        if process_id is None:
            return db.execute(
                "SELECT pl.*, p.name AS process_name FROM process_production_lines pl "
                "JOIN processes p ON p.id=pl.process_id ORDER BY p.seq_order, p.id, pl.line_code"
            ).fetchall()
        return db.execute(
            "SELECT pl.*, p.name AS process_name FROM process_production_lines pl "
            "JOIN processes p ON p.id=pl.process_id WHERE pl.process_id=? "
            "ORDER BY pl.line_code", (process_id,)
        ).fetchall()

    @staticmethod
    def find_line(line_id, db=None):
        db = resolve_db(db)
        return db.execute("SELECT * FROM process_production_lines WHERE id=?", (line_id,)).fetchone()

    @staticmethod
    def find_order_operations(order_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT op.id AS order_process_id, op.order_id, op.process_id, op.seq_order, "
            "op.status, op.completed, op.scrapped, p.name AS process_name, "
            "s.id AS schedule_id, s.process_line_id, s.quantity AS scheduled_quantity, "
            "s.standard_minutes_per_unit, s.setup_minutes, s.difficulty_factor, s.planned_minutes, "
            "s.plan_start, s.plan_end, s.status AS schedule_status, s.blocked_reason, s.schedule_run_key, pl.line_name "
            "FROM order_processes op JOIN processes p ON p.id=op.process_id "
            "LEFT JOIN order_process_schedules s ON s.order_process_id=op.id "
            "LEFT JOIN process_production_lines pl ON pl.id=s.process_line_id "
            "WHERE op.order_id=? ORDER BY op.seq_order, op.id", (order_id,)
        ).fetchall()

    @staticmethod
    def clear_order_schedules(order_id, db):
        db.execute("DELETE FROM order_process_schedules WHERE order_id=?", (order_id,))

    @staticmethod
    def find_run(order_id, schedule_run_key, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT DISTINCT order_id FROM order_process_schedules "
            "WHERE schedule_run_key=? LIMIT 2",
            (schedule_run_key,),
        ).fetchall()

    @staticmethod
    def line_available_dates(exclude_order_id, db):
        """Return the first free date after schedules belonging to other orders."""
        return db.execute(
            "SELECT process_line_id, MAX(plan_end) AS last_end "
            "FROM order_process_schedules "
            "WHERE order_id != ? AND process_line_id IS NOT NULL "
            "AND status != 'blocked' GROUP BY process_line_id",
            (exclude_order_id,),
        ).fetchall()

    @staticmethod
    def insert_operation_schedule(data, db):
        cur = db.execute(
            "INSERT INTO order_process_schedules (order_id,order_process_id,process_id,process_line_id,"
            "seq_order,quantity,standard_minutes_per_unit,setup_minutes,difficulty_factor,planned_minutes,plan_start,plan_end,"
            "status,blocked_reason,schedule_run_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (data["order_id"], data["order_process_id"], data["process_id"], data.get("process_line_id"),
             data.get("seq_order", 0), data.get("quantity", 0), data.get("standard_minutes_per_unit", 0),
             data.get("setup_minutes", 0), data.get("difficulty_factor", 1), data.get("planned_minutes", 0), data["plan_start"], data["plan_end"],
             data.get("status", "planned"), data.get("blocked_reason", ""), data.get("schedule_run_key", "")),
        )
        return cur.lastrowid

    @staticmethod
    def list_scheduled_operations(limit=500, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT s.*, o.order_no, o.product_name, p.name AS process_name, pl.line_name "
            "FROM order_process_schedules s JOIN orders o ON o.id=s.order_id "
            "JOIN processes p ON p.id=s.process_id LEFT JOIN process_production_lines pl ON pl.id=s.process_line_id "
            "WHERE o.deleted_at IS NULL ORDER BY s.plan_start, s.seq_order, o.order_no LIMIT ?", (limit,)
        ).fetchall()
