"""qr-system — ReportsService（Repository-refactored）"""
from modules.services import BaseService
from modules.repositories.reports_repository import ReportsRepository

_ACTIVE_ORDERS = "wr.order_id IN (SELECT id FROM orders WHERE deleted_at IS NULL)"

PROCESS_ORDER = ["下料", "铆接", "焊接", "抛丸", "打磨", "镗孔", "喷漆"]


def _build_date_filter(start, end, prefix="wr"):
    where = []
    params = []
    if start:
        where.append("DATE(" + prefix + ".created_at) >= ?")
        params.append(start)
    if end:
        where.append("DATE(" + prefix + ".created_at) <= ?")
        params.append(end)
    return " AND ".join(where) if where else "", params


def _build_item_wheres(start, end):
    """Build three subquery WHERE fragments for output/scrap/rework item queries."""
    pi_w, sr_w, wr_w = "", "", ""
    item_params = []
    if start:
        pi_w += " AND DATE(pi.completed_at) >= ?"; item_params.append(start)
        sr_w += " AND DATE(sr.created_at) >= ?"; item_params.append(start)
        wr_w += " AND DATE(wr.created_at) >= ?"; item_params.append(start)
    if end:
        pi_w += " AND DATE(pi.completed_at) <= ?"; item_params.append(end)
        sr_w += " AND DATE(sr.created_at) <= ?"; item_params.append(end)
        wr_w += " AND DATE(wr.created_at) <= ?"; item_params.append(end)
    return pi_w, sr_w, wr_w, item_params


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
        trend = ReportsRepository.fetch_production_trend(start_date, end_date)
        return [dict(r) for r in trend]

    @staticmethod
    def worker_efficiency(start="", end="", product_code=""):
        date_w, date_p = _build_date_filter(start, end)
        where = [_ACTIVE_ORDERS, "wr.status = 'approved'"]
        params = list(date_p)
        if date_w:
            where.append(date_w)
        if product_code:
            where.append("wr.order_id IN (SELECT id FROM orders WHERE product_code = ?)")
            params.append(product_code)
        w = " AND ".join(where)
        workers = ReportsRepository.fetch_worker_efficiency(w, params)
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
        date_w, date_p = _build_date_filter(start, end)
        where = [_ACTIVE_ORDERS, "wr.status = 'approved'"]
        params = list(date_p)
        if date_w:
            where.append(date_w)
        if product_code:
            where.append("wr.order_id IN (SELECT id FROM orders WHERE product_code = ?)")
            params.append(product_code)
        w = " AND ".join(where)
        by_process = ReportsRepository.fetch_quality_by_process(w, params)
        pi_w, sr_w, wr_w, item_params = _build_item_wheres(start, end)
        by_product = ReportsRepository.fetch_quality_by_product(
            w, params, pi_w, sr_w, wr_w, item_params
        )
        summary = ReportsRepository.fetch_quality_summary(w, params, pi_w, item_params)
        result = {"by_process": _calc_defect_rate(by_process)}
        if by_product:
            result["by_product"] = [dict(r) for r in by_product]
        if summary:
            result["summary"] = dict(summary)
        return result

    @staticmethod
    def product_report(start="", end="", product_code=""):
        where = ["o.deleted_at IS NULL"]
        params = []
        if start:
            where.append("DATE(o.created_at) >= ?"); params.append(start)
        if end:
            where.append("DATE(o.created_at) <= ?"); params.append(end)
        if product_code:
            where.append("o.product_code = ?"); params.append(product_code)
        w = " AND ".join(where)
        pi_w, sr_w, wr_w, item_params = _build_item_wheres(start, end)
        by_product = ReportsRepository.fetch_product_report(
            w, params, pi_w, sr_w, wr_w, item_params
        )
        summary = ReportsRepository.fetch_product_report_summary(w, params, pi_w, item_params)
        return {
            "by_product": [dict(r) for r in by_product],
            "summary": dict(summary) if summary else {},
        }

    @staticmethod
    def material_usage(start="", end="", product_code=""):
        date_w, date_p = _build_date_filter(start, end, prefix="mc")
        where = ["1=1"]
        params = list(date_p)
        if date_w:
            where.append(date_w)
        if product_code:
            where.append("mc.order_id IN (SELECT id FROM orders WHERE product_code = ?)")
            params.append(product_code)
        w = " AND ".join(where)
        by_material = ReportsRepository.fetch_material_usage(w, params)
        summary = ReportsRepository.fetch_material_usage_summary(date_w, date_p)
        return {
            "by_material": [dict(r) for r in by_material],
            "summary": dict(summary) if summary else {},
        }

    @staticmethod
    def shipment_stats(start="", end="", product_code=""):
        date_w, date_p = _build_date_filter(start, end, prefix="s")
        where = ["1=1"]
        params = list(date_p)
        if date_w:
            where.append(date_w)
        if product_code:
            where.append("s.id IN (SELECT si.shipment_id FROM shipment_items si JOIN orders o ON si.order_id=o.id WHERE o.product_code = ?)")
            params.append(product_code)
        w = " AND ".join(where)
        by_status = ReportsRepository.fetch_shipment_by_status(w, params)
        by_customer = ReportsRepository.fetch_shipment_by_customer(w, params)
        monthly = ReportsRepository.fetch_shipment_monthly_trend(w, params)
        return {
            "by_status": [dict(r) for r in by_status],
            "by_customer": [dict(r) for r in by_customer],
            "monthly_trend": [dict(r) for r in monthly],
        }

    @staticmethod
    def product_process_matrix(start="", end=""):
        """Product x Process cross-tab matrix for heatmap visualization."""
        date_w, date_p = _build_date_filter(start, end)
        where = ["wr.status = 'approved'", "o.deleted_at IS NULL"]
        params = list(date_p)
        if date_w:
            where.append(date_w)
        w = " AND ".join(where)
        rows = ReportsRepository.fetch_product_process_matrix(w, params)
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
        date_w, date_p = _build_date_filter(start, end)
        where = ["wr.status = 'approved'", "o.deleted_at IS NULL"]
        params = list(date_p)
        if date_w:
            where.append(date_w)
        w = " AND ".join(where)
        rows = ReportsRepository.fetch_model_process_stats(w, params)
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
        date_w, date_p = _build_date_filter(start, end)
        where = ["wr.status = 'approved'", "o.deleted_at IS NULL", "o.status != 'cancelled'"]
        params = list(date_p)
        if date_w:
            where.append(date_w)
        w = " AND ".join(where)
        all_procs = ReportsRepository.fetch_product_process_proc_names(w, params)
        proc_names = sorted([r["name"] for r in all_procs],
                           key=lambda n: PROCESS_ORDER.index(n) if n in PROCESS_ORDER else 999)
        rows = ReportsRepository.fetch_product_process_matrix_data(w, params)
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
        where = ["o.deleted_at IS NULL"]
        params = []
        if start:
            where.append("DATE(o.created_at) >= ?"); params.append(start)
        if end:
            where.append("DATE(o.created_at) <= ?"); params.append(end)
        w = " AND ".join(where)
        rows = ReportsRepository.fetch_customer_stats(w, params)
        return [dict(r) for r in rows]

    @staticmethod
    def production_line_stats(start="", end=""):
        where = ["o.deleted_at IS NULL"]
        params = []
        if start:
            where.append("DATE(o.created_at) >= ?"); params.append(start)
        if end:
            where.append("DATE(o.created_at) <= ?"); params.append(end)
        w = " AND ".join(where)
        rows = ReportsRepository.fetch_production_line_stats(w, params)
        return [dict(r) for r in rows]

    @staticmethod
    def monthly_summary():
        this_month = ReportsRepository.fetch_monthly_summary_this()
        last_month = ReportsRepository.fetch_monthly_summary_last()

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
        return {
            "active_orders": ReportsRepository.kpi_active_orders(),
            "completed_month": ReportsRepository.kpi_completed_month(),
            "output_month": ReportsRepository.kpi_output_month(),
            "scrap_rate": ReportsService._calc_scrap_rate(),
            "active_workers_today": ReportsRepository.kpi_active_workers(),
            "pending_shipments": ReportsRepository.kpi_pending_shipments(),
            "low_stock_count": ReportsRepository.kpi_low_stock(),
            "weekly_trend": ReportsRepository.kpi_weekly_trend(),
        }

    @staticmethod
    def _calc_scrap_rate():
        """Scrap rate = scrapped product_items / (completed + scrapped) this month."""
        total = ReportsRepository.kpi_scrap_total()
        scrap = ReportsRepository.kpi_scrap_count()
        return round(scrap / total * 100, 1) if total else 0
