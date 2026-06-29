"""qr-system \u2014 ReportsService (refactored)"""
import logging

from modules.repositories.reports_repository import ReportsRepository

_logger = logging.getLogger(__name__)
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
        where = [_ACTIVE_ORDERS, 'wr.status = "approved"']
        params = list(date_p)
        if date_w:
            where.append(date_w)
        if product_code:
            where.append("wr.order_id IN (SELECT id FROM orders WHERE product_code = ?)")
            params.append(product_code)
        w = " AND ".join(where)
        by_process = ReportsRepository.fetch_quality_by_process(w, params)
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
        except Exception as exc:
            _logger.warning("quality pass_rate_trend report failed: %s", exc)
        try:
            spc = QualityService.spc_p_chart(limit=50, start=start, end=end)
            if isinstance(spc, dict):
                result["spc_samples"] = [s["rate"] for s in spc.get("samples", [])]
                result["spc_ucl"] = spc.get("ucl", 0)
                result["spc_cl"] = spc.get("cl", 0)
                result["spc_lcl"] = spc.get("lcl", 0)
        except Exception as exc:
            _logger.warning("quality spc_p_chart report failed: %s", exc)
        try:
            insp = QualityService.inspector_performance(start=start, end=end)
            if isinstance(insp, dict):
                result["inspector_data"] = insp.get("data", [])
        except Exception as exc:
            _logger.warning("quality inspector_performance report failed: %s", exc)
        try:
            supp = QualityService.supplier_quality(start=start, end=end)
            if isinstance(supp, dict):
                result["supplier_data"] = supp.get("data", [])
        except Exception as exc:
            _logger.warning("quality supplier_quality report failed: %s", exc)
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
            qi_by_process = ReportsRepository.fetch_quality_inspection_by_process(qi_w, qi_params)
            result["qi_by_process"] = [dict(r) for r in qi_by_process]
        except Exception as exc:
            _logger.warning("quality inspection by-process report failed: %s", exc)
        return result
    @staticmethod
    def order_analysis():
        status_dist = ReportsRepository.fetch_order_status_distribution()
        monthly = ReportsRepository.fetch_order_monthly_trend()
        return {
            "status_distribution": [dict(r) for r in status_dist],
            "monthly_trend": [dict(r) for r in monthly],
        }

    @staticmethod
    def product_stats(start="", end="", product_code=""):
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
        item_extra = []
        if start:
            item_w += " AND DATE(pi.completed_at) >= ?"
            item_extra.append(start)
        if end:
            item_w += " AND DATE(pi.completed_at) <= ?"
            item_extra.append(end)
        sr_w = (" AND DATE(sr.created_at) >= ?" if start else "") + (" AND DATE(sr.created_at) <= ?" if end else "")
        wr_w = (" AND DATE(wr.created_at) >= ?" if start else "") + (" AND DATE(wr.created_at) <= ?" if end else "")
        by_product = ReportsRepository.fetch_product_report(w, params, item_w, sr_w, wr_w, item_extra)
        summary = ReportsRepository.fetch_product_report_summary(w, params, item_w, item_extra)
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
        monthly = ReportsRepository.fetch_shipment_monthly_trend(w + " AND s.created_at>=date('now','-12 months')", params)
        return {
            "by_status": [dict(r) for r in by_status],
            "by_customer": [dict(r) for r in by_customer],
            "monthly_trend": [dict(r) for r in monthly],
        }

    @staticmethod
    def product_process_matrix(start="", end="", product_code=""):
        """Product x Process cross-tab matrix for heatmap visualization."""
        date_w, date_p = _build_date_filter(start, end)
        where = ["wr.status = 'approved'", "o.deleted_at IS NULL"]
        params = list(date_p)
        if date_w:
            where.append(date_w)
        if product_code:
            where.append("p.product_code = ?")
            params.append(product_code)
        w = " AND ".join(where)
        rows = ReportsRepository.fetch_product_process_matrix(w, params)
        products = {}
        processes = {}
        for r in rows:
            pc = r["product_code"]
            if pc not in products:
                products[pc] = {"product_code": pc, "product_name": r["product_name"],
                                 "model": r["model"], "spec": r["spec"], "data": {}}
            products[pc]["data"][r["process_id"]] = r["output"]
            processes[r["process_id"]] = {
                "id": r["process_id"],
                "name": r["process_name"],
                "seq_order": r["seq_order"],
            }
        process_list = sorted(
            processes.values(),
            key=lambda p: (
                PROCESS_ORDER.index(p["name"]) if p["name"] in PROCESS_ORDER else 999,
                p["seq_order"] if p["seq_order"] is not None else 999,
                p["name"],
            ),
        )
        public_processes = [{"id": p["id"], "name": p["name"]} for p in process_list]
        product_rows = []
        for product in products.values():
            data = [product["data"].get(process["id"], 0) for process in public_processes]
            product_rows.append({
                "product_code": product["product_code"],
                "product_name": product["product_name"],
                "model": product["model"],
                "spec": product["spec"],
                "data": data,
                "total": sum(data),
            })
        return {
            "products": product_rows,
            "processes": public_processes,
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
        # Get all distinct processes first (sorted by custom order)
        all_procs = ReportsRepository.fetch_product_process_proc_names(w, params)
        proc_names = sorted([r["name"] for r in all_procs], key=lambda n: PROCESS_ORDER.index(n) if n in PROCESS_ORDER else 999)
        # Get product-process matrix
        rows = ReportsRepository.fetch_product_process_matrix_data(w, params)
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
        scrap_total = ReportsRepository.kpi_scrap_total()
        scrap_count = ReportsRepository.kpi_scrap_count()
        return {
            "active_orders": ReportsRepository.kpi_active_orders(),
            "completed_month": ReportsRepository.kpi_completed_month(),
            "output_month": ReportsRepository.kpi_output_month(),
            "scrap_rate": round(scrap_count / scrap_total * 100, 1) if scrap_total else 0,
            "active_workers_today": ReportsRepository.kpi_active_workers(),
            "pending_shipments": ReportsRepository.kpi_pending_shipments(),
            "low_stock_count": ReportsRepository.kpi_low_stock(),
            "weekly_trend": [dict(r) for r in ReportsRepository.kpi_weekly_trend()],
        }
