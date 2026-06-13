"""qr-system \u2014 ReportsService (refactored)"""
from modules.services import BaseService

_ACTIVE_ORDERS = "wr.order_id IN (SELECT id FROM orders WHERE deleted_at IS NULL)"
_WORKER_ROLE = (
    "u.id IN (SELECT ur.user_id FROM user_roles ur "
    "JOIN roles r ON ur.role_id=r.id WHERE r.code='worker')"
)
# SECURITY: All $where variables are built from trusted string constants only.


def _build_date_filter(start, end, prefix="wr"):
    where = []
    params = []
    if start:
        where.append(f"DATE({prefix}.created_at) >= ?")
        params.append(start)
    if end:
        where.append(f"DATE({prefix}.created_at) <= ?")
        params.append(end)
    return " AND ".join(where) if where else "", params


def _calc_defect_rate(items):
    result = []
    for r in items:
        d = dict(r)
        total = (d.get("output") or 0) + (d.get("scrap") or 0) + (d.get("rework") or 0)
        d["defect_rate"] = round((d.get("scrap", 0) + d.get("rework", 0)) / total * 100, 1) if total else 0
        result.append(d)
    return result


class ReportsService:

    @staticmethod
    def production_trend(start_date, end_date):
        """Daily output = count of completed product_items (NOT work_records process count)."""
        db = BaseService.db()
        trend = db.execute(
            "SELECT dates.d as date, "
            # FIXED: output = completed product items per day (not process-level work records)
            "COALESCE(COUNT(DISTINCT pi.id),0) as output, "
            "COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as scrap, "
            "COALESCE(SUM(CASE WHEN wr.type='rework' THEN wr.quantity ELSE 0 END),0) as rework, "
            "COUNT(wr.id) as report_count "
            "FROM (WITH RECURSIVE dates(d) AS (SELECT ? UNION ALL SELECT date(d,'+1 day') FROM dates WHERE d<?) SELECT d FROM dates) dates "
            "LEFT JOIN product_items pi ON DATE(pi.completed_at)=dates.d AND pi.status='completed' "
            "LEFT JOIN work_records wr ON DATE(wr.created_at)=dates.d "
            f"AND {_ACTIVE_ORDERS} "
            "GROUP BY dates.d ORDER BY dates.d ASC",
            (start_date, end_date)
        ).fetchall()
        return [dict(r) for r in trend]

    @staticmethod
    def worker_efficiency(start="", end=""):
        db = BaseService.db()
        date_w, date_p = _build_date_filter(start, end)
        where = [_ACTIVE_ORDERS]
        params = list(date_p)
        if date_w:
            where.append(date_w)
        w = " AND ".join(where)
        workers = db.execute(
            f"SELECT u.id, u.name, u.employee_no, "
            f"COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as output, "
            f"COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as scrap, "
            f"COALESCE(SUM(CASE WHEN wr.type='rework' THEN wr.quantity ELSE 0 END),0) as rework, "
            f"COUNT(DISTINCT DATE(wr.created_at)) as work_days, COUNT(wr.id) as report_count "
            f"FROM users u LEFT JOIN work_records wr ON wr.user_id=u.id AND {w} "
            f"WHERE {_WORKER_ROLE} AND u.status='active' "
            f"GROUP BY u.id ORDER BY output DESC",
            params
        ).fetchall()
        result = []
        for w in workers:
            d = dict(w)
            d["daily_avg"] = round(d["output"] / d["work_days"], 1) if d["work_days"] else 0
            d["scrap_rate"] = round(d["scrap"] / d["output"] * 100, 1) if d["output"] else 0
            d["rework_rate"] = round(d["rework"] / d["output"] * 100, 1) if d["output"] else 0
            result.append(d)
        return result

    @staticmethod
    def quality_analysis(start="", end=""):
        db = BaseService.db()
        date_w, date_p = _build_date_filter(start, end)
        where = [_ACTIVE_ORDERS]
        params = list(date_p)
        if date_w:
            where.append(date_w)
        w = " AND ".join(where)
        by_process = db.execute(
            f"SELECT p.id, p.name, p.category, "
            f"COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as output, "
            f"COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as scrap, "
            f"COALESCE(SUM(CASE WHEN wr.type='rework' THEN wr.quantity ELSE 0 END),0) as rework "
            f"FROM processes p JOIN work_records wr ON wr.process_id=p.id "
            f"WHERE {w} GROUP BY p.id ORDER BY output DESC LIMIT 20",
            params
        ).fetchall()
        by_worker = db.execute(
            f"SELECT u.id, u.name, u.employee_no, "
            f"COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as output, "
            f"COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as scrap, "
            f"COALESCE(SUM(CASE WHEN wr.type='rework' THEN wr.quantity ELSE 0 END),0) as rework "
            f"FROM users u LEFT JOIN work_records wr ON wr.user_id=u.id AND {w} "
            f"WHERE {_WORKER_ROLE} AND u.status='active' "
            f"GROUP BY u.id ORDER BY output DESC LIMIT 20",
            params
        ).fetchall()
        return {"by_process": _calc_defect_rate(by_process), "by_worker": _calc_defect_rate(by_worker)}

    @staticmethod
    def order_analysis():
        db = BaseService.db()
        status_dist = db.execute(
            "SELECT o.status, COUNT(*) as count, COALESCE(SUM(o.quantity),0) as qty, "
            "COALESCE(SUM(o.completed),0) as done FROM orders o WHERE o.deleted_at IS NULL "
            "GROUP BY o.status ORDER BY COUNT(*) DESC"
        ).fetchall()
        monthly = db.execute(
            "SELECT substr(o.created_at,1,7) as month, COUNT(*) as count, "
            "COALESCE(SUM(o.quantity),0) as total_qty, COALESCE(SUM(o.completed),0) as total_done "
            "FROM orders o WHERE o.deleted_at IS NULL AND o.created_at>=date('now','-12 months') "
            "GROUP BY substr(o.created_at,1,7) ORDER BY month ASC"
        ).fetchall()
        return {
            "status_distribution": [dict(r) for r in status_dist],
            "monthly_trend": [dict(r) for r in monthly],
        }

    @staticmethod
    def product_stats(start="", end=""):
        db = BaseService.db()
        date_w, date_p = _build_date_filter(start, end)
        where = ["o.deleted_at IS NULL"]
        params = list(date_p)
        if date_w:
            where.append(date_w)
        w = " AND ".join(where)
        by_product = db.execute(
            f"SELECT p.id, p.product_name, p.product_code, p.model, p.spec, p.category, "
            f"COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as output, "
            f"COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as scrap, "
            f"COALESCE(SUM(CASE WHEN wr.type='rework' THEN wr.quantity ELSE 0 END),0) as rework, "
            f"COUNT(DISTINCT wr.order_id) as order_count "
            f"FROM products p "
            f"LEFT JOIN orders o ON o.product_code=p.product_code AND o.deleted_at IS NULL "
            f"LEFT JOIN work_records wr ON wr.order_id=o.id "
            f"WHERE {w} GROUP BY p.id ORDER BY output DESC LIMIT 30",
            params
        ).fetchall()
        summary = db.execute(
            f"SELECT COUNT(DISTINCT p.id) as product_count, "
            f"COUNT(DISTINCT o.id) as order_count, "
            f"COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as total_output "
            f"FROM products p "
            f"LEFT JOIN orders o ON o.product_code=p.product_code AND o.deleted_at IS NULL "
            f"LEFT JOIN work_records wr ON wr.order_id=o.id "
            f"WHERE {w}",
            params
        ).fetchone()
        return {
            "by_product": [dict(r) for r in by_product],
            "summary": dict(summary) if summary else {},
        }

    @staticmethod
    def material_usage(start="", end=""):
        db = BaseService.db()
        date_w, date_p = _build_date_filter(start, end, prefix="mc")
        where = ["1=1"]
        params = list(date_p)
        if date_w:
            where.append(date_w)
        w = " AND ".join(where)
        by_material = db.execute(
            f"SELECT m.id, m.name, m.spec, m.material_type, m.unit, "
            f"m.quantity as stock_qty, m.safe_stock, "
            f"COALESCE(SUM(mc.quantity),0) as total_used, "
            f"COUNT(DISTINCT mc.order_id) as order_count "
            f"FROM materials m "
            f"LEFT JOIN material_consumptions mc ON mc.material_id=m.id AND {w} "
            f"GROUP BY m.id ORDER BY total_used DESC LIMIT 30",
            params
        ).fetchall()
        summary = db.execute(
            "SELECT COUNT(*) as material_count, "
            "COALESCE(SUM(mc.quantity),0) as total_consumed "
            "FROM materials m "
            "LEFT JOIN material_consumptions mc ON mc.material_id=m.id"
        ).fetchone()
        return {
            "by_material": [dict(r) for r in by_material],
            "summary": dict(summary) if summary else {},
        }

    @staticmethod
    def shipment_stats(start="", end=""):
        db = BaseService.db()
        date_w, date_p = _build_date_filter(start, end, prefix="s")
        where = ["1=1"]
        params = list(date_p)
        if date_w:
            where.append(date_w)
        w = " AND ".join(where)
        by_status = db.execute(
            f"SELECT s.status, COUNT(*) as count, COALESCE(SUM(s.total_quantity),0) as total_qty "
            f"FROM shipments s WHERE {w} GROUP BY s.status ORDER BY count DESC"
        ).fetchall()
        by_customer = db.execute(
            f"SELECT s.customer, COUNT(*) as shipment_count, "
            f"COALESCE(SUM(s.total_quantity),0) as total_qty "
            f"FROM shipments s WHERE {w} "
            f"GROUP BY s.customer ORDER BY total_qty DESC LIMIT 20"
        ).fetchall()
        monthly = db.execute(
            f"SELECT substr(s.created_at,1,7) as month, COUNT(*) as count, "
            f"COALESCE(SUM(s.total_quantity),0) as total_qty "
            f"FROM shipments s WHERE {w} AND s.created_at>=date('now','-12 months') "
            f"GROUP BY substr(s.created_at,1,7) ORDER BY month ASC"
        ).fetchall()
        return {
            "by_status": [dict(r) for r in by_status],
            "by_customer": [dict(r) for r in by_customer],
            "monthly_trend": [dict(r) for r in monthly],
        }

    @staticmethod
    def dashboard_kpi():
        db = BaseService.db()
        return {
            "active_orders": ReportsService._kpi_active_orders(db),
            "completed_month": ReportsService._kpi_completed_month(db),
            "output_month": ReportsService._kpi_output_month(db),
            "scrap_rate": ReportsService._kpi_scrap_rate(db),
            "active_workers_today": ReportsService._kpi_active_workers(db),
            "pending_shipments": ReportsService._kpi_pending_shipments(db),
            "low_stock_count": ReportsService._kpi_low_stock(db),
            "weekly_trend": ReportsService._kpi_weekly_trend(db),
        }

    @staticmethod
    def _kpi_active_orders(db):
        return db.execute(
            "SELECT COUNT(*) FROM orders WHERE deleted_at IS NULL "
            "AND status IN ('pending','producing','paused')"
        ).fetchone()[0]

    @staticmethod
    def _kpi_completed_month(db):
        return db.execute(
            "SELECT COUNT(*) FROM orders WHERE deleted_at IS NULL "
            "AND status='completed' AND substr(updated_at,1,7)=strftime('%Y-%m','now')"
        ).fetchone()[0]

    @staticmethod
    def _kpi_output_month(db):
        # FIXED: use product_items completed count instead of work_records
        return db.execute(
            "SELECT COUNT(*) FROM product_items pi "
            "JOIN orders o ON pi.order_id=o.id "
            "WHERE pi.status='completed' AND o.deleted_at IS NULL "
            "AND substr(pi.completed_at,1,7)=strftime('%Y-%m','now')"
        ).fetchone()[0] or 0

    @staticmethod
    def _kpi_scrap_rate(db):
        total = db.execute(
            "SELECT COUNT(*) FROM product_items pi "
            "JOIN orders o ON pi.order_id=o.id "
            "WHERE pi.status IN ('completed','scrapped') AND o.deleted_at IS NULL "
            "AND substr(pi.completed_at,1,7)=strftime('%Y-%m','now')"
        ).fetchone()[0] or 0
        scrap = db.execute(
            "SELECT COUNT(*) FROM scrap_records sr "
            "JOIN orders o ON sr.order_id=o.id "
            "WHERE o.deleted_at IS NULL "
            "AND substr(sr.created_at,1,7)=strftime('%Y-%m','now')"
        ).fetchone()[0] or 0
        return round(scrap / total * 100, 1) if total else 0

    @staticmethod
    def _kpi_active_workers(db):
        return db.execute(
            f"SELECT COUNT(DISTINCT wr.user_id) FROM work_records wr "
            f"JOIN orders o ON wr.order_id=o.id "
            f"WHERE o.deleted_at IS NULL AND DATE(wr.created_at)=date('now')"
        ).fetchone()[0] or 0

    @staticmethod
    def _kpi_pending_shipments(db):
        return db.execute("SELECT COUNT(*) FROM shipments WHERE status='pending'").fetchone()[0] or 0

    @staticmethod
    def _kpi_low_stock(db):
        return db.execute(
            "SELECT COUNT(*) FROM materials WHERE safe_stock > 0 AND quantity <= safe_stock"
        ).fetchone()[0] or 0

    @staticmethod
    def _kpi_weekly_trend(db):
        # FIXED: weekly output = completed product items per day
        weekly = db.execute(
            "SELECT dates.d as date, "
            "COALESCE(COUNT(DISTINCT pi.id),0) as output "
            "FROM (WITH RECURSIVE dates(d) AS (SELECT date('now','-6 days') UNION ALL SELECT date(d,'+1 day') FROM dates WHERE d<date('now')) SELECT d FROM dates) dates "
            "LEFT JOIN product_items pi ON DATE(pi.completed_at)=dates.d AND pi.status='completed' "
            "LEFT JOIN orders o ON pi.order_id=o.id AND o.deleted_at IS NULL "
            "GROUP BY dates.d ORDER BY dates.d ASC"
        ).fetchall()
        return [dict(r) for r in weekly]
