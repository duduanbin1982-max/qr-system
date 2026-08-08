"""qr-system \u2014 ReportsService (refactored)"""
from modules.repositories.reports_repository import ReportsRepository

PROCESS_ORDER = ["下料", "铆接", "焊接", "抛丸", "打磨", "镗孔", "喷漆"]


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
        workers = ReportsRepository.worker_efficiency(start, end, product_code)
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
        from modules.services.quality_service import QualityService

        by_process = ReportsRepository.quality_by_process(start, end, product_code)
        result = {"by_process": _calc_defect_rate(by_process)}
        trend_list = QualityService.pass_rate_trend(
            weeks=6, start=start, end=end, product_code=product_code
        )
        result["trend_labels"] = [item["label"] for item in trend_list]
        result["trend_pass_rates"] = [item["rate"] for item in trend_list]

        spc = QualityService.spc_p_chart(
            date_from=start, date_to=end, product_code=product_code
        )
        result["spc_samples"] = [sample["rate"] for sample in spc.get("samples", [])]
        result["spc_ucl"] = spc.get("ucl", 0)
        result["spc_cl"] = spc.get("cl", 0)
        result["spc_lcl"] = spc.get("lcl", 0)

        inspector = QualityService.inspector_performance(
            start=start, end=end, product_code=product_code
        )
        result["inspector_data"] = inspector.get("data", [])
        supplier = QualityService.supplier_quality(
            start=start, end=end, product_code=product_code
        )
        result["supplier_data"] = supplier.get("data", [])
        result["qi_by_process"] = [
            dict(row) for row in ReportsRepository.quality_inspection_by_process(
                start, end, product_code
            )
        ]
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
        by_product, summary = ReportsRepository.product_report(start, end, product_code)
        return {
            "by_product": [dict(r) for r in by_product],
            "summary": dict(summary) if summary else {},
        }
    @staticmethod
    def material_usage(start="", end="", product_code=""):
        by_material, summary = ReportsRepository.material_usage(start, end, product_code)
        return {
            "by_material": [dict(r) for r in by_material],
            "summary": dict(summary) if summary else {},
        }

    @staticmethod
    def shipment_stats(start="", end="", product_code=""):
        by_status, by_customer, monthly = ReportsRepository.shipment_stats(
            start, end, product_code
        )
        return {
            "by_status": [dict(r) for r in by_status],
            "by_customer": [dict(r) for r in by_customer],
            "monthly_trend": [dict(r) for r in monthly],
        }

    @staticmethod
    def product_process_matrix(start="", end="", product_code=""):
        """Product x Process cross-tab matrix for heatmap visualization."""
        rows = ReportsRepository.product_process_matrix(start, end, product_code)
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
        rows = ReportsRepository.model_process_stats(start, end)
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
        all_procs, rows = ReportsRepository.product_process_stats(start, end)
        proc_names = sorted([r["name"] for r in all_procs], key=lambda n: PROCESS_ORDER.index(n) if n in PROCESS_ORDER else 999)
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
        rows = ReportsRepository.customer_stats(start, end)
        return [dict(r) for r in rows]

    @staticmethod
    def production_line_stats(start="", end=""):
        rows = ReportsRepository.production_line_stats(start, end)
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
            "monthly_summary": ReportsService.monthly_summary(),
        }
