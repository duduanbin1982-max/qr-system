"""qr-system - PersonalStatsRepository"""
from modules.repositories.context import resolve_db
from modules.process_fact_projection import (
    process_value_sql,
    process_version_join,
    warn_legacy_fact_rows,
)


class PersonalStatsRepository:

    @staticmethod
    def get_today_records(user_id, today_start, db=None):
        db = resolve_db(db)
        process_name = process_value_sql("wr", "process_version", "p")
        rows = db.execute(
            "SELECT wr.id, wr.order_id, wr.process_id, wr.serial_no, wr.quantity, wr.type, wr.remark, wr.created_at, "
            "wr.process_version_id,o.order_no,o.product_name," + process_name + " AS process_name "
            "FROM work_records wr LEFT JOIN orders o ON wr.order_id=o.id "
            "LEFT JOIN processes p ON wr.process_id=p.id "
            + process_version_join("wr", "process_version")
            + "WHERE wr.user_id=? AND wr.created_at>=? ORDER BY wr.created_at DESC LIMIT 50",
            (user_id, today_start)
        ).fetchall()
        warn_legacy_fact_rows("work_records", rows)
        return rows

    @staticmethod
    def get_today_summary(user_id, today_start, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) as total_records, COALESCE(SUM(quantity),0) as total_qty, "
            "COUNT(DISTINCT order_id) as order_count FROM work_records "
            "WHERE user_id=? AND created_at>=?", (user_id, today_start)
        ).fetchone()

    @staticmethod
    def get_week_summary(user_id, week_start, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) as total_records, COALESCE(SUM(quantity),0) as total_qty, "
            "COUNT(DISTINCT order_id) as order_count FROM work_records "
            "WHERE user_id=? AND created_at>=?", (user_id, week_start)
        ).fetchone()

    @staticmethod
    def get_month_summary(user_id, month_start, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COUNT(*) as total_records, COALESCE(SUM(quantity),0) as total_qty, "
            "COUNT(DISTINCT order_id) as order_count FROM work_records "
            "WHERE user_id=? AND created_at>=?", (user_id, month_start)
        ).fetchone()

    @staticmethod
    def get_process_breakdown(user_id, today_start, db=None):
        db = resolve_db(db)
        process_name = process_value_sql("wr", "process_version", "p")
        rows = db.execute(
            "SELECT wr.process_id,wr.process_version_id," + process_name + " AS process_name,"
            "COUNT(*) AS count,COALESCE(SUM(wr.quantity),0) AS total_qty "
            "FROM work_records wr LEFT JOIN processes p ON wr.process_id=p.id "
            + process_version_join("wr", "process_version")
            + "WHERE wr.user_id=? AND wr.created_at>=? GROUP BY wr.process_id,"
            "wr.process_version_id," + process_name + " ORDER BY total_qty DESC",
            (user_id, today_start)
        ).fetchall()
        warn_legacy_fact_rows("work_records", rows)
        return rows

    @staticmethod
    def get_active_orders(user_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT DISTINCT o.id, o.order_no, o.product_name, o.status, o.quantity, "
            "(SELECT COALESCE(SUM(wr2.quantity),0) FROM work_records wr2 WHERE wr2.order_id=o.id AND wr2.user_id=?) as my_qty "
            "FROM work_records wr JOIN orders o ON wr.order_id=o.id "
            "WHERE wr.user_id=? AND o.status IN ('producing','pending') ORDER BY wr.created_at DESC LIMIT 10",
            (user_id, user_id)
        ).fetchall()

    @staticmethod
    def get_day_stats(user_id, day_start, day_end, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT COALESCE(SUM(quantity),0) as qty, COUNT(*) as records FROM work_records "
            "WHERE user_id=? AND created_at>=? AND created_at<?",
            (user_id, day_start, day_end)
        ).fetchone()
