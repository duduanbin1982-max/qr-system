"""
qr-system - ScheduleRepository

All SQL for schedule/gantt operations.
"""
from modules.services import BaseService


class ScheduleRepository:
    """Schedule data access."""

    @staticmethod
    def find_scheduled_orders(limit=200, offset=0, db=None):
        """Get orders with plan_start set, with pagination."""
        db = db or BaseService.db()
        return db.execute("""
            SELECT o.id, o.order_no, o.product_name, o.product_code, o.plan_start,
                   o.plan_end, o.production_line_id, o.deadline, o.status, o.quantity,
                   o.completed,
                   COALESCE(c.name, o.customer) as customer_name,
                   COALESCE(pl.name, '') as production_line,
                   COALESCE(pl.capacity_per_day, 10) as line_capacity
            FROM orders o
            LEFT JOIN customers c ON o.customer_id = c.id
            LEFT JOIN production_lines pl ON o.production_line_id = pl.id
            WHERE o.plan_start IS NOT NULL AND o.plan_start != ''
              AND o.deleted_at IS NULL
            ORDER BY o.plan_start, o.order_no
            LIMIT ? OFFSET ?
        """, (limit, offset)).fetchall()

    @staticmethod
    def count_scheduled_orders(db=None):
        db = db or BaseService.db()
        return db.execute("""
            SELECT COUNT(*) FROM orders
            WHERE plan_start IS NOT NULL AND plan_start != '' AND deleted_at IS NULL
        """).fetchone()[0]

    @staticmethod
    def find_order_by_id(order_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT id FROM orders WHERE id = ? AND deleted_at IS NULL", (order_id,)
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
        order = db.execute(
            "SELECT id, plan_start, plan_end FROM orders WHERE id = ? AND deleted_at IS NULL",
            (order_id,)
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
