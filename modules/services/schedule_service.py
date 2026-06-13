"""
qr-system — ScheduleService
"""
from modules.services import BaseService


class ScheduleService:
    @staticmethod
    def get_gantt_data():
        db = BaseService.db()
        rows = db.execute('''
            SELECT o.id, o.order_no, o.product_name, o.plan_start, o.plan_end,
                   o.status, o.quantity, o.completed,
                   COALESCE(c.name, o.customer) as customer_name
            FROM orders o
            LEFT JOIN customers c ON o.customer_id = c.id
            WHERE o.plan_start IS NOT NULL AND o.plan_start != ''
              AND o.deleted_at IS NULL
            ORDER BY o.plan_start, o.order_no
        ''').fetchall()

        orders = []
        min_date = None
        max_date = None
        for r in rows:
            start = r['plan_start']
            end = r['plan_end']
            orders.append({
                'id': r['id'], 'order_no': r['order_no'],
                'product_name': r['product_name'],
                'customer_name': r['customer_name'],
                'plan_start': start, 'plan_end': end,
                'status': r['status'], 'quantity': r['quantity'],
                'completed': r['completed'],
                'progress': min(round(r['completed'] / r['quantity'] * 100), 100) if r['quantity'] else 0,
            })
            if start:
                if min_date is None or start < min_date: min_date = start
                if max_date is None or end > max_date: max_date = end
        return {'ok': True, 'orders': orders, 'min_date': min_date, 'max_date': max_date}
