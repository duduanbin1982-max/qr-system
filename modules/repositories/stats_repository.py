"""qr-system - StatsRepository

All SQL for stats: daily records, scrap records, order progress, worker stats.
"""
from modules.services import BaseService


class StatsRepository:
    """Stats data access."""

    # ============================================================
    # Shared WHERE builders
    # ============================================================
    @staticmethod
    def _daily_where(date, product_code):
        where_parts = [
            "wr.status='approved'",
            "DATE(wr.created_at)=?",
            "o.deleted_at IS NULL",
            "o.status != 'cancelled'"
        ]
        params = [date]
        if product_code:
            where_parts.append("o.product_code = ?")
            params.append(product_code)
        return " AND ".join(where_parts), params

    @staticmethod
    def _scrap_where(start, end, product_code):
        where_parts = ["o.deleted_at IS NULL", "o.status != 'cancelled'"]
        params = []
        if start:
            where_parts.append("DATE(sr.created_at) >= ?")
            params.append(start)
        if end:
            where_parts.append("DATE(sr.created_at) <= ?")
            params.append(end)
        if product_code:
            where_parts.append("o.product_code = ?")
            params.append(product_code)
        return " AND ".join(where_parts), params

    @staticmethod
    def _order_progress_where(start, end, product_code):
        where_parts = ["o.deleted_at IS NULL", "o.status IN ('producing','pending','paused')"]
        params = []
        if start:
            where_parts.append("DATE(o.created_at) >= ?")
            params.append(start)
        if end:
            where_parts.append("DATE(o.created_at) <= ?")
            params.append(end)
        if product_code:
            where_parts.append("o.product_code = ?")
            params.append(product_code)
        return " AND ".join(where_parts), params

    @staticmethod
    def _worker_where(start, end, product_code):
        where_parts = ["wr.status = 'approved'", "o.deleted_at IS NULL", "o.status != 'cancelled'"]
        params = []
        if start:
            where_parts.append("DATE(wr.created_at) >= ?")
            params.append(start)
        if end:
            where_parts.append("DATE(wr.created_at) <= ?")
            params.append(end)
        if product_code:
            where_parts.append("o.product_code = ?")
            params.append(product_code)
        return " AND ".join(where_parts), params

    # ============================================================
    # Daily Records
    # ============================================================
    @staticmethod
    def get_daily_records(date, product_code, limit, offset, db=None):
        db = db or BaseService.db()
        where_clause, params = StatsRepository._daily_where(date, product_code)
        rows = db.execute(
            "SELECT wr.id, wr.created_at, wr.quantity, wr.type, wr.status, "
            "o.order_no, o.product_name, p.name as process_name, p.id as process_id, "
            "u.id as user_id, u.name as worker_name, u.employee_no "
            "FROM work_records wr "
            "JOIN orders o ON wr.order_id=o.id "
            "JOIN processes p ON wr.process_id=p.id "
            "JOIN users u ON wr.user_id=u.id "
            "WHERE " + where_clause
            + " ORDER BY wr.created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset]
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_daily_summary(date, product_code, db=None):
        db = db or BaseService.db()
        where_clause, params = StatsRepository._daily_where(date, product_code)
        rows = db.execute(
            "SELECT p.id, p.name, COUNT(*) as record_count, "
            "COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as total_output, "
            "COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as total_scrap, "
            "COALESCE(SUM(CASE WHEN wr.type='rework' THEN wr.quantity ELSE 0 END),0) as total_rework "
            "FROM work_records wr "
            "JOIN orders o ON wr.order_id=o.id "
            "JOIN processes p ON wr.process_id=p.id "
            "JOIN users u ON wr.user_id=u.id "
            "WHERE " + where_clause
            + " GROUP BY p.id ORDER BY record_count DESC",
            params
        ).fetchall()
        return [dict(s) for s in rows]

    @staticmethod
    def get_daily_count(date, product_code, db=None):
        db = db or BaseService.db()
        where_clause, params = StatsRepository._daily_where(date, product_code)
        return db.execute(
            "SELECT COUNT(*) FROM work_records wr "
            "JOIN orders o ON wr.order_id=o.id "
            "WHERE " + where_clause,
            params
        ).fetchone()[0]

    # ============================================================
    # Scrap Records
    # ============================================================
    @staticmethod
    def get_scrap_records(start, end, product_code, db=None):
        db = db or BaseService.db()
        w, params = StatsRepository._scrap_where(start, end, product_code)
        rows = db.execute(
            "SELECT sr.id, sr.created_at, sr.quantity, sr.reason, "
            "o.order_no, o.product_name, p.name as process_name, "
            "u.id as user_id, u.name as worker_name, u.employee_no "
            "FROM scrap_records sr "
            "JOIN orders o ON sr.order_id=o.id "
            "JOIN processes p ON sr.process_id=p.id "
            "JOIN users u ON sr.user_id=u.id "
            "WHERE " + w + " ORDER BY sr.created_at DESC",
            params
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_scrap_summary(start, end, product_code, db=None):
        db = db or BaseService.db()
        w, params = StatsRepository._scrap_where(start, end, product_code)
        return dict(db.execute(
            "SELECT COUNT(*) as total_records, "
            "COALESCE(SUM(sr.quantity),0) as total_qty, "
            "COUNT(DISTINCT sr.process_id) as process_count "
            "FROM scrap_records sr JOIN orders o ON sr.order_id=o.id "
            "JOIN users u ON sr.user_id=u.id "
            "WHERE " + w,
            params
        ).fetchone())

    @staticmethod
    def get_scrap_by_process(start, end, product_code, db=None):
        db = db or BaseService.db()
        w, params = StatsRepository._scrap_where(start, end, product_code)
        rows = db.execute(
            "SELECT p.name, COUNT(*) as cnt, COALESCE(SUM(sr.quantity),0) as qty "
            "FROM scrap_records sr "
            "JOIN orders o ON sr.order_id=o.id "
            "JOIN processes p ON sr.process_id=p.id "
            "JOIN users u ON sr.user_id=u.id "
            "WHERE " + w + " GROUP BY p.id ORDER BY qty DESC LIMIT 10",
            params
        ).fetchall()
        return [dict(r) for r in rows]

    # ============================================================
    # Order Progress
    # ============================================================
    @staticmethod
    def get_order_progress(start, end, product_code, db=None):
        db = db or BaseService.db()
        w, params = StatsRepository._order_progress_where(start, end, product_code)
        rows = db.execute(
            "SELECT o.id, o.order_no, o.product_name, "
            "COALESCE(c.name, o.customer) as customer, "
            "o.quantity, "
            "COALESCE((SELECT COUNT(*) FROM product_items pi WHERE pi.order_id=o.id AND pi.status IN ('completed','scrapped')),0) as completed, "
            "o.plan_end, o.status "
            "FROM orders o LEFT JOIN customers c ON o.customer_id=c.id "
            "WHERE " + w + " "
            "ORDER BY o.plan_end ASC, o.created_at DESC",
            params
        ).fetchall()
        return [dict(o) for o in rows]

    # ============================================================
    # Worker Stats
    # ============================================================
    @staticmethod
    def get_worker_stats(sort_by, sort_dir, start, end, product_code, db=None):
        db = db or BaseService.db()
        allowed = {"quantity": "total_output", "name": "name", "scrap": "total_scrap", "rework": "total_rework"}
        col = allowed.get(sort_by, "total_output")
        direction = "DESC" if sort_dir == "desc" else "ASC"
        where_clause, params = StatsRepository._worker_where(start, end, product_code)
        # Worker filter removed - admins cannot scan work per mobile module
        rows = db.execute(
            "SELECT u.id as id, u.name as name, u.employee_no, "
            "COUNT(DISTINCT DATE(wr.created_at)) as work_days, "
            "COUNT(wr.id) as record_count, "
            "COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as total_output, "
            "COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as total_scrap, "
            "COALESCE(SUM(CASE WHEN wr.type='rework' THEN wr.quantity ELSE 0 END),0) as total_rework "
            "FROM work_records wr "
            "JOIN users u ON wr.user_id=u.id "
            "JOIN orders o ON wr.order_id=o.id "
            "WHERE " + where_clause + " "
            "GROUP BY u.id ORDER BY " + col + " " + direction + " LIMIT 500",
            params
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_worker_detail(user_id, start, end, db=None):
        db = db or BaseService.db()
        where = ["wr.user_id=?", "wr.status = 'approved'", "o.deleted_at IS NULL", "o.status != 'cancelled'"]
        params = [user_id]
        if start:
            where.append('DATE(wr.created_at) >= ?')
            params.append(start)
        if end:
            where.append('DATE(wr.created_at) <= ?')
            params.append(end)
        w = ' AND '.join(where)
        rows = db.execute(
            "SELECT o.product_name, "
            "pr.model AS model, pr.spec AS spec, "
            "p.name AS process_name, "
            "SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END) AS output, "
            "SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END) AS scrap "
            "FROM work_records wr "
            "JOIN orders o ON wr.order_id=o.id "
            "LEFT JOIN products pr ON o.product_code=pr.product_code AND pr.deleted_at IS NULL "
            "JOIN processes p ON wr.process_id=p.id "
            "WHERE " + w + " GROUP BY o.product_name, pr.model, pr.spec, p.id "
            "ORDER BY o.product_name, pr.model, p.name",
            params
        ).fetchall()
        return [dict(r) for r in rows]
