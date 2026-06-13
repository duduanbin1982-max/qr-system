"""qr-system — StatsService"""
from modules.services import BaseService


class StatsService:
    @staticmethod
    def get_daily_records(date):
        db = BaseService.db()
        records = db.execute(
            "SELECT wr.id, wr.created_at, wr.quantity, wr.type, wr.status, "
            "o.order_no, o.product_name, p.name as process_name, u.name as worker_name "
            "FROM work_records wr "
            "JOIN orders o ON wr.order_id=o.id AND o.deleted_at IS NULL "
            "JOIN processes p ON wr.process_id=p.id "
            "JOIN users u ON wr.user_id=u.id "
            "WHERE wr.status='approved' AND DATE(wr.created_at)=? ORDER BY wr.created_at DESC", (date,)
        ).fetchall()
        summary = db.execute(
            "SELECT p.id, p.name, COUNT(*) as record_count, "
            "COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as total_output, "
            "COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as total_scrap, "
            "COALESCE(SUM(CASE WHEN wr.type='rework' THEN wr.quantity ELSE 0 END),0) as total_rework "
            "FROM work_records wr "
            "JOIN orders o ON wr.order_id=o.id AND o.deleted_at IS NULL "
            "JOIN processes p ON wr.process_id=p.id "
            "WHERE wr.status='approved' AND DATE(wr.created_at)=? GROUP BY p.id ORDER BY record_count DESC", (date,)
        ).fetchall()
        return {
            "records": [dict(r) for r in records],
            "summary": [dict(s) for s in summary],
        }

    @staticmethod
    def get_scrap_records(start="", end=""):
        db = BaseService.db()
        where = ["o.deleted_at IS NULL"]
        params = []
        if start:
            where.append("DATE(sr.created_at) >= ?"); params.append(start)
        if end:
            where.append("DATE(sr.created_at) <= ?"); params.append(end)
        w = " AND ".join(where)
        records = db.execute(
            f"SELECT sr.id, sr.created_at, sr.quantity, sr.reason, "
            f"o.order_no, o.product_name, p.name as process_name, u.name as worker_name "
            f"FROM scrap_records sr "
            f"JOIN orders o ON sr.order_id=o.id "
            f"JOIN processes p ON sr.process_id=p.id "
            f"JOIN users u ON sr.user_id=u.id "
            f"WHERE {w} ORDER BY sr.created_at DESC LIMIT 500", params
        ).fetchall()
        return [dict(r) for r in records]

    @staticmethod
    def get_order_progress():
        db = BaseService.db()
        orders = db.execute(
            "SELECT o.id, o.order_no, o.product_name, "
            "COALESCE(c.name, o.customer) as customer, "
            "o.quantity, COALESCE(o.completed,0) as completed, o.plan_end, o.status "
            "FROM orders o LEFT JOIN customers c ON o.customer_id=c.id "
            "WHERE o.deleted_at IS NULL AND o.status IN ('producing','pending') "
            "ORDER BY o.plan_end ASC, o.created_at DESC"
        ).fetchall()
        return [dict(o) for o in orders]


    @staticmethod
    def get_worker_stats(sort_by="quantity", sort_dir="desc", start="", end=""):
        db = BaseService.db()
        allowed = {"quantity": "total_quantity", "name": "worker_name",
                   "scrap": "total_scrap", "rework": "total_rework"}
        col = allowed.get(sort_by, "total_quantity")
        direction = "DESC" if sort_dir == "desc" else "ASC"
        where_parts = ["wr.status = 'approved'"]
        params = []
        if start:
            where_parts.append("DATE(wr.created_at) >= ?"); params.append(start)
        if end:
            where_parts.append("DATE(wr.created_at) <= ?"); params.append(end)
        where_clause = " AND ".join(where_parts)
        workers = db.execute(
            f"SELECT u.name as worker_name, u.employee_no, COUNT(wr.id) as record_count, "
            f"COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as total_quantity, "
            f"COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as total_scrap, "
            f"COALESCE(SUM(CASE WHEN wr.type='rework' THEN wr.quantity ELSE 0 END),0) as total_rework "
            f"FROM work_records wr JOIN users u ON wr.user_id=u.id "
            f"WHERE {where_clause} "
            f"GROUP BY u.name ORDER BY {col} {direction} LIMIT 50", params
        ).fetchall()
        return [dict(r) for r in workers]
