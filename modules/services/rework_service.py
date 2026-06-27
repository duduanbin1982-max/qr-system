"""
qr-system - ReworkService (Refactored: SQL -> ReworkRepository)
"""
import logging
from datetime import datetime, timedelta
from modules.services import BaseService
from modules.repositories.rework_repository import ReworkRepository
from modules.services.quality_service import QualityService


class ReworkService:
    """Rework business logic."""

    @staticmethod
    def list_rework(status="", search="", date_from="", date_to="", page=1, per_page=50,
                    worker_id=None, process_id=None):
        return ReworkRepository.list_rework(
            status=status, search=search, date_from=date_from, date_to=date_to,
            page=page, per_page=per_page, worker_id=worker_id, process_id=process_id
        )

    @staticmethod
    def create_rework(order_id, process_id, user_id, quantity, reason=""):
        if quantity <= 0:
            raise ValueError("quantity must be greater than 0")

        order = ReworkRepository.find_order(order_id)
        if not order:
            raise ValueError("order not found or deleted")
        proc = ReworkRepository.find_process(process_id)
        if not proc:
            raise ValueError("process not found")

        with BaseService.transaction() as txn:
            rework_id = ReworkRepository.insert_rework_txn(
                order_id, process_id, user_id, quantity, reason, db=txn
            )
            ReworkRepository.increment_order_process_rework_txn(
                order_id, process_id, quantity, db=txn
            )
            ReworkRepository.sync_order_rework_txn(order_id, db=txn)
        return rework_id

    @staticmethod
    def get_stats():
        return ReworkRepository.get_stats()

    @staticmethod
    def update_rework(rework_id, reason):
        rw = ReworkRepository.find_by_id(rework_id)
        if not rw:
            raise ValueError("rework record not found")
        ReworkRepository.update_reason(rework_id, reason)

    @staticmethod
    def export_rework(status="", search="", date_from="", date_to="",
                      worker_id=None, process_id=None):
        from modules.export_utils import style_header, auto_width, THIN_BORDER, CELL_ALIGN
        from openpyxl import Workbook
        from io import BytesIO

        items = ReworkRepository.find_all_for_export(
            status=status, search=search, date_from=date_from, date_to=date_to,
            worker_id=worker_id, process_id=process_id
        )
        items = [dict(item) for item in items]

        wb = Workbook()
        ws = wb.active
        ws.title = "Rework Records"
        headers = ["Order No", "Product", "Customer", "Process", "Worker",
                   "Quantity", "Reason", "Status", "Result", "Created", "Completed"]
        style_header(ws, headers)

        for row_idx, item in enumerate(items, 2):
            vals = [
                item.get("order_no", ""),
                item.get("product_name", ""),
                item.get("customer_name", ""),
                item.get("process_name", ""),
                item.get("worker_name", ""),
                item.get("quantity", 0),
                item.get("reason", ""),
                item.get("status", ""),
                item.get("result", ""),
                item.get("created_at", "")[:19] if item.get("created_at") else "",
                item.get("completed_at", "")[:19] if item.get("completed_at") else "",
            ]
            for col_idx, val in enumerate(vals, 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=val)
                cell.alignment = CELL_ALIGN
                cell.border = THIN_BORDER

        auto_width(ws)
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        return output

    @staticmethod
    def complete_rework(rework_id, reason, user_id, result="", result_remark=""):
        rw = ReworkRepository.find_by_id(rework_id)
        if not rw:
            raise ValueError("rework record not found")
        rw = dict(rw)
        if rw["status"] == "completed":
            raise ValueError("rework already completed")

        reason_final = reason or rw["reason"]

        # Calculate duration
        duration = 0
        created = rw.get("created_at")
        if created:
            try:
                d1 = datetime.strptime(created[:19], "%Y-%m-%d %H:%M:%S")
                d2 = datetime.now()
                duration = round((d2 - d1).total_seconds() / 3600, 1)
            except Exception:
                logging.getLogger(__name__).debug("rework duration calc failed: %s", rework_id)

        with BaseService.transaction() as txn:
            ReworkRepository.complete_rework_txn(
                rework_id, reason_final, user_id, result, result_remark, duration, db=txn
            )

        # Auto-create quality re-check after rework complete (non-critical)
        try:
            QualityService.create_inspection({
                "order_id": rw["order_id"],
                "process_id": rw["process_id"],
                "inspection_type": "rework_check",
                "quantity_checked": rw["quantity"],
                "quantity_passed": rw["quantity"] if result == "ok" else 0,
                "quantity_failed": rw["quantity"] if result == "scrap" else 0,
                "defect_category": "",
                "defect_quantity": 0,
                "notes": "rework re-check (rework_id:" + str(rework_id) + ") - result:" + result + " " + result_remark,
                "inspected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }, user_id)
        except Exception:
            logging.getLogger(__name__).warning(
                "auto_create_inspection on rework complete failed: rework_id=%s", rework_id
            )

    # ============ Analytics ============

    @staticmethod
    def rework_trend(period="week", months=3):
        return ReworkRepository.rework_trend(period=period, months=months)

    @staticmethod
    def top_rework_processes(top_n=5):
        return ReworkRepository.top_rework_processes(top_n=top_n)

    @staticmethod
    def worker_rework_stats():
        return ReworkRepository.worker_rework_stats()

    @staticmethod
    def batch_complete(rework_ids, reason, user_id, result="ok", result_remark=""):
        """Batch complete rework records within a single transaction."""
        completed = 0
        errors = []
        with BaseService.transaction() as txn:
            for rid in rework_ids:
                try:
                    rw = ReworkRepository.find_by_id(rid, db=txn)
                    if not rw:
                        errors.append({"id": rid, "error": "rework record not found"})
                        continue
                    rw = dict(rw)
                    if rw["status"] == "completed":
                        errors.append({"id": rid, "error": "rework already completed"})
                        continue

                    reason_final = reason or rw["reason"]
                    duration = 0
                    created = rw.get("created_at")
                    if created:
                        try:
                            d1 = datetime.strptime(created[:19], "%Y-%m-%d %H:%M:%S")
                            d2 = datetime.now()
                            duration = round((d2 - d1).total_seconds() / 3600, 1)
                        except Exception:
                            logging.getLogger(__name__).debug(
                                "rework duration calc failed: rework_id=%s", rid
                            )

                    ReworkRepository.complete_rework_txn(
                        rid, reason_final, user_id, result, result_remark, duration, db=txn
                    )

                    # Auto-create inspection (in same transaction, non-critical)
                    try:
                        QualityService.create_inspection({
                            "order_id": rw["order_id"],
                            "process_id": rw["process_id"],
                            "inspection_type": "rework_check",
                            "quantity_checked": rw["quantity"],
                            "quantity_passed": rw["quantity"] if result == "ok" else 0,
                            "quantity_failed": rw["quantity"] if result == "scrap" else 0,
                            "defect_category": "",
                            "defect_quantity": 0,
                            "notes": "rework batch-check (rework_id:" + str(rid) + ")",
                            "inspected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }, user_id)
                    except Exception:
                        logging.getLogger(__name__).warning(
                            "auto_create_inspection on rework batch complete failed: rework_id=%s",
                            rid,
                        )

                    completed += 1
                except ValueError as e:
                    errors.append({"id": rid, "error": str(e)})
        return {"completed": completed, "errors": errors}
