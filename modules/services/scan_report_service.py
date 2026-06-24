"""Scan report orchestration facade.

This service keeps route-level report submission orchestration out of
ScanHelperService so the helper remains a lower-level data access seam.
"""
from modules.services.scan_helper_service import ScanHelperService
from modules.services.scan_validation_service import ScanValidationService
from modules.services.work_report_writer import WorkReportWriter


class ScanReportService:
    """Coordinates validation, approval checks, and transactional report writes."""

    @staticmethod
    def validate_report(order_id, process_id, user, quantity, serial_no, report_type):
        return ScanValidationService.validate_report(
            order_id,
            process_id,
            user,
            quantity,
            serial_no,
            report_type,
        )

    @staticmethod
    def check_approval_required(process_id):
        return ScanHelperService.check_approval_required(process_id) is not None

    @staticmethod
    def execute_report_write(report_type, order_id, process_id, user_id, user_name,
                             quantity, remark, serial_no, need_approval, record_type="normal"):
        return WorkReportWriter.execute_report_write(
            report_type,
            order_id,
            process_id,
            user_id,
            user_name,
            quantity,
            remark,
            serial_no,
            need_approval,
            record_type=record_type,
        )
