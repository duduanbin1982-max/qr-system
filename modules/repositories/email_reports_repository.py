"""qr-system - EmailReportsRepository"""
from modules.repositories.context import resolve_db
from modules.process_fact_projection import (
    process_value_sql,
    process_version_join,
    warn_legacy_fact_rows,
)


class EmailReportsRepository:

    @staticmethod
    def get_daily_order_stats(today, db=None):
        db = resolve_db(db)
        total = db.execute(
            "SELECT COUNT(*) FROM orders WHERE date(created_at)=? AND deleted_at IS NULL", (today,)
        ).fetchone()[0]
        new_orders = db.execute(
            "SELECT COUNT(*) FROM orders WHERE date(created_at)=? AND status='pending' AND deleted_at IS NULL", (today,)
        ).fetchone()[0]
        completed = db.execute(
            "SELECT COUNT(*) FROM orders WHERE date(updated_at)=? AND status='completed'", (today,)
        ).fetchone()[0]
        return total, new_orders, completed

    @staticmethod
    def get_daily_work_records(today, db=None):
        db = resolve_db(db)
        wr_sum = db.execute(
            "SELECT COUNT(*) as records, COALESCE(SUM(quantity),0) as qty, COUNT(DISTINCT user_id) as workers "
            "FROM work_records WHERE date(created_at)=?", (today,)
        ).fetchone()
        top_workers = db.execute(
            "SELECT u.name, COALESCE(SUM(wr.quantity),0) as qty, COUNT(*) as records "
            "FROM work_records wr LEFT JOIN users u ON wr.user_id=u.id "
            "WHERE date(wr.created_at)=? GROUP BY wr.user_id ORDER BY qty DESC LIMIT 5", (today,)
        ).fetchall()
        process_name = process_value_sql("wr", "process_version", "p")
        proc_breakdown = db.execute(
            "SELECT wr.process_id,wr.process_version_id," + process_name + " AS name,"
            "COALESCE(SUM(wr.quantity),0) AS qty,COUNT(*) AS records "
            "FROM work_records wr LEFT JOIN processes p ON wr.process_id=p.id "
            + process_version_join("wr", "process_version")
            + "WHERE date(wr.created_at)=? GROUP BY wr.process_id,wr.process_version_id,"
            + process_name + " ORDER BY qty DESC LIMIT 10", (today,)
        ).fetchall()
        warn_legacy_fact_rows("work_records", proc_breakdown)
        return wr_sum, top_workers, proc_breakdown

    @staticmethod
    def get_weekly_order_stats(week_start, week_end, db=None):
        db = resolve_db(db)
        total = db.execute(
            "SELECT COUNT(*) FROM orders WHERE date(created_at) BETWEEN ? AND ? AND deleted_at IS NULL",
            (week_start, week_end)
        ).fetchone()[0]
        completed = db.execute(
            "SELECT COUNT(*) FROM orders WHERE date(updated_at) BETWEEN ? AND ? AND status='completed'",
            (week_start, week_end)
        ).fetchone()[0]
        return total, completed

    @staticmethod
    def get_weekly_work_records(week_start, week_end, db=None):
        db = resolve_db(db)
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
        return wr_sum, top_workers
