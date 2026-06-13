"""qr-system — PersonalStatsService"""
from modules.services import BaseService


class PersonalStatsService:
    @staticmethod
    def get_all_stats(user_id, today_start, week_start, month_start):
        db = BaseService.db()
        today_records = db.execute(
            "SELECT wr.id, wr.order_id, wr.process_id, wr.serial_no, wr.quantity, wr.type, wr.remark, wr.created_at, "
            "o.order_no, o.product_name, p.name as process_name "
            "FROM work_records wr LEFT JOIN orders o ON wr.order_id=o.id "
            "LEFT JOIN processes p ON wr.process_id=p.id "
            "WHERE wr.user_id=? AND wr.created_at>=? ORDER BY wr.created_at DESC LIMIT 50",
            (user_id, today_start)
        ).fetchall()

        today_sum = db.execute(
            "SELECT COUNT(*) as total_records, COALESCE(SUM(quantity),0) as total_qty, "
            "COUNT(DISTINCT order_id) as order_count FROM work_records "
            "WHERE user_id=? AND created_at>=?", (user_id, today_start)
        ).fetchone()

        week_sum = db.execute(
            "SELECT COUNT(*) as total_records, COALESCE(SUM(quantity),0) as total_qty, "
            "COUNT(DISTINCT order_id) as order_count FROM work_records "
            "WHERE user_id=? AND created_at>=?", (user_id, week_start)
        ).fetchone()

        month_sum = db.execute(
            "SELECT COUNT(*) as total_records, COALESCE(SUM(quantity),0) as total_qty, "
            "COUNT(DISTINCT order_id) as order_count FROM work_records "
            "WHERE user_id=? AND created_at>=?", (user_id, month_start)
        ).fetchone()

        process_breakdown = db.execute(
            "SELECT p.name as process_name, COUNT(*) as count, COALESCE(SUM(wr.quantity),0) as total_qty "
            "FROM work_records wr LEFT JOIN processes p ON wr.process_id=p.id "
            "WHERE wr.user_id=? AND wr.created_at>=? GROUP BY wr.process_id ORDER BY total_qty DESC",
            (user_id, today_start)
        ).fetchall()

        active_orders = db.execute(
            "SELECT DISTINCT o.id, o.order_no, o.product_name, o.status, o.quantity, "
            "(SELECT COALESCE(SUM(wr2.quantity),0) FROM work_records wr2 WHERE wr2.order_id=o.id AND wr2.user_id=?) as my_qty "
            "FROM work_records wr JOIN orders o ON wr.order_id=o.id "
            "WHERE wr.user_id=? AND o.status IN ('producing','pending') ORDER BY wr.created_at DESC LIMIT 10",
            (user_id, user_id)
        ).fetchall()

        trend = []
        from datetime import datetime, timedelta
        now = datetime.now()
        for i in range(6, -1, -1):
            day = (now - timedelta(days=i)).strftime('%Y-%m-%d')
            ds = db.execute(
                "SELECT COALESCE(SUM(quantity),0) as qty, COUNT(*) as records FROM work_records "
                "WHERE user_id=? AND created_at>=? AND created_at<?",
                (user_id, day + ' 00:00:00', day + ' 23:59:59')
            ).fetchone()
            trend.append({'date': day, 'quantity': ds['qty'], 'records': ds['records']})

        return {
            'today_records': [dict(r) for r in today_records],
            'today_sum': dict(today_sum),
            'week_sum': dict(week_sum),
            'month_sum': dict(month_sum),
            'process_breakdown': [dict(r) for r in process_breakdown],
            'active_orders': [dict(r) for r in active_orders],
            'trend': trend,
        }
