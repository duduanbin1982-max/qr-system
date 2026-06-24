"""Transactional writer for scan work reports."""
import logging
from datetime import datetime

from modules.repositories.scan_repository import ScanRepository
from modules.services import BaseService
from modules.services.inventory_auto_inbound_service import InventoryAutoInboundService


_logger = logging.getLogger(__name__)


class WorkReportWriter:
    """Persists normal, scrap, and rework reports inside one transaction."""

    @staticmethod
    def execute_report_write(report_type, order_id, process_id, user_id, user_name,
                             quantity, remark, serial_no, need_approval, record_type="normal"):
        """共享报工写入逻辑。整个方法在事务中执行，全部成功或全部回滚。"""
        from modules.services.scan_helper_service import ScanHelperService

        with BaseService.transaction() as db:
            WorkReportWriter._check_duplicates(
                ScanHelperService,
                report_type,
                order_id,
                process_id,
                user_id,
                serial_no,
                db,
            )
            current_op = WorkReportWriter._load_current_operation(
                ScanHelperService,
                order_id,
                process_id,
                db,
            )

            if report_type == "normal":
                WorkReportWriter._check_normal_limits(
                    ScanHelperService,
                    order_id,
                    current_op,
                    quantity,
                    db,
                )
                WorkReportWriter._write_normal_report(
                    ScanHelperService,
                    order_id,
                    process_id,
                    user_id,
                    user_name,
                    quantity,
                    remark,
                    serial_no,
                    need_approval,
                    db,
                )
            elif report_type == "scrap":
                WorkReportWriter._write_scrap_report(
                    ScanHelperService,
                    order_id,
                    process_id,
                    user_id,
                    quantity,
                    remark,
                    db,
                )
            elif report_type == "rework":
                WorkReportWriter._write_rework_report(
                    ScanHelperService,
                    order_id,
                    process_id,
                    user_id,
                    quantity,
                    remark,
                    db,
                )

    @staticmethod
    def _check_duplicates(helper, report_type, order_id, process_id, user_id, serial_no, db):
        if report_type == "normal":
            dup = helper.check_duplicate_normal_report(
                order_id,
                process_id,
                serial_no,
                user_id,
                db=db,
            )
            if dup:
                msg = "序列号 {} 在此工序已报工".format(serial_no) if serial_no else "此工序已报工"
                raise ValueError(msg)
        elif report_type in ("scrap", "rework"):
            dup = helper.check_duplicate_defect_report(
                order_id,
                process_id,
                user_id,
                report_type,
                db=db,
            )
            if dup:
                raise ValueError("请勿重复提交缺陷报告")

    @staticmethod
    def _load_current_operation(helper, order_id, process_id, db):
        current_op = dict(helper.get_order_process(order_id, process_id, db=db) or {})
        if not current_op:
            raise ValueError("该工序不在订单工艺路线中")
        return current_op

    @staticmethod
    def _check_normal_limits(helper, order_id, current_op, quantity, db):
        err, code = helper.check_process_order(
            order_id,
            current_op.get("seq_order", 0),
            db=db,
        )
        if err:
            raise ValueError(err.get("error", "工序顺序校验失败，请按工艺路线顺序报工"))

        order = dict(helper.get_order(order_id, db=db) or {})
        if not order:
            return

        err, code = helper.check_quantity_limits(
            order_id,
            current_op.get("seq_order", 0),
            current_op.get("completed", 0) or 0,
            quantity,
            order.get("quantity", 0),
            db=db,
        )
        if err:
            raise ValueError(err.get("error", "报工数量超出订单总量限制"))

    @staticmethod
    def _write_normal_report(helper, order_id, process_id, user_id, user_name,
                             quantity, remark, serial_no, need_approval, db):
        work_status = "pending" if need_approval else "approved"
        quantity_local = 1 if serial_no else quantity
        wr_id = helper.insert_work_record(
            order_id,
            process_id,
            user_id,
            "normal",
            quantity_local,
            remark,
            work_status,
            serial_no,
            db=db,
        )

        if need_approval:
            helper.insert_approval_record(wr_id, db=db)

        if work_status == "approved":
            WorkReportWriter._apply_approved_normal_effects(
                helper,
                order_id,
                process_id,
                user_id,
                user_name,
                quantity_local,
                serial_no,
                db,
            )

        if serial_no:
            WorkReportWriter._advance_serial_item(
                helper,
                order_id,
                process_id,
                user_id,
                user_name,
                serial_no,
                db,
            )

    @staticmethod
    def _apply_approved_normal_effects(helper, order_id, process_id, user_id, user_name,
                                       quantity_local, serial_no, db):
        op = helper.get_order_process(order_id, process_id, db=db)
        if op:
            new_completed = (op["completed"] or 0) + quantity_local
            helper.update_order_process_completed(order_id, process_id, new_completed, db=db)

        WorkReportWriter._create_first_article_if_needed(
            order_id,
            process_id,
            user_id,
            db,
        )
        ScanRepository.deduct_materials_for_process(
            order_id,
            process_id,
            quantity_local,
            user_id,
            user_name,
            db=db,
        )

        if not serial_no and op:
            WorkReportWriter._auto_inbound_last_non_serial(
                helper,
                order_id,
                process_id,
                user_id,
                user_name,
                db,
            )

    @staticmethod
    def _create_first_article_if_needed(order_id, process_id, user_id, db):
        first_count = db.execute(
            "SELECT COUNT(*) FROM work_records "
            "WHERE order_id=? AND process_id=? AND type='normal' AND status='approved'",
            (order_id, process_id),
        ).fetchone()[0]
        if first_count > 1:
            return

        existing = db.execute(
            "SELECT id FROM quality_inspections "
            "WHERE order_id=? AND process_id=? AND inspection_type='first_article'",
            (order_id, process_id),
        ).fetchone()
        if existing:
            return

        try:
            from modules.services.quality_service import QualityService

            QualityService.create_inspection({
                "order_id": order_id,
                "process_id": process_id,
                "inspection_type": "first_article",
                "quantity_checked": 1,
                "quantity_passed": 0,
                "quantity_failed": 0,
                "defect_category": "",
                "defect_quantity": 0,
                "notes": "自动创建: 首件报工",
                "inspected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }, user_id)
        except Exception:
            _logger.warning(
                "auto_create_inspection failed: order_id=%s process_id=%s",
                order_id,
                process_id,
            )

    @staticmethod
    def _auto_inbound_last_non_serial(helper, order_id, process_id, user_id, user_name, db):
        order_status = db.execute(
            "SELECT status FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if order_status and order_status["status"] != "completed":
            if helper.is_last_process(order_id, process_id, db=db):
                InventoryAutoInboundService.auto_inbound_for_item(
                    order_id,
                    user_id,
                    user_name,
                    serial_no=None,
                    db=db,
                )

    @staticmethod
    def _advance_serial_item(helper, order_id, process_id, user_id, user_name, serial_no, db):
        current_op = dict(helper.get_order_process(order_id, process_id, db=db) or {})
        if current_op:
            item = helper.get_product_item(serial_no, db=db)
            if item:
                WorkReportWriter._move_item_to_next_step(
                    helper,
                    order_id,
                    current_op,
                    item,
                    user_id,
                    user_name,
                    serial_no,
                    db,
                )

        helper.update_order_completed(order_id, db=db)
        order_info = helper.get_order_quantity(order_id, db=db)
        if order_info:
            completed_cnt = helper.count_completed_items(order_id, db=db)
            if completed_cnt >= order_info["quantity"]:
                helper.complete_order(order_id, db=db)

    @staticmethod
    def _move_item_to_next_step(helper, order_id, current_op, item, user_id, user_name,
                                serial_no, db):
        current_seq = current_op["seq_order"]
        next_op = helper.find_next_process(order_id, current_seq, db=db)
        item_version = item["version"] or 1
        if next_op:
            cur = helper.advance_product_item(
                item["id"],
                next_op["process_id"],
                item_version,
                db=db,
            )
            if cur.rowcount == 0:
                raise ValueError(f"序列号 {serial_no} 已被其他操作修改，请刷新后重试")
            return

        cur = helper.complete_product_item(item["id"], item_version, db=db)
        if cur.rowcount == 0:
            raise ValueError(f"序列号 {serial_no} 已被其他操作修改，请刷新后重试")
        InventoryAutoInboundService.auto_inbound_for_item(
            order_id,
            user_id,
            user_name,
            serial_no,
            db=db,
        )

    @staticmethod
    def _write_scrap_report(helper, order_id, process_id, user_id, quantity, remark, db):
        reason = remark or ""
        helper.insert_scrap_record(order_id, process_id, user_id, quantity, reason, db=db)
        op = helper.get_order_process(order_id, process_id, db=db)
        if op:
            new_scrapped = (op["scrapped"] or 0) + quantity
            helper.update_order_process_scrapped(order_id, process_id, new_scrapped, db=db)
        helper.update_order_scrapped(order_id, db=db)

    @staticmethod
    def _write_rework_report(helper, order_id, process_id, user_id, quantity, remark, db):
        reason = remark or ""
        helper.insert_rework_record(order_id, process_id, user_id, quantity, reason, db=db)
        op = helper.get_order_process(order_id, process_id, db=db)
        if op:
            new_rework = (op["rework"] or 0) + quantity
            helper.update_order_process_rework(order_id, process_id, new_rework, db=db)
        helper.update_order_rework(order_id, db=db)
