"""
qr-system — ScheduleService
"""
from datetime import datetime, timedelta
from modules.services import BaseService


class ScheduleService:
    @staticmethod
    def get_gantt_data():
        db = BaseService.db()
        rows = db.execute('''
            SELECT o.id, o.order_no, o.product_name, o.product_code, o.plan_start, o.plan_end,
                   o.deadline, o.status, o.quantity, o.completed,
                   COALESCE(c.name, o.customer) as customer_name,
                   COALESCE(pl.name, '') as production_line,
                   COALESCE(pl.capacity_per_day, 10) as line_capacity
            FROM orders o
            LEFT JOIN customers c ON o.customer_id = c.id
            LEFT JOIN production_lines pl ON o.production_line_id = pl.id
            WHERE o.plan_start IS NOT NULL AND o.plan_start != ''
              AND o.deleted_at IS NULL
              AND o.status != 'completed'
            ORDER BY o.plan_start, o.order_no
        ''').fetchall()

        orders = []
        min_date = None
        max_date = None
        now = datetime.now()
        today_str = now.strftime('%Y-%m-%d')
        two_days_later = (now + timedelta(days=2)).strftime('%Y-%m-%d')
        for r in rows:
            start = r['plan_start']
            end = r['plan_end']
            progress = min(round(r['completed'] / r['quantity'] * 100), 100) if r['quantity'] else 0

            # Deadline risk assessment
            deadline = r['deadline'] if r['deadline'] else None
            risk = 'normal'
            if end and end < today_str and progress < 100:
                risk = 'overdue'
            elif end and end <= two_days_later and progress < 60:
                risk = 'warning'

            orders.append({
                'id': r['id'], 'order_no': r['order_no'],
                'deadline': r['deadline'],
                'completed_qty': r['completed'],
                'product_name': r['product_name'],
                'product_code': r['product_code'],
                'customer_name': r['customer_name'],
                'plan_start': start, 'plan_end': end,
                'status': r['status'], 'quantity': r['quantity'],
                'completed': r['completed'],
                'progress': progress,
                'risk': risk,
                'production_line': r['production_line'],
                'line_capacity': r['line_capacity'],
            })
            if start:
                if min_date is None or start < min_date: min_date = start
                if max_date is None or end > max_date: max_date = end

        # Extend max_date to end of next month
        if max_date:
            ref = datetime.strptime(max_date, '%Y-%m-%d')
        else:
            ref = now
        # First day of the month after next: go to next month, then next again
        y, m = ref.year, ref.month
        m += 2  # skip to month after next
        if m > 12:
            y += 1
            m -= 12
        # Last day of that month = first day of following month - 1 day
        if m == 12:
            last_day = datetime(y + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = datetime(y, m + 1, 1) - timedelta(days=1)
        max_date = last_day.strftime('%Y-%m-%d')

        return {'ok': True, 'orders': orders, 'min_date': min_date, 'max_date': max_date}
    @staticmethod
    def update_order_schedule(order_id, plan_start, plan_end):
        """拖拽排程：更新订单计划时间"""
        db = BaseService.db()
        order = db.execute(
            "SELECT id FROM orders WHERE id = ? AND deleted_at IS NULL",
            (order_id,)
        ).fetchone()
        if not order:
            raise ValueError("订单不存在")

        db.execute(
            "UPDATE orders SET plan_start = ?, plan_end = ?, updated_at = datetime('now','localtime') WHERE id = ?",
            (plan_start, plan_end, order_id)
        )
        db.commit()

    @staticmethod
    def batch_shift(order_ids, days):
        """批量偏移订单排程日期"""
        db = BaseService.db()
        count = 0
        for oid in order_ids:
            order = db.execute(
                "SELECT id, plan_start, plan_end FROM orders WHERE id = ? AND deleted_at IS NULL",
                (oid,)
            ).fetchone()
            if not order or not order["plan_start"]:
                continue
            # Shift dates by days using SQLite date functions
            db.execute("""
                UPDATE orders SET
                    plan_start = date(plan_start, '+' || ? || ' days'),
                    plan_end = date(plan_end, '+' || ? || ' days'),
                    updated_at = datetime('now','localtime')
                WHERE id = ?
            """, (days, days, oid))
            count += 1
        db.commit()
        return count
