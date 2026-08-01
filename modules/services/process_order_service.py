"""Process-order policy shared by scan presentation and report validation."""

from modules.domain.process_reporting import (
    OUT_OF_ORDER,
    SEQUENTIAL,
    ProcessReportingPolicy,
)
from modules.setting_reader import get_setting


class ProcessOrderService:
    SEQUENTIAL = SEQUENTIAL
    OUT_OF_ORDER = OUT_OF_ORDER

    @staticmethod
    def policy():
        mode = get_setting("process_order_mode", ProcessOrderService.SEQUENTIAL)
        if mode not in {ProcessOrderService.SEQUENTIAL, ProcessOrderService.OUT_OF_ORDER}:
            mode = ProcessOrderService.SEQUENTIAL
        configured_previous_limit = get_setting("limit_by_prev_process", "1") == "1"
        return {
            "mode": mode,
            "configured_previous_limit": configured_previous_limit,
            "effective_previous_limit": (
                configured_previous_limit and mode == ProcessOrderService.SEQUENTIAL
            ),
        }

    @staticmethod
    def _is_completed(process, order_quantity):
        return ProcessReportingPolicy.is_completed(process, order_quantity)

    @staticmethod
    def _summary(process, order_quantity):
        return ProcessReportingPolicy.summary(process, order_quantity)

    @classmethod
    def attach_context(
        cls,
        order_data,
        item_info=None,
        serial_no=None,
        user_process_ids=None,
        preferred_process_ids=None,
        serial_backfill_available=False,
        serial_report_states=None,
    ):
        return ProcessReportingPolicy.attach_context(
            order_data,
            cls.policy(),
            item_info=item_info,
            serial_no=serial_no,
            user_process_ids=user_process_ids,
            preferred_process_ids=preferred_process_ids,
            serial_backfill_available=serial_backfill_available,
            serial_report_states=serial_report_states,
        )
