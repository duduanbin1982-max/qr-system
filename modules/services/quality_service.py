"""qr-system - QualityService (Refactored: SQL -> QualityRepository)"""
from datetime import datetime
from modules.services import BaseService
from modules.repositories.quality_repository import QualityRepository
import logging

INSPECTION_TYPES = {"first_article": "first article", "in_process": "in_process", "final": "final", "rework_check": "rework_check"}
DEFECT_CATEGORIES = ["size", "appearance", "material", "welding", "assembly", "other"]


class QualityService:

    @staticmethod
    def list_inspections(order_id=None, process_id=None, inspection_type="",
                         result="", search="", date_from="", date_to="",
                         page=1, per_page=20):
        return QualityRepository.list_inspections(
            order_id=order_id, process_id=process_id,
            inspection_type=inspection_type, result=result, search=search,
            date_from=date_from, date_to=date_to, page=page, per_page=per_page
        )

    @staticmethod
    def check_order_exists(order_id):
        order = QualityRepository.check_order_exists(order_id)
        if not order:
            raise ValueError("order not found")
        if order["deleted_at"] is not None:
            raise ValueError("order deleted, cannot add inspection")
        return order

    @staticmethod
    def create_inspection(data, user_id):
        order_id = data.get("order_id")
        process_id = data.get("process_id")
        inspection_type = data.get("inspection_type", "first_article")
        quantity_checked = data.get("quantity_checked", 0)
        quantity_passed = data.get("quantity_passed", 0)
        quantity_failed = data.get("quantity_failed", 0)
        defect_category = data.get("defect_category", "").strip()
        defect_quantity = data.get("defect_quantity", 0)
        notes = data.get("notes", "")
        inspected_at = data.get("inspected_at", "")

        if not order_id or not process_id:
            raise ValueError("order and process required")
        if inspection_type not in INSPECTION_TYPES:
            raise ValueError("invalid inspection type")
        if defect_category and defect_category not in DEFECT_CATEGORIES:
            raise ValueError("invalid defect category: " + defect_category)

        result = "pass" if quantity_failed == 0 else ("fail" if quantity_passed == 0 else "partial")
        data["result"] = result

        with BaseService.transaction() as txn:
            return QualityRepository.insert_inspection_txn(data, user_id, db=txn)

    @staticmethod
    def get_inspection(inspection_id):
        qi = QualityRepository.find_by_id(inspection_id)
        if not qi:
            raise ValueError("record not found")
        return dict(qi)

    @staticmethod
    def update_inspection(inspection_id, data):
        qi = QualityRepository.find_by_id(inspection_id)
        if not qi:
            raise ValueError("record not found")

        inspection_type = data.get("inspection_type", qi["inspection_type"])
        if inspection_type not in INSPECTION_TYPES:
            raise ValueError("invalid inspection type")
        defect_cat = data.get("defect_category", qi.get("defect_category", ""))
        if defect_cat and defect_cat not in DEFECT_CATEGORIES:
            raise ValueError("invalid defect category: " + defect_cat)

        qc = data.get("quantity_checked", qi["quantity_checked"])
        qp = data.get("quantity_passed", qi["quantity_passed"])
        qf = data.get("quantity_failed", qi["quantity_failed"])
        result = "pass" if qf == 0 else ("fail" if qp == 0 else "partial")
        data.setdefault("result", result)
        data.setdefault("quantity_checked", qc)
        data.setdefault("quantity_passed", qp)
        data.setdefault("quantity_failed", qf)
        data.setdefault("inspection_type", inspection_type)
        data.setdefault("defect_category", defect_cat)
        data.setdefault("defect_quantity", data.get("defect_quantity", qi.get("defect_quantity", 0)))
        data.setdefault("notes", data.get("notes", qi["notes"]))
        data.setdefault("inspected_at", data.get("inspected_at", qi["inspected_at"]))

        with BaseService.transaction() as txn:
            QualityRepository.update_inspection_txn(inspection_id, data, db=txn)
        return result

    @staticmethod
    def delete_inspection(inspection_id):
        qi = QualityRepository.find_by_id(inspection_id)
        if not qi:
            raise ValueError("record not found")
        with BaseService.transaction() as txn:
            QualityRepository.delete_inspection_txn(inspection_id, db=txn)

    @staticmethod
    def get_stats():
        return QualityRepository.get_stats()

    @staticmethod
    def defect_pareto(date_from="", date_to=""):
        return QualityRepository.defect_pareto(date_from=date_from, date_to=date_to)

    @staticmethod
    def spc_p_chart(order_id=None, process_id=None, date_from="", date_to=""):
        return QualityRepository.spc_p_chart(
            order_id=order_id, process_id=process_id,
            date_from=date_from, date_to=date_to
        )

    @staticmethod
    def inspector_performance(**kwargs):
        rows = QualityRepository.inspector_performance()
        result = []
        for r in rows:
            r = dict(r)
            total = r["total_checked"] or 0
            failed = r["total_failed"] or 0
            rate = round(failed / total * 100, 1) if total > 0 else 0
            result.append({
                "inspector_id": r["id"], "inspector_name": r["name"],
                "inspection_count": r["inspection_count"],
                "total_checked": total, "total_failed": failed,
                "overall_defect_rate": rate,
                "avg_defect_rate": r["avg_defect_rate"] or 0,
                "orders_covered": r["orders_covered"],
            })
        return {"ok": True, "data": result}

    @staticmethod
    def supplier_quality(**kwargs):
        rows = QualityRepository.supplier_quality()
        result = []
        for r in rows:
            r = dict(r)
            total = r["total_checked"] or 0
            failed = r["total_failed"] or 0
            rate = round(failed / total * 100, 1) if total > 0 else 0
            pass_rate = round(r["pass_count"] / r["inspection_count"] * 100, 1) if r["inspection_count"] > 0 else 0
            result.append({
                "customer_id": r["customer_id"],
                "customer_name": r["customer_name"],
                "inspection_count": r["inspection_count"],
                "total_checked": total, "total_failed": failed,
                "defect_rate": rate, "pass_rate": pass_rate,
                "pass_count": r["pass_count"], "fail_count": r["fail_count"],
            })
        return {"ok": True, "data": result}

    @staticmethod
    def pass_rate_trend(weeks=6, start="", end=""):
        return QualityRepository.pass_rate_trend(weeks=weeks, start=start, end=end)

    @staticmethod
    def export_inspections(order_id=None, process_id=None, inspection_type="",
                           result="", search="", date_from="", date_to=""):
        from modules.export_utils import style_header, auto_width, THIN_BORDER, CELL_ALIGN
        from openpyxl import Workbook
        from io import BytesIO

        items = QualityRepository.find_all_for_export(
            order_id=order_id, process_id=process_id,
            inspection_type=inspection_type, result=result, search=search,
            date_from=date_from, date_to=date_to
        )

        wb = Workbook()
        ws = wb.active
        ws.title = "quality inspections"

        headers = ["order_no", "product", "customer", "process", "type",
                   "inspector", "checked", "passed", "failed", "result",
                   "defect_cat", "defect_qty", "notes", "inspected_at"]
        style_header(ws, headers)

        type_map = {"first_article": "FAI", "in_process": "IPQC", "final": "FQC", "rework_check": "RC"}
        result_map = {"pass": "PASS", "fail": "FAIL", "partial": "PARTIAL"}

        for row_idx, item in enumerate(items, 2):
            vals = [
                item.get("order_no", ""), item.get("product_name", ""),
                item.get("customer_name", ""), item.get("process_name", ""),
                type_map.get(item.get("inspection_type", ""), item.get("inspection_type", "")),
                item.get("inspector_name", ""), item.get("quantity_checked", 0),
                item.get("quantity_passed", 0), item.get("quantity_failed", 0),
                result_map.get(item.get("result", ""), item.get("result", "")),
                item.get("defect_category", ""), item.get("defect_quantity", 0),
                item.get("notes", ""),
                item.get("inspected_at", "")[:19] if item.get("inspected_at") else "",
            ]
            for col_idx, val in enumerate(vals, 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.border = THIN_BORDER
                cell.alignment = CELL_ALIGN

        auto_width(ws)
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        return output

    # ============================================================
    # Attachments (was inline SQL in routes/quality.py)
    # ============================================================

    @staticmethod
    def list_attachments(inspection_id):
        rows = QualityRepository.list_attachments(inspection_id)
        return {"ok": True, "attachments": [dict(r) for r in rows]}

    @staticmethod
    def upload_attachment(inspection_id, file, user_id):
        import mimetypes
        file_data = file.read()
        mime = mimetypes.guess_type(file.filename)[0] or ""
        with BaseService.transaction() as txn:
            QualityRepository.insert_attachment_txn(
                inspection_id, file.filename, mime, len(file_data), file_data, user_id, db=txn
            )

    @staticmethod
    def download_attachment(att_id):
        row = QualityRepository.find_attachment_by_id(att_id)
        if not row:
            raise ValueError("attachment not found")
        return row

    @staticmethod
    def delete_attachment(att_id):
        row = QualityRepository.find_attachment_by_id(att_id)
        if not row:
            raise ValueError("attachment not found")
        with BaseService.transaction() as txn:
            QualityRepository.delete_attachment_txn(att_id, db=txn)

    # ============================================================
    # Mobile Inspection
    # ============================================================

    @staticmethod
    def submit_inspection(data, user_id, user_name=""):
        if not data.get("order_id") and not data.get("order_no"):
            raise ValueError("order_id or order_no required")
        with BaseService.transaction() as txn:
            return QualityRepository.insert_mobile_inspection_txn(data, user_id, db=txn)

    @staticmethod
    def list_inspections_simple(keyword="", page=1, limit=20, result=""):
        return QualityRepository.list_inspections_simple(
            keyword=keyword, page=page, limit=limit, result=result
        )

    @staticmethod
    def get_inspection_stats():
        return QualityRepository.get_mobile_inspection_stats()
