"""qr-system - StatsRepository

All SQL for stats: daily records, scrap records, order progress, worker stats.
"""
from modules.repositories.context import resolve_db
from modules.domain.reporting_day import reporting_day_bounds


class StatsRepository:
    """Stats data access."""

    # ============================================================
    # Shared WHERE builders
    # ============================================================
    @staticmethod
    def _append_product_filter(where_parts, params, product_code):
        if not product_code:
            return
        where_parts.append(
            "(o.product_code = ? OR "
            "COALESCE(o.product_id, ("
            "SELECT a.product_id FROM product_code_aliases a "
            "WHERE a.product_code = o.product_code"
            ")) = ("
            "SELECT selected.product_id FROM product_code_aliases selected "
            "WHERE selected.product_code = ?"
            "))"
        )
        params.extend([product_code, product_code])

    @staticmethod
    def _daily_where(date, product_code):
        period_start, period_end = reporting_day_bounds(date)
        where_parts = [
            "wr.status='approved'",
            "wr.created_at >= ?",
            "wr.created_at < ?",
            "o.deleted_at IS NULL",
            "o.status != 'cancelled'"
        ]
        params = [period_start, period_end]
        StatsRepository._append_product_filter(where_parts, params, product_code)
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
        StatsRepository._append_product_filter(where_parts, params, product_code)
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
        StatsRepository._append_product_filter(where_parts, params, product_code)
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
        StatsRepository._append_product_filter(where_parts, params, product_code)
        return " AND ".join(where_parts), params

    # ============================================================
    # Daily Records
    # ============================================================
    @staticmethod
    def get_daily_records(date, product_code, limit, offset, db=None):
        db = resolve_db(db)
        where_clause, params = StatsRepository._daily_where(date, product_code)
        rows = db.execute(
            "SELECT wr.id, wr.created_at, wr.quantity, wr.type, wr.status, wr.serial_no, wr.remark, "
            "wr.order_id, wr.process_id, "
            "o.order_no, o.qr_mode, o.customer, o.product_code, opl.product_id, "
            "CASE WHEN o.qr_mode = 'serial' AND COALESCE(wr.serial_no, '') != '' "
            "THEN wr.serial_no ELSE o.order_no END as display_order_no, "
            "COALESCE(NULLIF(o.product_name, ''), prod.product_name, '') as product_name, "
            "COALESCE(prod.model, '') as product_model, "
            "COALESCE(prod.spec, '') as product_spec, "
            "COALESCE(prod.category, '') as product_category, "
            "COALESCE(route.name, '') as route_name, "
            "p.name as process_name, p.id as process_id, "
            "u.id as user_id, u.name as worker_name, u.employee_no, COALESCE(u.group_name, '') as group_name, "
            "COALESCE(dept.name, '') as department_name, COALESCE(pos.name, '') as position_name, "
            "COALESCE((SELECT qi.result FROM quality_inspections qi "
            "WHERE qi.order_id=wr.order_id AND qi.process_id=wr.process_id "
            "ORDER BY qi.inspected_at DESC, qi.id DESC LIMIT 1), '') as quality_result, "
            "COALESCE((SELECT qi.score_total FROM quality_inspections qi "
            "WHERE qi.order_id=wr.order_id AND qi.process_id=wr.process_id "
            "ORDER BY qi.inspected_at DESC, qi.id DESC LIMIT 1), 0) as quality_score "
            "FROM work_records wr "
            "JOIN orders o ON wr.order_id=o.id "
            "JOIN processes p ON wr.process_id=p.id "
            "JOIN users u ON wr.user_id=u.id "
            "LEFT JOIN order_product_links opl ON opl.order_id=o.id "
            "LEFT JOIN products prod ON prod.id=opl.product_id "
            "LEFT JOIN process_routes route ON route.id=o.route_id "
            "LEFT JOIN departments dept ON dept.id=u.department_id "
            "LEFT JOIN positions pos ON pos.id=u.position_id "
            "WHERE " + where_clause
            + " ORDER BY u.name COLLATE NOCASE ASC, u.employee_no ASC, wr.created_at ASC, wr.id ASC LIMIT ? OFFSET ?",
            params + [limit, offset]
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_daily_totals(date, product_code, db=None):
        db = resolve_db(db)
        where_clause, params = StatsRepository._daily_where(date, product_code)
        row = db.execute(
            "SELECT COUNT(*) as record_count, "
            "COALESCE(SUM(wr.quantity),0) as total_quantity, "
            "COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as normal_quantity, "
            "COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as scrap_quantity, "
            "COALESCE(SUM(CASE WHEN wr.type='rework' THEN wr.quantity ELSE 0 END),0) as rework_quantity, "
            "COUNT(DISTINCT wr.user_id) as worker_count, "
            "COUNT(DISTINCT wr.order_id) as order_count, "
            "COUNT(DISTINCT COALESCE(CAST(opl.product_id AS TEXT), NULLIF(o.product_code, ''), o.product_name)) as product_count "
            "FROM work_records wr "
            "JOIN orders o ON wr.order_id=o.id "
            "LEFT JOIN order_product_links opl ON opl.order_id=o.id "
            "WHERE " + where_clause,
            params
        ).fetchone()
        return dict(row) if row else {}

    @staticmethod
    def get_daily_summary(date, product_code, db=None):
        db = resolve_db(db)
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
        db = resolve_db(db)
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
        db = resolve_db(db)
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
        db = resolve_db(db)
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
        db = resolve_db(db)
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
        db = resolve_db(db)
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
        db = resolve_db(db)
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
        db = resolve_db(db)
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
            "LEFT JOIN order_product_links opl ON opl.order_id=o.id "
            "LEFT JOIN products pr ON pr.id=opl.product_id AND pr.deleted_at IS NULL "
            "JOIN processes p ON wr.process_id=p.id "
            "WHERE " + w + " GROUP BY o.product_name, pr.model, pr.spec, p.id "
            "ORDER BY o.product_name, pr.model, p.name",
            params
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def get_material_detail(material_id, start='', end='', db=None):
        db = resolve_db(db)
        where = ["mc.material_id = ?"]
        params = [material_id]
        if start:
            where.append("DATE(mc.created_at) >= ?")
            params.append(start)
        if end:
            where.append("DATE(mc.created_at) <= ?")
            params.append(end)
        w = " AND ".join(where)
        rows = db.execute(
            "SELECT mc.id, mc.quantity, mc.created_at, o.order_no, o.product_name, "
            "p.name as process_name FROM material_consumptions mc "
            "LEFT JOIN orders o ON mc.order_id = o.id "
            "LEFT JOIN processes p ON mc.process_id = p.id "
            "WHERE " + w + " ORDER BY mc.created_at DESC LIMIT 200",
            params
        ).fetchall()
        return [dict(r) for r in rows]
