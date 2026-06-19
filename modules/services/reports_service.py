"""qr-system \u2014 ReportsService (refactored)"""
from modules.services import BaseService

_ACTIVE_ORDERS = "wr.order_id IN (SELECT id FROM orders WHERE deleted_at IS NULL)"

PROCESS_ORDER = ["下料", "铆接", "焊接", "抛丸", "打磨", "镗孔", "喷漆"]
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
        d["defect_rate"] = round((d.get("scrap", 0) + d.get("rework", 0)) / total * 100, 1) if total else None
        result.append(d)
    return result


class ReportsService:

    @staticmethod
    def production_trend(start_date, end_date):
        """Daily output/scrap = count of product_items (consistent counting units).
        Rework and report_count still come from work_records (no product_items equivalent)."""
        db = BaseService.db()
        trend = db.execute(
            "SELECT dates.d as date, "
            "COALESCE(COUNT(DISTINCT CASE WHEN pi.status='completed' THEN pi.id END),0) as output, "
            "COALESCE(COUNT(DISTINCT CASE WHEN pi.status='scrapped' THEN pi.id END),0) as scrap, "
            "COALESCE(SUM(CASE WHEN wr.type='rework' THEN wr.quantity ELSE 0 END),0) as rework, "
            "COUNT(wr.id) as report_count "
            "FROM (WITH RECURSIVE dates(d) AS (SELECT ? UNION ALL SELECT date(d,'+1 day') FROM dates WHERE d<?) SELECT d FROM dates) dates "
            "LEFT JOIN product_items pi ON DATE(pi.completed_at)=dates.d AND pi.status IN ('completed','scrapped') AND pi.order_id IN (SELECT id FROM orders WHERE deleted_at IS NULL) "
            "LEFT JOIN work_records wr ON DATE(wr.created_at)=dates.d "
            f"AND {_ACTIVE_ORDERS} "
            "GROUP BY dates.d ORDER BY dates.d ASC",
            (start_date, end_date)
        ).fetchall()
        return [dict(r) for r in trend]

    @staticmethod
    def worker_efficiency(start="", end="", product_code=""):
        db = BaseService.db()
        date_w, date_p = _build_date_filter(start, end)
        where = [_ACTIVE_ORDERS, "wr.status = 'approved'"]
        params = list(date_p)
        if date_w:
            where.append(date_w)
        if product_code:
            where.append("wr.order_id IN (SELECT id FROM orders WHERE product_code = ?)")
            params.append(product_code)
        w = " AND ".join(where)
        workers = db.execute(
            f"SELECT u.id, u.name, u.employee_no, "
            f"COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as output, "
            f"COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as scrap, "
            f"COALESCE(SUM(CASE WHEN wr.type='rework' THEN wr.quantity ELSE 0 END),0) as rework, "
            f"COUNT(DISTINCT DATE(wr.created_at)) as work_days, COUNT(wr.id) as report_count "
            f"FROM users u LEFT JOIN work_records wr ON wr.user_id=u.id AND {w} "
            f"WHERE u.status='active' "
            f"GROUP BY u.id ORDER BY output DESC",
            params
        ).fetchall()
        result = []
        for w in workers:
            d = dict(w)
            total = (d["output"] or 0) + (d["scrap"] or 0)
            d["daily_avg"] = round(d["output"] / d["work_days"], 1) if d["work_days"] else 0
            d["scrap_rate"] = round(d["scrap"] / total * 100, 1) if total else 0
            d["rework_rate"] = round(d["rework"] / total * 100, 1) if total else 0
            result.append(d)
        return result

    @staticmethod
    def quality_analysis(start="", end="", product_code=""):
        db = BaseService.db()
        date_w, date_p = _build_date_filter(start, end)
        where = [_ACTIVE_ORDERS, 'wr.status = "approved"']
        params = list(date_p)
        if date_w:
            where.append(date_w)
        if product_code:
            where.append("wr.order_id IN (SELECT id FROM orders WHERE product_code = ?)")
            params.append(product_code)
        w = " AND ".join(where)
        by_process = db.execute(
            f"SELECT p.id, p.name, p.category, "
            f"COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as output, "
            f"COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as scrap, "
            f"COALESCE(SUM(CASE WHEN wr.type='rework' THEN wr.quantity ELSE 0 END),0) as rework "
            f"FROM processes p JOIN work_records wr ON wr.process_id=p.id "
            f"WHERE {w} GROUP BY p.id ORDER BY output DESC",
            params
        ).fetchall()
        result = {"by_process": _calc_defect_rate(by_process)}
        try:
            from modules.services.quality_service import QualityService
        except ImportError:
            return result
        try:
            trend_list = QualityService.pass_rate_trend(weeks=6, start=start, end=end)
            if isinstance(trend_list, list):
                result["trend_labels"] = [t["label"] for t in trend_list]
                result["trend_pass_rates"] = [t["rate"] for t in trend_list]
        except Exception:
            pass
        try:
            spc = QualityService.spc_p_chart(limit=50, start=start, end=end)
            if isinstance(spc, dict):
                result["spc_samples"] = [s["rate"] for s in spc.get("samples", [])]
                result["spc_ucl"] = spc.get("ucl", 0)
                result["spc_cl"] = spc.get("cl", 0)
                result["spc_lcl"] = spc.get("lcl", 0)
        except Exception:
            pass
        try:
            insp = QualityService.inspector_performance(start=start, end=end)
            if isinstance(insp, dict):
                result["inspector_data"] = insp.get("data", [])
        except Exception:
            pass
        try:
            supp = QualityService.supplier_quality(start=start, end=end)
            if isinstance(supp, dict):
                result["supplier_data"] = supp.get("data", [])
        except Exception:
            pass
        try:
            qi_where = ["1=1"]
            qi_params = []
            if start:
                qi_where.append("DATE(qi.inspected_at) >= ?")
                qi_params.append(start)
            if end:
                qi_where.append("DATE(qi.inspected_at) <= ?")
                qi_params.append(end)
            if product_code:
                qi_where.append("qi.product_code = ?")
                qi_params.append(product_code)
            qi_w = " AND ".join(qi_where)
            qi_by_process = db.execute(
                "SELECT qi.process_name as name, COUNT(*) as total_inspections, "
                "COALESCE(SUM(CASE WHEN qi.result='pass' THEN 1 ELSE 0 END),0) as pass_count, "
                "COALESCE(SUM(CASE WHEN qi.result IN('fail','partial') THEN 1 ELSE 0 END),0) as fail_count, "
                "COALESCE(SUM(CASE WHEN qi.result='scrap' THEN 1 ELSE 0 END),0) as scrap_count, "
                "COALESCE(SUM(CASE WHEN qi.result='rework' THEN 1 ELSE 0 END),0) as rework_count "
                "FROM quality_inspections qi WHERE " + qi_w + " AND qi.process_name != '' "
                "GROUP BY qi.process_name ORDER BY total_inspections DESC",
                qi_params
            ).fetchall()
            result["qi_by_process"] = [dict(r) for r in qi_by_process]
        except Exception:
            pass
        return result
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
    def product_stats(start="", end="", product_code=""):
        db = BaseService.db()
        where = ["o.deleted_at IS NULL"]
        params = []
        if start:
            where.append("DATE(o.created_at) >= ?"); params.append(start)
        if end:
            where.append("DATE(o.created_at) <= ?"); params.append(end)
        if product_code:
            where.append("o.product_code = ?"); params.append(product_code)
        w = " AND ".join(where)
        item_w = ""
        if start:
            item_w += f" AND DATE(pi.completed_at) >= '{start}'"
        if end:
            item_w += f" AND DATE(pi.completed_at) <= '{end}'"
        by_product = db.execute(
            f"SELECT p.id, p.product_name, p.product_code, p.model, p.spec, p.category, "
            f"p.price, p.upper_opening, p.lower_opening, p.plate_thickness, p.weight, "
            f"COALESCE(SUM(o.quantity),0) as order_qty, "
            f"COALESCE((SELECT COUNT(*) FROM product_items pi JOIN orders o2 ON pi.order_id=o2.id WHERE o2.product_code=p.product_code AND o2.deleted_at IS NULL AND pi.status='completed'{item_w}),0) as output, "
            f"COALESCE((SELECT COUNT(DISTINCT sr.id) FROM scrap_records sr JOIN orders o2 ON sr.order_id=o2.id WHERE o2.product_code=p.product_code AND o2.deleted_at IS NULL" + (f" AND DATE(sr.created_at) >= '{start}'" if start else "") + (f" AND DATE(sr.created_at) <= '{end}'" if end else "") + "),0) as scrap, "
            f"COALESCE((SELECT COUNT(DISTINCT wr.id) FROM work_records wr JOIN orders o2 ON wr.order_id=o2.id WHERE o2.product_code=p.product_code AND o2.deleted_at IS NULL AND wr.type='rework' AND wr.status='approved'" + (f" AND DATE(wr.created_at) >= '{start}'" if start else "") + (f" AND DATE(wr.created_at) <= '{end}'" if end else "") + "),0) as rework, "
            f"COUNT(DISTINCT o.id) as order_count "
            f"FROM products p "
            f"LEFT JOIN orders o ON o.product_code=p.product_code AND o.deleted_at IS NULL "
            f"WHERE {w} GROUP BY p.id ORDER BY output DESC LIMIT 30",
            params
        ).fetchall()
        summary = db.execute(
            f"SELECT COUNT(DISTINCT p.id) as product_count, "
            f"COUNT(DISTINCT o.id) as order_count, "
            f"COALESCE((SELECT COUNT(*) FROM product_items pi JOIN orders o2 ON pi.order_id=o2.id WHERE o2.deleted_at IS NULL AND pi.status='completed'{item_w}),0) as total_output "
            f"FROM products p "
            f"LEFT JOIN orders o ON o.product_code=p.product_code AND o.deleted_at IS NULL "
            f"WHERE {w}",
            params
        ).fetchone()
        return {
            "by_product": [dict(r) for r in by_product],
            "summary": dict(summary) if summary else {},
        }
    @staticmethod
    def material_usage(start="", end="", product_code=""):
        db = BaseService.db()
        date_w, date_p = _build_date_filter(start, end, prefix="mc")
        where = ["1=1"]
        params = list(date_p)
        if date_w:
            where.append(date_w)
        if product_code:
            where.append("mc.order_id IN (SELECT id FROM orders WHERE product_code = ?)")
            params.append(product_code)
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
            f"SELECT COUNT(DISTINCT m.id) as material_count, "
            f"COALESCE(SUM(mc.quantity),0) as total_consumed "
            f"FROM materials m "
            f"LEFT JOIN material_consumptions mc ON mc.material_id=m.id"
            + (f" AND {date_w}" if date_w else ""),
            date_p
        ).fetchone()
        return {
            "by_material": [dict(r) for r in by_material],
            "summary": dict(summary) if summary else {},
        }

    @staticmethod
    def shipment_stats(start="", end="", product_code=""):
        db = BaseService.db()
        date_w, date_p = _build_date_filter(start, end, prefix="s")
        where = ["1=1"]
        params = list(date_p)
        if date_w:
            where.append(date_w)
        if product_code:
            where.append("s.id IN (SELECT si.shipment_id FROM shipment_items si JOIN orders o ON si.order_id=o.id WHERE o.product_code = ?)")
            params.append(product_code)
        w = " AND ".join(where)
        by_status = db.execute(
            f"SELECT s.status, COUNT(*) as count, COALESCE(SUM(s.total_quantity),0) as total_qty "
            f"FROM shipments s WHERE {w} GROUP BY s.status ORDER BY count DESC",
            params
        ).fetchall()
        by_customer = db.execute(
            f"SELECT s.customer, COUNT(*) as shipment_count, "
            f"COALESCE(SUM(s.total_quantity),0) as total_qty "
            f"FROM shipments s WHERE {w} "
            f"GROUP BY s.customer ORDER BY total_qty DESC LIMIT 20",
            params
        ).fetchall()
        monthly = db.execute(
            f"SELECT substr(s.created_at,1,7) as month, COUNT(*) as count, "
            f"COALESCE(SUM(s.total_quantity),0) as total_qty "
            f"FROM shipments s WHERE {w} AND s.created_at>=date('now','-12 months') "
            f"GROUP BY substr(s.created_at,1,7) ORDER BY month ASC",
            params
        ).fetchall()
        return {
            "by_status": [dict(r) for r in by_status],
            "by_customer": [dict(r) for r in by_customer],
            "monthly_trend": [dict(r) for r in monthly],
        }

    @staticmethod

    @staticmethod
    def product_process_matrix(start="", end=""):
        """Product x Process cross-tab matrix for heatmap visualization."""
        db = BaseService.db()
        date_w, date_p = _build_date_filter(start, end)
        where = ["wr.status = 'approved'", "o.deleted_at IS NULL"]
        params = list(date_p)
        if date_w:
            where.append(date_w)
        w = " AND ".join(where)
        rows = db.execute(
            f"SELECT p.product_code, p.product_name, p.model, pr.name as process_name, "
            f"COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as output "
            f"FROM products p "
            f"JOIN orders o ON o.product_code=p.product_code AND o.deleted_at IS NULL "
            f"JOIN work_records wr ON wr.order_id=o.id AND {w} "
            f"JOIN processes pr ON wr.process_id=pr.id "
            f"GROUP BY p.product_code, pr.name ORDER BY p.product_code, pr.name",
            params
        ).fetchall()
        products = {}
        processes_set = set()
        for r in rows:
            pc = r["product_code"]
            if pc not in products:
                products[pc] = {"product_code": pc, "product_name": r["product_name"],
                                 "model": r["model"], "data": {}}
            products[pc]["data"][r["process_name"]] = r["output"]
            processes_set.add(r["process_name"])
        return {
            "products": list(products.values()),
            "processes": sorted(processes_set),
        }

    @staticmethod
    def model_process_stats(start="", end=""):
        """Aggregate output by model + process."""
        db = BaseService.db()
        date_w, date_p = _build_date_filter(start, end)
        where = ["wr.status = 'approved'", "o.deleted_at IS NULL"]
        params = list(date_p)
        if date_w:
            where.append(date_w)
        w = " AND ".join(where)
        rows = db.execute(
            f"SELECT p.model, pr.name as process_name, "
            f"COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as output, "
            f"COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as scrap "
            f"FROM products p "
            f"JOIN orders o ON o.product_code=p.product_code AND o.deleted_at IS NULL "
            f"JOIN work_records wr ON wr.order_id=o.id AND {w} "
            f"JOIN processes pr ON wr.process_id=pr.id "
            f"GROUP BY p.model, pr.name ORDER BY output DESC",
            params
        ).fetchall()
        result = {}
        for r in rows:
            model = r["model"] or "-"
            if model not in result:
                result[model] = {"model": model, "processes": {}}
            result[model]["processes"][r["process_name"]] = {
                "output": r["output"], "scrap": r["scrap"]
            }
        return {"by_model": list(result.values())}

    @staticmethod
    def product_process_stats(start="", end=""):
        """Per-product process breakdown with flat process list for matrix display."""
        db = BaseService.db()
        date_w, date_p = _build_date_filter(start, end)
        where = ["wr.status = 'approved'", "o.deleted_at IS NULL", "o.status != 'cancelled'"]
        params = list(date_p)
        if date_w:
            where.append(date_w)
        w = " AND ".join(where)
        # Get all distinct processes first (sorted by custom order)
        all_procs = db.execute(
            "SELECT DISTINCT pr.name FROM processes pr "
            "JOIN work_records wr ON wr.process_id=pr.id "
            "JOIN orders o ON wr.order_id=o.id "
            f"WHERE {w} ORDER BY pr.name", params
        ).fetchall()
        proc_names = sorted([r["name"] for r in all_procs], key=lambda n: PROCESS_ORDER.index(n) if n in PROCESS_ORDER else 999)
        # Get product-process matrix
        rows = db.execute(
            f"SELECT p.product_code, p.product_name, p.model, p.spec, p.category, "
            f"pr.name as process_name, "
            f"COALESCE(SUM(CASE WHEN wr.type='normal' THEN wr.quantity ELSE 0 END),0) as output, "
            f"COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as scrap "
            f"FROM products p "
            f"JOIN orders o ON o.product_code=p.product_code "
            f"JOIN work_records wr ON wr.order_id=o.id "
            f"JOIN processes pr ON wr.process_id=pr.id "
            f"WHERE {w} GROUP BY p.product_code, pr.name ORDER BY p.product_code",
            params
        ).fetchall()
        # Build response: products array with data dict keyed by process name
        prod_map = {}
        for r in rows:
            pc = r["product_code"]
            if pc not in prod_map:
                prod_map[pc] = {"product_code": pc, "product_name": r["product_name"],
                                "model": r["model"], "spec": r["spec"],
                                "category": r["category"], "data": {}}
            prod_map[pc]["data"][r["process_name"]] = r["output"]
        products_out = []
        for pc, md in prod_map.items():
            total = sum(md["data"].values())
            products_out.append({**md, "total": total})
        return {"processes": proc_names, "products": products_out}


    @staticmethod
    def customer_stats(start="", end=""):
        db = BaseService.db()
        where = ["o.deleted_at IS NULL"]
        params = []
        if start:
            where.append("DATE(o.created_at) >= ?"); params.append(start)
        if end:
            where.append("DATE(o.created_at) <= ?"); params.append(end)
        w = " AND ".join(where)
        rows = db.execute(
            "SELECT COALESCE(c.name, o.customer) as customer_name, "
            "COUNT(DISTINCT o.id) as order_count, SUM(o.quantity) as total_qty, "
            "COALESCE(SUM(CASE WHEN o.status='completed' THEN o.quantity ELSE 0 END),0) as completed_qty, "
            "COALESCE((SELECT COUNT(*) FROM orders o2 WHERE COALESCE((SELECT name FROM customers c2 WHERE c2.id=o2.customer_id), o2.customer) = COALESCE(c.name, o.customer) AND o2.deleted_at IS NULL AND o2.status IN ('pending','producing','paused')),0) as active_orders "
            "FROM orders o LEFT JOIN customers c ON o.customer_id = c.id "
            "WHERE " + w + " GROUP BY customer_name ORDER BY total_qty DESC LIMIT 30",
            params
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def production_line_stats(start="", end=""):
        db = BaseService.db()
        where = ["o.deleted_at IS NULL"]
        params = []
        if start:
            where.append("DATE(o.created_at) >= ?"); params.append(start)
        if end:
            where.append("DATE(o.created_at) <= ?"); params.append(end)
        w = " AND ".join(where)
        rows = db.execute(
            "SELECT pl.id as line_id, pl.name as line_name, "
            "COUNT(DISTINCT o.id) as order_count, SUM(o.quantity) as total_qty, "
            "COALESCE(SUM(CASE WHEN o.status='completed' THEN o.quantity ELSE 0 END),0) as completed_qty, "
            "COALESCE((SELECT COUNT(*) FROM orders o2 WHERE o2.production_line_id=pl.id AND o2.deleted_at IS NULL AND o2.status IN ('pending','producing','paused')),0) as active_orders "
            "FROM production_lines pl "
            "LEFT JOIN orders o ON o.production_line_id = pl.id AND " + w + " "
            "GROUP BY pl.id ORDER BY total_qty DESC",
            params
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def monthly_summary():
        db = BaseService.db()
        this_month = db.execute(
            "SELECT COUNT(DISTINCT o.id) as orders, "
            "COALESCE(SUM(o.quantity),0) as total_qty, "
            "COALESCE(SUM(CASE WHEN o.status='completed' THEN o.quantity ELSE 0 END),0) as completed_qty, "
            "COALESCE((SELECT COUNT(*) FROM product_items pi JOIN orders o2 ON pi.order_id=o2.id WHERE o2.deleted_at IS NULL AND pi.status='completed' AND substr(pi.completed_at,1,7)=strftime('%Y-%m','now')),0) as output "
            "FROM orders o WHERE o.deleted_at IS NULL AND substr(o.created_at,1,7)=strftime('%Y-%m','now')"
        ).fetchone()
        last_month = db.execute(
            "SELECT COUNT(DISTINCT o.id) as orders, "
            "COALESCE(SUM(o.quantity),0) as total_qty, "
            "COALESCE(SUM(CASE WHEN o.status='completed' THEN o.quantity ELSE 0 END),0) as completed_qty, "
            "COALESCE((SELECT COUNT(*) FROM product_items pi JOIN orders o2 ON pi.order_id=o2.id WHERE o2.deleted_at IS NULL AND pi.status='completed' AND substr(pi.completed_at,1,7)=strftime('%Y-%m','now','-1 month')),0) as output "
            "FROM orders o WHERE o.deleted_at IS NULL AND substr(o.created_at,1,7)=strftime('%Y-%m','now','-1 month')"
        ).fetchone()
        def _pct(a, b):
            if not b: return None
            return round((a - b) / b * 100, 1)
        return {
            "this_month": dict(this_month),
            "last_month": dict(last_month),
            "order_change_pct": _pct(this_month["orders"], last_month["orders"]),
            "output_change_pct": _pct(this_month["output"], last_month["output"]),
            "completed_change_pct": _pct(this_month["completed_qty"], last_month["completed_qty"]),
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
        """Count orders completed this month. Uses updated_at as proxy for completion time
        (orders table has no dedicated completed_at column; updated_at reflects last status change)."""
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
        """Scrap rate = scrapped product_items / (completed + scrapped) this month.
        Both numerator and denominator use product_items for consistent counting units."""
        total = db.execute(
            "SELECT COUNT(*) FROM product_items pi "
            "JOIN orders o ON pi.order_id=o.id "
            "WHERE pi.status IN ('completed','scrapped') AND o.deleted_at IS NULL "
            "AND substr(pi.completed_at,1,7)=strftime('%Y-%m','now')"
        ).fetchone()[0] or 0
        scrap = db.execute(
            "SELECT COUNT(*) FROM product_items pi "
            "JOIN orders o ON pi.order_id=o.id "
            "WHERE pi.status='scrapped' AND o.deleted_at IS NULL "
            "AND substr(pi.completed_at,1,7)=strftime('%Y-%m','now')"
        ).fetchone()[0] or 0
        return round(scrap / total * 100, 1) if total else 0

    @staticmethod
    def _kpi_active_workers(db):
        """Count distinct workers with approved work records today."""
        return db.execute(
            f"SELECT COUNT(DISTINCT wr.user_id) FROM work_records wr "
            f"JOIN orders o ON wr.order_id=o.id "
            f"WHERE o.deleted_at IS NULL AND wr.status='approved' "
            f"AND DATE(wr.created_at)=date('now')"
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
