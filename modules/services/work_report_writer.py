"""Transactional writer for scan work reports."""
import logging
from datetime import datetime

from modules.services.material_service import MaterialService
from modules.repositories.scan_repository import ScanRepository
from modules.services import BaseService
from modules.services.inventory_auto_inbound_service import InventoryAutoInboundService
from modules.services.order_completion_service import OrderCompletionService


_logger = logging.getLogger(__name__)


class WorkReportWriter:
    """Persists normal, scrap, and rework reports inside one transaction."""

    material_service = None
    scan_repository = None
    inventory_auto_inbound_service = None
    order_completion_service = None
    scan_helper_service = None
    quality_management_service = None
    quality_evaluation_service = None
    quality_event_service = None
    unit_of_work = None

    @classmethod
    def _material_service(cls):
        return cls.material_service or MaterialService

    @classmethod
    def _scan_repository(cls):
        return cls.scan_repository or ScanRepository

    @classmethod
    def _inventory_auto_inbound_service(cls):
        return cls.inventory_auto_inbound_service or InventoryAutoInboundService

    @classmethod
    def _order_completion_service(cls):
        return cls.order_completion_service or OrderCompletionService

    @classmethod
    def _scan_helper_service(cls):
        if cls.scan_helper_service:
            return cls.scan_helper_service
        from modules.services.scan_helper_service import ScanHelperService
        return ScanHelperService

    @classmethod
    def _quality_management_service(cls):
        if cls.quality_management_service:
            return cls.quality_management_service
        from modules.services.quality_management_service import QualityManagementService
        return QualityManagementService

    @classmethod
    def _quality_evaluation_service(cls):
        if cls.quality_evaluation_service:
            return cls.quality_evaluation_service
        from modules.services.process_quality_evaluation_service import (
            ProcessQualityEvaluationService,
        )
        return ProcessQualityEvaluationService

    @classmethod
    def _quality_event_service(cls):
        if cls.quality_event_service:
            return cls.quality_event_service
        from modules.services.performance_quality_event_service import (
            PerformanceQualityEventService,
        )
        return PerformanceQualityEventService

    @classmethod
    def _unit_of_work(cls):
        return cls.unit_of_work or BaseService

    @staticmethod
    def execute_report_write(command):
        """共享报工写入逻辑。整个方法在事务中执行，全部成功或全部回滚。"""
        scan_helper_service = WorkReportWriter._scan_helper_service()

        with WorkReportWriter._unit_of_work().transaction() as db:
            WorkReportWriter._check_duplicates(
                scan_helper_service,
                command.report_type,
                command.order_id,
                command.process_id,
                command.user_id,
                command.serial_no,
                db,
            )
            current_op = WorkReportWriter._load_current_operation(
                scan_helper_service,
                command.order_id,
                command.process_id,
                db,
            )

            if command.report_type == "normal":
                WorkReportWriter._check_normal_limits(
                    scan_helper_service,
                    command.order_id,
                    current_op,
                    command.quantity,
                    command.user_id,
                    db,
                    skip_sequence=command.report_source == "serial_backfill",
                )
                WorkReportWriter._write_normal_report(
                    scan_helper_service,
                    command,
                    db,
                )
            elif command.report_type == "scrap":
                WorkReportWriter._write_scrap_report(
                    scan_helper_service,
                    command.order_id,
                    command.process_id,
                    command.user_id,
                    command.quantity,
                    command.remark,
                    db,
                )
            elif command.report_type == "rework":
                WorkReportWriter._write_rework_report(
                    command.order_id,
                    command.process_id,
                    command.user_id,
                    command.quantity,
                    command.remark,
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
    def _check_normal_limits(
        helper,
        order_id,
        current_op,
        quantity,
        user_id,
        db,
        skip_sequence=False,
    ):
        WorkReportWriter._quality_evaluation_service().assert_required_tasks_completed(
            user_id, db
        )
        if not skip_sequence:
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

        WorkReportWriter._quality_management_service().assert_report_allowed(
            order_id, current_op.get("process_id"), db=db
        )

        if skip_sequence:
            if (current_op.get("completed", 0) or 0) + quantity > (order.get("quantity", 0) or 0):
                raise ValueError("报工数量超出订单总量限制")
        else:
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
    def _write_normal_report(helper, command, db):
        work_status = "pending" if command.need_approval else "approved"
        wr_id = helper.insert_work_record(
            command.order_id,
            command.process_id,
            command.user_id,
            "normal",
            command.effective_quantity,
            command.remark,
            work_status,
            command.serial_no,
            command.report_source,
            command.actual_completed_at,
            command.backfill_reason,
            command.submit_position_id,
            command.submit_position_name,
            db=db,
        )

        if command.need_approval:
            helper.insert_approval_record(wr_id, db=db)

        if work_status == "approved":
                WorkReportWriter.apply_approved_normal_report(
                    command,
                    db,
                    wr_id,
                    validate_policy=False,
                )

    @staticmethod
    def apply_approved_normal_report(command, db, work_record_id=None, validate_policy=True):
        scan_helper_service = WorkReportWriter._scan_helper_service()
        quality_management_service = WorkReportWriter._quality_management_service()
        quality_evaluation_service = WorkReportWriter._quality_evaluation_service()

        if validate_policy:
            current_op = WorkReportWriter._load_current_operation(
                scan_helper_service,
                command.order_id,
                command.process_id,
                db,
            )
            WorkReportWriter._check_normal_limits(
                scan_helper_service,
                command.order_id,
                current_op,
                command.effective_quantity,
                command.user_id,
                db,
                skip_sequence=command.report_source == "serial_backfill",
            )
        else:
            quality_evaluation_service.assert_required_tasks_completed(command.user_id, db)
            quality_management_service.assert_report_allowed(
                command.order_id, command.process_id, db=db
            )

        WorkReportWriter._apply_approved_normal_effects(
            scan_helper_service,
            command.order_id,
            command.process_id,
            command.user_id,
            command.user_name,
            command.effective_quantity,
            command.serial_no,
            db,
            work_record_id,
        )
        if command.serial_no:
            WorkReportWriter._reconcile_serial_item(
                scan_helper_service,
                command.order_id,
                command.user_id,
                command.user_name,
                command.serial_no,
                db,
            )
            quality_evaluation_service.generate_tasks(command, work_record_id, db)
            if scan_helper_service.has_approved_serial_backfill(
                command.order_id, command.serial_no, db=db
            ):
                WorkReportWriter._rebuild_serial_quality_tasks(
                    scan_helper_service,
                    command.order_id,
                    command.serial_no,
                    quality_evaluation_service,
                    db,
                )
        else:
            quality_evaluation_service.generate_tasks(command, work_record_id, db)
        quality_management_service.generate_for_report(
            command.order_id,
            command.process_id,
            work_record_id,
            command.serial_no,
            command.user_id,
            db,
        )
        WorkReportWriter._order_completion_service().reconcile(
            command.order_id,
            trigger="approved_work_report",
            actor_id=command.user_id,
            db=db,
        )

    @staticmethod
    def _apply_approved_normal_effects(helper, order_id, process_id, user_id, user_name,
                                       quantity_local, serial_no, db, work_record_id=None):
        op = helper.get_order_process(order_id, process_id, db=db)
        if op:
            new_completed = (op["completed"] or 0) + quantity_local
            helper.update_order_process_completed(order_id, process_id, new_completed, db=db)

        WorkReportWriter._material_service().deduct_for_process(
            order_id,
            process_id,
            quantity_local,
            user_id,
            user_name,
            db=db,
            work_record_id=work_record_id,
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
    def _auto_inbound_last_non_serial(helper, order_id, process_id, user_id, user_name, db):
        order_status = WorkReportWriter._scan_repository().find_order_status(
            order_id, db=db
        )
        if order_status and order_status["status"] != "completed":
            if helper.is_last_process(order_id, process_id, db=db):
                WorkReportWriter._inventory_auto_inbound_service().auto_inbound_for_item(
                    order_id,
                    user_id,
                    user_name,
                    serial_no=None,
                    db=db,
                )

    @staticmethod
    def _reconcile_serial_item(helper, order_id, user_id, user_name, serial_no, db):
        item = helper.get_product_item(serial_no, db=db)
        if not item:
            return
        next_op = helper.find_first_unreported_serial_process(order_id, serial_no, db=db)
        item_version = item["version"] or 1
        if next_op:
            if (
                item["status"] == "in_progress"
                and int(item["current_process_id"] or 0) == int(next_op["process_id"])
            ):
                return
            cur = helper.set_product_item_current_process(
                item["id"],
                next_op["process_id"],
                item_version,
                db=db,
            )
            if cur.rowcount == 0:
                raise ValueError(f"序列号 {serial_no} 已被其他操作修改，请刷新后重试")
            return

        if item["status"] == "completed":
            return
        cur = helper.complete_product_item(item["id"], item_version, db=db)
        if cur.rowcount == 0:
            raise ValueError(f"序列号 {serial_no} 已被其他操作修改，请刷新后重试")
        WorkReportWriter._inventory_auto_inbound_service().auto_inbound_for_item(
            order_id,
            user_id,
            user_name,
            serial_no,
            db=db,
        )

    @staticmethod
    def _rebuild_serial_quality_tasks(helper, order_id, serial_no, service, db):
        from modules.domain.work_report import WorkReportCommand

        for row in helper.list_approved_serial_work_records(order_id, serial_no, db=db):
            record = dict(row)
            service.generate_tasks(
                WorkReportCommand.from_approved_record(record),
                record["id"],
                db,
            )

    @staticmethod
    def _write_scrap_report(helper, order_id, process_id, user_id, quantity, remark, db):
        reason = remark or ""
        scrap_id = helper.insert_scrap_record(
            order_id, process_id, user_id, quantity, reason, db=db
        )
        WorkReportWriter._quality_event_service().record_event(
            event_type="scrap",
            source_type="scrap_record",
            source_id=scrap_id,
            quantity=quantity,
            order_id=order_id,
            process_id=process_id,
            user_id=user_id,
            snapshot={"reason": reason},
            db=db,
        )
        op = helper.get_order_process(order_id, process_id, db=db)
        if op:
            new_scrapped = (op["scrapped"] or 0) + quantity
            helper.update_order_process_scrapped(order_id, process_id, new_scrapped, db=db)
        helper.update_order_scrapped(order_id, db=db)

    @staticmethod
    def _write_rework_report(order_id, process_id, user_id, quantity, remark, db):
        from modules.services.rework_service import ReworkService

        ReworkService.create_rework(
            order_id,
            process_id,
            user_id,
            quantity,
            remark,
            db=db,
            reject_recent_duplicate=True,
        )
