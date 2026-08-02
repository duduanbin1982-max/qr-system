"""Process reportability orchestration with compatibility adapters."""

from modules.domain.process_eligibility import ProcessEligibilityPolicy
from modules.domain.process_reporting_models import (
    OUT_OF_ORDER,
    SEQUENTIAL,
    ProcessReportingRequest,
    ProcessReportingResult,
    ReportingContext,
)
from modules.domain.process_selection import ProcessSelectionPolicy


class ProcessReportingPolicy:
    @staticmethod
    def is_completed(process, order_quantity):
        return ProcessEligibilityPolicy.is_completed(process, order_quantity)

    @staticmethod
    def summary(process, order_quantity):
        if not process:
            return None
        return {
            "process_id": process["process_id"],
            "process_name": process.get("process_name", ""),
            "completed": process.get("completed") or 0,
            "total": process.get("total_quantity", order_quantity),
        }

    @classmethod
    def evaluate(cls, request):
        context = ReportingContext.from_request(request)
        eligibility = ProcessEligibilityPolicy.evaluate(
            request.order_data.get("processes", ()), context
        )
        backfill = ProcessSelectionPolicy.select_backfill(
            eligibility.processes, context
        )
        selection = ProcessSelectionPolicy.select_current(
            eligibility.processes, eligibility.reportable, context
        )
        selectable_ids = {
            process.get("process_id") for process in selection.pool if process
        }
        processes = tuple(
            {
                **process,
                "position_reportable": bool(
                    process.get("normal_reportable")
                    and process.get("process_id") in selectable_ids
                ),
            }
            for process in eligibility.processes
        )
        return ProcessReportingResult(
            processes=processes,
            current_process=cls.summary(selection.selected, context.order_quantity),
            context=context,
            backfill=backfill,
            selection=selection,
        )

    @classmethod
    def attach_context(
        cls,
        order_data,
        policy,
        item_info=None,
        serial_no=None,
        user_process_ids=None,
        preferred_process_ids=None,
        serial_backfill_available=False,
        serial_report_states=None,
    ):
        request = ProcessReportingRequest(
            order_data=order_data,
            policy=policy,
            item_info=item_info,
            serial_no=serial_no,
            user_process_ids=user_process_ids,
            preferred_process_ids=preferred_process_ids,
            serial_backfill_available=serial_backfill_available,
            serial_report_states=serial_report_states,
        )
        return cls.evaluate(request).attach_to(order_data)
