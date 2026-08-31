"""Scan report orchestration facade.

This service keeps route-level report submission orchestration out of
ScanHelperService so the helper remains a lower-level data access seam.
"""
from modules.services.scan_helper_service import ScanHelperService
from modules.services.scan_validation_service import ScanValidationService
from modules.services.work_report_writer import WorkReportWriter
from modules.services.serial_backfill_service import SerialBackfillService
from modules.domain.work_report import WorkReportCommand


class ScanReportService:
    """Coordinates validation, approval checks, and transactional report writes."""

    @staticmethod
    def validate_report(
        order_id,
        process_id,
        user,
        quantity,
        serial_no,
        report_type,
        serial_backfill=False,
    ):
        return ScanValidationService.validate_report(
            order_id,
            process_id,
            user,
            quantity,
            serial_no,
            report_type,
            serial_backfill=serial_backfill,
        )

    @staticmethod
    def prepare_submission(data, user):
        serial_backfill = data.get("serial_backfill") is True
        if not serial_backfill:
            data["report_source"] = "standard"
            return False
        normalized = SerialBackfillService.validate_submission(
            data.get("order_id"),
            data.get("process_id"),
            (data.get("serial_no") or "").strip() or None,
            user,
            data.get("report_type", "normal"),
        )
        data.update(normalized)
        data["report_source"] = "serial_backfill"
        return True

    @staticmethod
    def check_approval_required(process_id, order_id=None):
        return ScanHelperService.check_approval_required(process_id, order_id=order_id) is not None

    @staticmethod
    def execute_report_write(command):
        return WorkReportWriter.execute_report_write(command)

    @staticmethod
    def build_command(data, user, quantity, serial_no, need_approval):
        return WorkReportCommand.from_submission(
            data,
            user,
            quantity,
            serial_no,
            need_approval,
        )
