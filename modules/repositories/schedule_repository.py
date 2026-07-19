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
                   COALESCE(pl.capacity_per_day, 10) as line_capacity
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
        db = resolve_db(db)
        scope_clause = ScheduleRepository._schedule_scope_clause(schedule_scope)
        return db.execute(f"""
            SELECT COUNT(*) FROM orders o
            WHERE o.plan_start IS NOT NULL AND o.plan_start != '' AND o.deleted_at IS NULL
              {scope_clause}
        """).fetchone()[0]

    @staticmethod
    def find_order_by_id(order_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT id, status, quantity, completed FROM orders WHERE id = ? AND deleted_at IS NULL",
            (order_id,),
        ).fetchone()

    @staticmethod
    def update_order_schedule_txn(order_id, plan_start, plan_end, production_line_id, db):
        db.execute(
            "UPDATE orders SET plan_start = ?, plan_end = ?, production_line_id = ?, "
            "updated_at = datetime('now','localtime') WHERE id = ?",
            (plan_start, plan_end, production_line_id, order_id)
        )

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
