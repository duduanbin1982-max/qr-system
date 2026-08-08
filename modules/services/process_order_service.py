"""Process-order policy shared by scan presentation and report validation."""

from modules.domain.process_reporting import (
    OUT_OF_ORDER,
    SEQUENTIAL,
    ProcessReportingPolicy,
)
from modules.domain.process_reporting_models import ProcessReportingRequest
from modules.services.process_reporting_presenter import ProcessReportingPresenter
from modules.setting_reader import get_setting


class ProcessOrderService:
    SEQUENTIAL = SEQUENTIAL
    OUT_OF_ORDER = OUT_OF_ORDER
    setting_reader = None

    @classmethod
    def _get_setting(cls, key, default=None):
        """Read configuration through an overridable boundary."""
        reader = vars(cls).get("setting_reader") or get_setting
        return reader(key, default)

    @classmethod
    def policy(cls):
        mode = cls._get_setting("process_order_mode", cls.SEQUENTIAL)
        if mode not in {cls.SEQUENTIAL, cls.OUT_OF_ORDER}:
            mode = cls.SEQUENTIAL
        configured_previous_limit = cls._get_setting("limit_by_prev_process", "1") == "1"
        return {
            "mode": mode,
            "configured_previous_limit": configured_previous_limit,
            "effective_previous_limit": (
                configured_previous_limit and mode == cls.SEQUENTIAL
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
        request = ProcessReportingRequest(
            order_data=order_data,
            policy=cls.policy(),
            item_info=item_info,
            serial_no=serial_no,
            user_process_ids=user_process_ids,
            preferred_process_ids=preferred_process_ids,
            serial_backfill_available=serial_backfill_available,
            serial_report_states=serial_report_states,
        )
        result = ProcessReportingPolicy.evaluate(request)
        result.attach_to(order_data)
        return ProcessReportingPresenter.attach_messages(order_data, result)
