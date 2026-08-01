"""
qr-system - ReworkService (Refactored: SQL -> ReworkRepository)
"""
import logging
from datetime import datetime
from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.services import BaseService
from modules.repositories.rework_repository import ReworkRepository


class ReworkService:
    """Rework business logic."""

    ALLOWED_STATUSES = {"", "pending", "completed"}
    ALLOWED_RESULTS = {"ok", "scrap", "rework_again"}
    MAX_PAGE_SIZE = 200
    MAX_TEXT_LENGTH = 512

    @staticmethod
    def _integer(value, field, minimum=1, maximum=None):
        if type(value) is int:
            normalized = value
        elif isinstance(value, str) and value.strip().isdigit():
            normalized = int(value.strip())
        else:
            raise ValidationError(f"{field}必须是整数")
        if normalized < minimum:
            raise ValidationError(f"{field}必须大于等于 {minimum}")
        if maximum is not None and normalized > maximum:
            raise ValidationError(f"{field}不能大于 {maximum}")
        return normalized

    @staticmethod
    def _text(value, field, required=False):
        if value is None:
            value = ""
        if not isinstance(value, str):
            raise ValidationError(f"{field}必须是文本")
        value = value.strip()
        if required and not value:
            raise ValidationError(f"{field}不能为空")
        if len(value) > ReworkService.MAX_TEXT_LENGTH:
            raise ValidationError(f"{field}不能超过 {ReworkService.MAX_TEXT_LENGTH} 个字符")
        return value

    @staticmethod
    def _result(value):
        result = ReworkService._text(value, "返工结果", required=True)
        if result not in ReworkService.ALLOWED_RESULTS:
            raise ValidationError("返工结果必须是合格、报废或再次返工")
        return result

    @staticmethod
    def _date(value, field):
        value = ReworkService._text(value, field)
        if value:
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError as exc:
                raise ValidationError(f"{field}格式必须为 YYYY-MM-DD") from exc
        return value

    @staticmethod
    def _filters(status="", search="", date_from="", date_to="", worker_id=None, process_id=None):
        status = ReworkService._text(status, "状态")
        if status not in ReworkService.ALLOWED_STATUSES:
            raise ValidationError("返工状态必须是待处理或已完成")
        search = ReworkService._text(search, "搜索关键字")
        if len(search) > 128:
            raise ValidationError("搜索关键字不能超过 128 个字符")
        date_from = ReworkService._date(date_from, "开始日期")
        date_to = ReworkService._date(date_to, "结束日期")
        if date_from and date_to and date_from > date_to:
            raise ValidationError("开始日期不能晚于结束日期")
        if worker_id not in (None, ""):
            worker_id = ReworkService._integer(worker_id, "员工 ID")
        else:
            worker_id = None
        if process_id not in (None, ""):
            process_id = ReworkService._integer(process_id, "工序 ID")
        else:
            process_id = None
        return {
            "status": status,
            "search": search,
            "date_from": date_from,
            "date_to": date_to,
            "worker_id": worker_id,
            "process_id": process_id,
        }

    @staticmethod
    def list_rework(status="", search="", date_from="", date_to="", page=1, per_page=50,
                    worker_id=None, process_id=None):
        filters = ReworkService._filters(
            status, search, date_from, date_to, worker_id, process_id
        )
        page = ReworkService._integer(page, "页码")
        per_page = ReworkService._integer(
            per_page, "每页数量", maximum=ReworkService.MAX_PAGE_SIZE
        )
        return ReworkRepository.list_rework(
            page=page, per_page=per_page, **filters
        )

    @staticmethod
    def create_rework(
        order_id,
        process_id,
        user_id,
        quantity,
        reason="",
        db=None,
        source_ncr_id=None,
        reject_recent_duplicate=False,
    ):
        order_id = ReworkService._integer(order_id, "订单 ID")
        process_id = ReworkService._integer(process_id, "工序 ID")
        user_id = ReworkService._integer(user_id, "操作人 ID")
        quantity = ReworkService._integer(quantity, "返工数量", maximum=99999)
        reason = ReworkService._text(reason, "返工原因")
        if source_ncr_id is not None:
            source_ncr_id = ReworkService._integer(source_ncr_id, "不合格单 ID")

        if db is not None:
            return ReworkService._create_rework_txn(
                order_id, process_id, user_id, quantity, reason, source_ncr_id,
                reject_recent_duplicate, db
            )
        with BaseService.transaction() as txn:
            return ReworkService._create_rework_txn(
                order_id, process_id, user_id, quantity, reason, source_ncr_id,
                reject_recent_duplicate, txn
            )

    @staticmethod
    def _create_rework_txn(
        order_id, process_id, user_id, quantity, reason, source_ncr_id,
        reject_recent_duplicate, db
    ):
        context_row = ReworkRepository.find_order_process_context(order_id, process_id, db=db)
        if not context_row or context_row["deleted_at"] is not None:
            raise NotFoundError("订单不存在或已删除")
        if context_row["order_status"] in {"completed", "cancelled"}:
            raise ConflictError("订单已完成或取消，不能新增返工")
        if context_row["order_process_id"] is None:
            raise ValidationError("该工序不在订单工艺路线中")
        if source_ncr_id and ReworkRepository.find_by_source_ncr_id(source_ncr_id, db=db):
            raise ConflictError("该质量不合格单已经生成返工记录")
        if reject_recent_duplicate and ReworkRepository.find_recent_duplicate(
            order_id, process_id, user_id, db=db
        ):
            raise ConflictError("请勿重复提交返工记录")

        rework_id = ReworkRepository.insert_rework_txn(
            order_id, process_id, user_id, quantity, reason, db=db,
            source_ncr_id=source_ncr_id
        )
        if ReworkRepository.increment_order_process_rework_txn(
            order_id, process_id, quantity, db=db
        ) != 1:
            raise ConflictError("订单工序状态已变化，请刷新后重试")
        if ReworkRepository.sync_order_rework_txn(order_id, db=db) != 1:
            raise ConflictError("订单状态已变化，请刷新后重试")
        return rework_id

    @staticmethod
    def get_stats():
        return ReworkRepository.get_stats()

    @staticmethod
    def update_rework(rework_id, reason):
        rework_id = ReworkService._integer(rework_id, "返工记录 ID")
        reason = ReworkService._text(reason, "返工原因")
        with BaseService.transaction() as txn:
            rw = ReworkRepository.find_by_id(rework_id, db=txn)
            if not rw:
                raise NotFoundError("返工记录不存在")
            if rw["status"] != "pending":
                raise ConflictError("已完成的返工记录不能修改")
            if ReworkRepository.update_reason_pending(rework_id, reason, db=txn) != 1:
                raise ConflictError("返工记录状态已变化，请刷新后重试")

    @staticmethod
    def export_rework(status="", search="", date_from="", date_to="",
                      worker_id=None, process_id=None):
        from modules.export_utils import style_header, auto_width, THIN_BORDER, CELL_ALIGN
        from openpyxl import Workbook
        from io import BytesIO

        filters = ReworkService._filters(
            status, search, date_from, date_to, worker_id, process_id
        )
        items = ReworkRepository.find_all_for_export(**filters)
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
        rework_id = ReworkService._integer(rework_id, "返工记录 ID")
        user_id = ReworkService._integer(user_id, "操作人 ID")
        reason = ReworkService._text(reason, "返工原因")
        result = ReworkService._result(result)
        result_remark = ReworkService._text(result_remark, "处理备注")
        with BaseService.transaction() as txn:
            rw = ReworkRepository.find_by_id(rework_id, db=txn)
            if not rw:
                raise NotFoundError("返工记录不存在")
            if rw["status"] != "pending":
                raise ConflictError("返工记录已完成，请勿重复操作")
            ReworkService._complete_rework_txn(
                dict(rw), reason, user_id, result, result_remark, txn
            )

    @staticmethod
    def _duration_hours(rework):
        created = rework.get("created_at")
        if not created:
            return 0
        try:
            started_at = datetime.strptime(created[:19], "%Y-%m-%d %H:%M:%S")
            return round((datetime.now() - started_at).total_seconds() / 3600, 1)
        except (TypeError, ValueError):
            logging.getLogger(__name__).debug(
                "rework duration calc failed: %s", rework.get("id")
            )
            return 0

    @staticmethod
    def _complete_rework_txn(rework, reason, user_id, result, result_remark, db):
        reason_final = reason or rework.get("reason", "")
        updated = ReworkRepository.complete_rework_txn(
            rework["id"], reason_final, user_id, result, result_remark,
            ReworkService._duration_hours(rework), db=db
        )
        if updated != 1:
            raise ConflictError("返工记录状态已变化，请刷新后重试")
        from modules.services.quality_management.tasks import QualityTaskService
        QualityTaskService.generate_for_rework(rework["id"], user_id, db)

    # ============ Analytics ============

    @staticmethod
    def rework_trend(period="week", months=3):
        period = ReworkService._text(period, "统计周期")
        if period not in {"week", "month"}:
            raise ValidationError("统计周期必须是 week 或 month")
        months = ReworkService._integer(months, "统计月数", maximum=24)
        return ReworkRepository.rework_trend(period=period, months=months)

    @staticmethod
    def top_rework_processes(top_n=5):
        top_n = ReworkService._integer(top_n, "排行数量", maximum=50)
        return ReworkRepository.top_rework_processes(top_n=top_n)

    @staticmethod
    def worker_rework_stats():
        return ReworkRepository.worker_rework_stats()

    @staticmethod
    def batch_complete(rework_ids, reason, user_id, result="ok", result_remark=""):
        """Batch complete rework records within a single transaction."""
        if not isinstance(rework_ids, list) or not rework_ids:
            raise ValidationError("请选择返工记录")
        if len(rework_ids) > 100:
            raise ValidationError("单次最多处理 100 条返工记录")
        normalized_ids = []
        for rework_id in rework_ids:
            normalized_id = ReworkService._integer(rework_id, "返工记录 ID")
            if normalized_id not in normalized_ids:
                normalized_ids.append(normalized_id)
        user_id = ReworkService._integer(user_id, "操作人 ID")
        reason = ReworkService._text(reason, "返工原因")
        result = ReworkService._result(result)
        result_remark = ReworkService._text(result_remark, "处理备注")
        completed = 0
        errors = []
        with BaseService.transaction() as txn:
            for rework_id in normalized_ids:
                rw = ReworkRepository.find_by_id(rework_id, db=txn)
                if not rw:
                    errors.append({"id": rework_id, "error": "返工记录不存在"})
                    continue
                if rw["status"] != "pending":
                    errors.append({"id": rework_id, "error": "返工记录已完成"})
                    continue
                ReworkService._complete_rework_txn(
                    dict(rw), reason, user_id, result, result_remark, txn
                )
                completed += 1
        return {"completed": completed, "errors": errors}
