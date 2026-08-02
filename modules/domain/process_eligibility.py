"""Eligibility calculation for normal and serial-backfill reporting."""

from modules.domain.process_reporting_models import (
    OUT_OF_ORDER,
    EligibilityResult,
)


class ProcessEligibilityPolicy:
    @staticmethod
    def is_completed(process, order_quantity):
        if process.get("status") == "completed":
            return True
        total = process.get("total_quantity", order_quantity) or 0
        return total > 0 and (process.get("completed") or 0) >= total

    @classmethod
    def evaluate(cls, raw_processes, context):
        processes = sorted(
            [dict(process) for process in raw_processes],
            key=lambda process: (
                process.get("seq_order") or 0,
                process.get("id") or 0,
            ),
        )
        reportable = []
        prior_started = True

        for index, process in enumerate(processes):
            process_id = process.get("process_id")
            completed = int(process.get("completed") or 0)
            total = int(
                process.get("total_quantity", context.order_quantity)
                or context.order_quantity
            )
            remaining = max(0, total - completed)
            authorized = (
                context.user_process_ids is None
                or process_id in context.user_process_ids
            )
            completed_process = cls.is_completed(process, context.order_quantity)
            serial_status = context.serial_status(process_id)
            max_quantity, sequence_allowed = cls._normal_limit(
                index,
                process,
                processes,
                remaining,
                completed_process,
                serial_status,
                prior_started,
                context,
            )
            normal_reportable = bool(
                authorized
                and sequence_allowed
                and not completed_process
                and max_quantity > 0
            )
            process.update(
                {
                    "process_authorized": authorized,
                    "normal_reportable": normal_reportable,
                    "max_report_quantity": max_quantity if normal_reportable else 0,
                    "position_preferred": (
                        not context.preferred_scope_supplied
                        or process_id in context.preferred_process_ids
                    ),
                    "serial_report_status": (
                        serial_status if context.serial_mode else None
                    ),
                    "serial_backfill_reportable": cls._can_backfill(
                        process_id,
                        authorized,
                        completed_process,
                        remaining,
                        serial_status,
                        context,
                    ),
                }
            )
            if normal_reportable:
                reportable.append(process)
            prior_started = prior_started and (completed > 0 or completed_process)

        return EligibilityResult(tuple(processes), tuple(reportable))

    @staticmethod
    def _normal_limit(
        index,
        process,
        processes,
        remaining,
        completed_process,
        serial_status,
        prior_started,
        context,
    ):
        if context.serial_mode:
            sequence_allowed = bool(
                context.item_process_id
                and process.get("process_id") == context.item_process_id
                and serial_status == "unreported"
            )
            return (1 if sequence_allowed and not completed_process else 0), sequence_allowed
        if context.mode == OUT_OF_ORDER:
            return remaining, True
        max_quantity = remaining
        if context.effective_previous_limit and index > 0:
            previous_completed = int(processes[index - 1].get("completed") or 0)
            completed = int(process.get("completed") or 0)
            max_quantity = min(remaining, max(0, previous_completed - completed))
        return max_quantity, prior_started

    @staticmethod
    def _can_backfill(
        process_id,
        authorized,
        completed_process,
        remaining,
        serial_status,
        context,
    ):
        return bool(
            context.serial_mode
            and context.serial_backfill_available
            and context.preferred_scope_supplied
            and process_id in context.preferred_process_ids
            and authorized
            and process_id != context.item_process_id
            and serial_status == "unreported"
            and not completed_process
            and remaining > 0
        )
