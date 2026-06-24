"""qr-system - PersonalStatsRepository"""
from modules.db_unit_of_work import BaseService


class PersonalStatsRepository:

    @staticmethod
    def get_today_records(user_id, today_start, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT wr.id, wr.order_id, wr.process_id, wr.serial_no, wr.quantity, wr.type, wr.remark, wr.created_at, "
            "o.order_no, o.product_name, p.name as process_name "
            "FROM work_records wr LEFT JOIN orders o ON wr.order_id=o.id "
            "LEFT JOIN processes p ON wr.process_id=p.id "
            "WHERE wr.user_id=? AND wr.created_at>=? ORDER BY wr.created_at DESC LIMIT 50",
            (user_id, today_start)
        ).fetchall()

    @staticmethod
    def get_today_summary(user_id, today_start, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) as total_records, COALESCE(SUM(quantity),0) as total_qty, "
            "COUNT(DISTINCT order_id) as order_count FROM work_records "
            "WHERE user_id=? AND created_at>=?", (user_id, today_start)
        ).fetchone()

    @staticmethod
    def get_week_summary(user_id, week_start, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) as total_records, COALESCE(SUM(quantity),0) as total_qty, "
            "COUNT(DISTINCT order_id) as order_count FROM work_records "
            "WHERE user_id=? AND created_at>=?", (user_id, week_start)
        ).fetchone()

    @staticmethod
    def get_month_summary(user_id, month_start, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) as total_records, COALESCE(SUM(quantity),0) as total_qty, "
            "COUNT(DISTINCT order_id) as order_count FROM work_records "
            "WHERE user_id=? AND created_at>=?", (user_id, month_start)
        ).fetchone()

    @staticmethod
    def get_process_breakdown(user_id, today_start, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT p.name as process_name, COUNT(*) as count, COALESCE(SUM(wr.quantity),0) as total_qty "
            "FROM work_records wr LEFT JOIN processes p ON wr.process_id=p.id "
            "WHERE wr.user_id=? AND wr.created_at>=? GROUP BY wr.process_id ORDER BY total_qty DESC",
            (user_id, today_start)
        ).fetchall()

    @staticmethod
    def get_active_orders(user_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT DISTINCT o.id, o.order_no, o.product_name, o.status, o.quantity, "
            "(SELECT COALESCE(SUM(wr2.quantity),0) FROM work_records wr2 WHERE wr2.order_id=o.id AND wr2.user_id=?) as my_qty "
            "FROM work_records wr JOIN orders o ON wr.order_id=o.id "
            "WHERE wr.user_id=? AND o.status IN ('producing','pending') ORDER BY wr.created_at DESC LIMIT 10",
            (user_id, user_id)
        ).fetchall()

    @staticmethod
    def get_day_stats(user_id, day_start, day_end, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COALESCE(SUM(quantity),0) as qty, COUNT(*) as records FROM work_records "
            "WHERE user_id=? AND created_at>=? AND created_at<?",
            (user_id, day_start, day_end)
        ).fetchone()
