"""
qr-system - ScheduleRepository

All SQL for schedule/gantt operations.
"""
from modules.repositories.context import resolve_db


class ScheduleRepository:
    """Schedule data access."""

    @staticmethod
    def _completed_expr(alias="o"):
        return (
            f"({alias}.status = 'completed' OR "
            f"(COALESCE({alias}.quantity, 0) > 0 "
            f"AND COALESCE({alias}.completed, 0) >= COALESCE({alias}.quantity, 0)))"
        )

    @staticmethod
    def _schedule_scope_clause(schedule_scope, alias="o"):
        completed_expr = ScheduleRepository._completed_expr(alias)
        if schedule_scope == "completed":
            return " AND " + completed_expr
        if schedule_scope == "all":
            return ""
        return " AND NOT " + completed_expr

    @staticmethod
    def find_scheduled_orders(limit=200, offset=0, schedule_scope="active", db=None):
        """Get orders with plan_start set, with pagination."""
        db = resolve_db(db)
        scope_clause = ScheduleRepository._schedule_scope_clause(schedule_scope)
        completed_expr = ScheduleRepository._completed_expr("o")
        return db.execute(f"""
            SELECT o.id, o.order_no, o.product_name, o.product_code, o.plan_start,
                   o.plan_end, o.production_line_id, o.deadline, o.status, o.quantity,
                   o.completed, o.priority_level, o.is_expedited, o.priority_reason,
                   o.priority_effective_at, o.priority_version, o.schedule_policy,
                   o.current_schedule_revision_id AS schedule_revision_id,
                   CASE WHEN {completed_expr} THEN 1 ELSE 0 END as is_completed,
                   COALESCE(c.name, o.customer) as customer_name,
                   COALESCE(pl.name, '') as production_line,
                   COALESCE(pl.capacity_per_day, 10) as line_capacity,
                   COALESCE((
                       SELECT MAX(NULLIF(s.planned_end_at,''))
                       FROM order_process_schedules s
                       WHERE s.order_id=o.id AND s.status != 'blocked'
                   ), '') AS projected_completion_at,
                   COALESCE((
                       SELECT COUNT(*)
                       FROM order_process_schedules s
                       WHERE s.order_id=o.id AND s.status='blocked'
                   ), 0) AS schedule_blocked_count,
                   COALESCE((
                       SELECT COUNT(*)
                       FROM schedule_node_task_locks l
                       JOIN schedule_revision_items ri ON ri.id=l.revision_item_id
                       JOIN schedule_revisions sr ON sr.id=ri.revision_id
                       WHERE sr.order_id=o.id AND sr.id=o.current_schedule_revision_id
                         AND l.status='active'
                   ), 0) AS locked_task_count,
                   COALESCE(o.completed, 0) AS actual_completed_qty,
                   COALESCE((
                       SELECT MIN(COALESCE(NULLIF(wr.actual_completed_at,''), wr.created_at))
                       FROM work_records wr
                       WHERE wr.order_id=o.id AND wr.status='approved'
                   ), '') AS actual_start_at,
                   COALESCE((
                       SELECT MAX(COALESCE(NULLIF(wr.actual_completed_at,''), wr.created_at))
                       FROM work_records wr
                       WHERE wr.order_id=o.id AND wr.status='approved'
                   ), '') AS actual_last_report_at,
                   CASE WHEN {completed_expr} THEN COALESCE((
                       SELECT MAX(COALESCE(NULLIF(wr.actual_completed_at,''), wr.created_at))
                       FROM work_records wr
                       WHERE wr.order_id=o.id AND wr.status='approved'
                   ), '') ELSE '' END AS actual_end_at,
                   COALESCE((
                       SELECT GROUP_CONCAT(NULLIF(s.blocked_reason,''), '；')
                       FROM order_process_schedules s
                       WHERE s.order_id=o.id AND s.status='blocked'
                   ), '') AS schedule_blocked_reasons,
                   COALESCE((
                       SELECT COUNT(DISTINCT CASE
                           WHEN first_fact.order_id=o.id THEN first_fact.fact_key
                           ELSE second_fact.fact_key
                       END)
                       FROM schedule_effective_capacity_intervals first_fact
                       JOIN schedule_effective_capacity_intervals second_fact
                         ON first_fact.fact_key < second_fact.fact_key
                        AND ((first_fact.production_node_id IS NOT NULL
                              AND first_fact.production_node_id=second_fact.production_node_id)
                             OR (first_fact.production_node_id IS NULL
                                 AND second_fact.production_node_id IS NULL
                                 AND first_fact.process_line_id=second_fact.process_line_id))
                        AND first_fact.start_at < second_fact.end_at
                        AND second_fact.start_at < first_fact.end_at
                       WHERE (first_fact.capacity_mode='exclusive'
                              OR second_fact.capacity_mode='exclusive')
                         AND (first_fact.order_id=o.id OR second_fact.order_id=o.id)
                   ), 0) AS schedule_conflict_count
            FROM orders o
            LEFT JOIN customers c ON o.customer_id = c.id
            LEFT JOIN production_lines pl ON o.production_line_id = pl.id
            WHERE o.plan_start IS NOT NULL AND o.plan_start != ''
              AND o.deleted_at IS NULL
              {scope_clause}
            ORDER BY o.order_no DESC, o.id DESC
            LIMIT ? OFFSET ?
        """, (limit, offset)).fetchall()

    @staticmethod
    def count_scheduled_orders(schedule_scope="active", db=None):
        return ScheduleRepository.get_schedule_summary(
            schedule_scope=schedule_scope,
            db=db,
        )["total"]

    @staticmethod
    def get_schedule_summary(schedule_scope="active", db=None):
        db = resolve_db(db)
        scope_clause = ScheduleRepository._schedule_scope_clause(schedule_scope)
        completed_expr = ScheduleRepository._completed_expr("o")
        return db.execute(f"""
            SELECT COUNT(*) AS total,
                   COALESCE(SUM(CASE WHEN {completed_expr} THEN 1 ELSE 0 END), 0) AS completed,
                   COALESCE(SUM(CASE WHEN o.status = 'producing' AND NOT {completed_expr}
                                     THEN 1 ELSE 0 END), 0) AS producing,
                   COALESCE(SUM(CASE WHEN o.status = 'pending' AND NOT {completed_expr}
                                     THEN 1 ELSE 0 END), 0) AS pending,
                   MIN(o.plan_start) AS min_date,
                   MAX(NULLIF(o.plan_end, '')) AS max_date
            FROM orders o
            WHERE o.plan_start IS NOT NULL AND o.plan_start != '' AND o.deleted_at IS NULL
              {scope_clause}
        """).fetchone()

    @staticmethod
    def find_order_by_id(order_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id, status, quantity, completed, production_line_id "
            "FROM orders WHERE id = ? AND deleted_at IS NULL",
            (order_id,),
        ).fetchone()

    @staticmethod
    def update_order_schedule_txn(
        order_id,
        plan_start,
        plan_end,
        production_line_id,
        *,
        update_production_line,
        db,
    ):
        assignments = ["plan_start = ?", "plan_end = ?"]
        params = [plan_start, plan_end]
        if update_production_line:
            assignments.append("production_line_id = ?")
            params.append(production_line_id)
        assignments.append("updated_at = datetime('now','localtime')")
        params.append(order_id)
        completed_expr = ScheduleRepository._completed_expr("orders")
        cursor = db.execute(
            f"UPDATE orders SET {', '.join(assignments)} "
            f"WHERE id = ? AND deleted_at IS NULL AND NOT {completed_expr}",
            params,
        )
        return cursor.rowcount

    @staticmethod
    def shift_order_dates_txn(order_id, days, db):
        """Shift order plan dates by a signed number of days within a transaction."""
        completed_expr = ScheduleRepository._completed_expr("o")
        order = db.execute(
            f"SELECT id, plan_start, plan_end FROM orders o "
            f"WHERE id = ? AND deleted_at IS NULL AND NOT {completed_expr}",
            (order_id,),
        ).fetchone()
        if not order or not order["plan_start"]:
            return False
        sign = "+" if days >= 0 else ""
        db.execute("""
            UPDATE orders SET
                plan_start = date(plan_start, ? || CAST(? AS TEXT) || ' days'),
                plan_end = date(plan_end, ? || CAST(? AS TEXT) || ' days'),
                updated_at = datetime('now','localtime')
            WHERE id = ?
        """, (sign, days, sign, days, order_id))
        return True
