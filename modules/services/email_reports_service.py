"""qr-system — EmailReportsService"""
from modules.services import BaseService


class EmailReportsService:
    @staticmethod
    def daily_stats(today):
        db = BaseService.db()
        total_orders = db.execute(
            "SELECT COUNT(*) FROM orders WHERE date(created_at)=? AND deleted_at IS NULL", (today,)
        ).fetchone()[0]
        new_orders = db.execute(
            "SELECT COUNT(*) FROM orders WHERE date(created_at)=? AND status='pending' AND deleted_at IS NULL", (today,)
        ).fetchone()[0]
        completed_orders = db.execute(
            "SELECT COUNT(*) FROM orders WHERE date(updated_at)=? AND status='completed'", (today,)
        ).fetchone()[0]
        wr_sum = db.execute(
            "SELECT COUNT(*) as records, COALESCE(SUM(quantity),0) as qty, COUNT(DISTINCT user_id) as workers "
            "FROM work_records WHERE date(created_at)=?", (today,)
        ).fetchone()
        top_workers = db.execute(
            "SELECT u.name, COALESCE(SUM(wr.quantity),0) as qty, COUNT(*) as records "
            "FROM work_records wr LEFT JOIN users u ON wr.user_id=u.id "
            "WHERE date(wr.created_at)=? GROUP BY wr.user_id ORDER BY qty DESC LIMIT 5", (today,)
        ).fetchall()
        proc_breakdown = db.execute(
            "SELECT p.name, COALESCE(SUM(wr.quantity),0) as qty, COUNT(*) as records "
            "FROM work_records wr LEFT JOIN processes p ON wr.process_id=p.id "
            "WHERE date(wr.created_at)=? GROUP BY wr.process_id ORDER BY qty DESC LIMIT 10", (today,)
        ).fetchall()
        return {
            'total_orders': total_orders, 'new_orders': new_orders,
            'completed_orders': completed_orders, 'wr_sum': dict(wr_sum),
            'top_workers': [dict(w) for w in top_workers],
            'proc_breakdown': [dict(p) for p in proc_breakdown],
        }

    @staticmethod
    def weekly_stats(week_start, week_end):
        db = BaseService.db()
        total_orders = db.execute(
            "SELECT COUNT(*) FROM orders WHERE date(created_at) BETWEEN ? AND ? AND deleted_at IS NULL",
            (week_start, week_end)
        ).fetchone()[0]
        completed = db.execute(
            "SELECT COUNT(*) FROM orders WHERE date(updated_at) BETWEEN ? AND ? AND status='completed'",
            (week_start, week_end)
        ).fetchone()[0]
        wr_sum = db.execute(
            "SELECT COUNT(*) as records, COALESCE(SUM(quantity),0) as qty, COUNT(DISTINCT user_id) as workers "
            "FROM work_records WHERE date(created_at) BETWEEN ? AND ?", (week_start, week_end)
        ).fetchone()
        top_workers = db.execute(
            "SELECT u.name, COALESCE(SUM(wr.quantity),0) as qty "
            "FROM work_records wr LEFT JOIN users u ON wr.user_id=u.id "
            "WHERE date(wr.created_at) BETWEEN ? AND ? "
            "GROUP BY wr.user_id ORDER BY qty DESC LIMIT 5", (week_start, week_end)
        ).fetchall()
        return {
            'total_orders': total_orders, 'completed': completed,
            'wr_sum': dict(wr_sum), 'top_workers': [dict(w) for w in top_workers],
        }
