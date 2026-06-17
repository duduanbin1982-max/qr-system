"""qr-system — StatsService"""
from modules.services import BaseService


class StatsService:
    @staticmethod
    def get_daily_records(date, product_code=""):
        db = BaseService.db()
        where_parts = ["wr.status='approved'", "DATE(wr.created_at)=?",
                       "o.deleted_at IS NULL", "o.status != 'cancelled'"]
        where_params = [date]
        if product_code:
            where_parts.append("o.product_code = ?")
            where_params.append(product_code)
        where_clause = " AND ".join(where_parts)
        # Worker role filter: only count workers
        worker_filter = ("u.id IN (SELECT ur.user_id FROM user_roles ur "
                         "JOIN roles r ON ur.role_id=r.id WHERE r.code='worker')")
        records = db.execute(
            "SELECT wr.id, wr.created_at, wr.quantity, wr.type, wr.status, "
            "o.order_no, o.product_name, p.name as process_name, p.id as process_id, "
            "u.id as user_id, u.name as worker_name, u.employee_no "
            "FROM work_records wr "
            "JOIN orders o ON wr.order_id=o.id "
            "JOIN processes p ON wr.process_id=p.id "
            "JOIN users u ON wr.user_id=u.id "
            "WHERE " + where_clause + " AND " + worker_filter
            + " ORDER BY wr.created_at DESC LIMIT 1000", where_params
        ).fetchall()
        summary = db.execute(
            "SELECT p.id, p.name, COUNT(*) as record_count, "
            "COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as total_output, "
            "COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as total_scrap, "
            "COALESCE(SUM(CASE WHEN wr.type='rework' THEN wr.quantity ELSE 0 END),0) as total_rework "
            "FROM work_records wr "
            "JOIN orders o ON wr.order_id=o.id "
            "JOIN processes p ON wr.process_id=p.id "
            "JOIN users u ON wr.user_id=u.id "
            "WHERE " + where_clause + " AND " + worker_filter
            + " GROUP BY p.id ORDER BY record_count DESC", where_params
        ).fetchall()
        return {
            "records": [dict(r) for r in records],
            "summary": [dict(s) for s in summary],
        }

    @staticmethod
    def get_scrap_records(start="", end="", product_code=""):
        db = BaseService.db()
        where_parts = ["o.deleted_at IS NULL", "o.status != 'cancelled'"]
        params = []
        if start:
            where_parts.append("DATE(sr.created_at) >= ?"); params.append(start)
        if end:
            where_parts.append("DATE(sr.created_at) <= ?"); params.append(end)
        if product_code:
            where_parts.append("o.product_code = ?"); params.append(product_code)
        w = " AND ".join(where_parts)
        records = db.execute(
            f"SELECT sr.id, sr.created_at, sr.quantity, sr.reason, "
            f"o.order_no, o.product_name, p.name as process_name, u.id as user_id, u.name as worker_name, u.employee_no "
            f"FROM scrap_records sr "
            f"JOIN orders o ON sr.order_id=o.id "
            f"JOIN processes p ON sr.process_id=p.id "
            f"JOIN users u ON sr.user_id=u.id "
            f"WHERE {w} ORDER BY sr.created_at DESC LIMIT 500", params
        ).fetchall()
        # Summary
        summary = db.execute(
            f"SELECT COUNT(*) as total_records, COALESCE(SUM(sr.quantity),0) as total_qty, COUNT(DISTINCT sr.process_id) as process_count "
            f"FROM scrap_records sr JOIN orders o ON sr.order_id=o.id "
            f"JOIN users u ON sr.user_id=u.id "
            f"WHERE {w}", params
        ).fetchone()
        # By process ranking
        by_process = db.execute(
            f"SELECT p.name, COUNT(*) as cnt, COALESCE(SUM(sr.quantity),0) as qty "
            f"FROM scrap_records sr "
            f"JOIN orders o ON sr.order_id=o.id "
            f"JOIN processes p ON sr.process_id=p.id "
            f"JOIN users u ON sr.user_id=u.id "
            f"WHERE {w} GROUP BY p.id ORDER BY qty DESC LIMIT 10", params
        ).fetchall()
        return {
            "records": [dict(r) for r in records],
            "summary": dict(summary) if summary else {},
            "by_process": [dict(r) for r in by_process],
        }

    @staticmethod
    def get_order_progress(start="", end="", product_code=""):
        db = BaseService.db()
        where_parts = ["o.deleted_at IS NULL", "o.status IN ('producing','pending','paused')"]
        params = []
        if start:
            where_parts.append("DATE(o.created_at) >= ?"); params.append(start)
        if end:
            where_parts.append("DATE(o.created_at) <= ?"); params.append(end)
        if product_code:
            where_parts.append("o.product_code = ?"); params.append(product_code)
        w = " AND ".join(where_parts)
        orders = db.execute(
            "SELECT o.id, o.order_no, o.product_name, "
            "COALESCE(c.name, o.customer) as customer, "
            "o.quantity, "
            "COALESCE((SELECT COUNT(*) FROM product_items pi WHERE pi.order_id=o.id AND pi.status IN ('completed','scrapped')),0) as completed, "
            "o.plan_end, o.status "
            "FROM orders o LEFT JOIN customers c ON o.customer_id=c.id "
            f"WHERE {w} "
            "ORDER BY o.plan_end ASC, o.created_at DESC", params
        ).fetchall()
        return [dict(o) for o in orders]

    @staticmethod
    def get_worker_stats(sort_by="quantity", sort_dir="desc", start="", end="", product_code=""):
        db = BaseService.db()
        allowed = {"quantity": "total_output", "name": "name",
                   "scrap": "total_scrap", "rework": "total_rework"}
        col = allowed.get(sort_by, "total_output")
        direction = "DESC" if sort_dir == "desc" else "ASC"
        where_parts = ["wr.status = 'approved'", "o.deleted_at IS NULL",
                       "o.status != 'cancelled'"]
        params = []
        if start:
            where_parts.append("DATE(wr.created_at) >= ?"); params.append(start)
        if end:
            where_parts.append("DATE(wr.created_at) <= ?"); params.append(end)
        if product_code:
            where_parts.append("o.product_code = ?"); params.append(product_code)
        where_clause = " AND ".join(where_parts)
        # Worker role filter: only count users with worker role
        worker_filter = ("u.id IN (SELECT ur.user_id FROM user_roles ur "
                         "JOIN roles r ON ur.role_id=r.id WHERE r.code='worker')")
        workers = db.execute(
            f"SELECT u.id as id, u.name as name, u.employee_no, "
            f"COUNT(DISTINCT DATE(wr.created_at)) as work_days, "
            f"COUNT(wr.id) as record_count, "
            f"COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as total_output, "
            f"COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as total_scrap, "
            f"COALESCE(SUM(CASE WHEN wr.type='rework' THEN wr.quantity ELSE 0 END),0) as total_rework "
            f"FROM work_records wr "
            f"JOIN users u ON wr.user_id=u.id "
            f"JOIN orders o ON wr.order_id=o.id "
            f"WHERE {where_clause} AND {worker_filter} "
            f"GROUP BY u.id ORDER BY {col} {direction} LIMIT 100", params
        ).fetchall()
        return [dict(r) for r in workers]

    @staticmethod
    def get_worker_detail(user_id, start='', end=''):
        db = BaseService.db()
        where = ["wr.user_id=?", "wr.status = 'approved'",
                 "o.deleted_at IS NULL", "o.status != 'cancelled'"]
        params = [user_id]
        if start:
            where.append('DATE(wr.created_at) >= ?'); params.append(start)
        if end:
            where.append('DATE(wr.created_at) <= ?'); params.append(end)
        w = ' AND '.join(where)
        rows = db.execute(
            "SELECT o.product_name, "
            "pr.model AS model, pr.spec AS spec, "
            "p.name AS process_name, "
            "SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END) AS output, "
            "SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END) AS scrap "
            'FROM work_records wr '
            'JOIN orders o ON wr.order_id=o.id '
            'LEFT JOIN products pr ON o.product_code=pr.product_code '
            'JOIN processes p ON wr.process_id=p.id '
            'WHERE ' + w + ' GROUP BY o.product_name, pr.model, pr.spec, p.id '
            'ORDER BY o.product_name, pr.model, p.name',
            params
        ).fetchall()
        return [dict(r) for r in rows]
