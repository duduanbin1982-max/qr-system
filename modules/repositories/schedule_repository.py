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
                   o.completed,
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
                       SELECT GROUP_CONCAT(NULLIF(s.blocked_reason,''), '；')
                       FROM order_process_schedules s
                       WHERE s.order_id=o.id AND s.status='blocked'
                   ), '') AS schedule_blocked_reasons,
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
