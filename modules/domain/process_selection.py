"""Selection policies for serial backfill and active-position reporting."""

from modules.domain.process_reporting_models import (
    BackfillSelection,
    ProcessSelection,
)


class ProcessSelectionPolicy:
    @staticmethod
    def select_backfill(processes, context):
        candidates = tuple(
            process
            for process in processes
            if process.get("serial_backfill_reportable")
        )
        if not context.serial_mode or not context.serial_backfill_available:
            return BackfillSelection(candidates, "none", "")
        if not context.preferred_scope_supplied:
            return BackfillSelection(candidates, "none", "active_position_required")
        if len(candidates) == 1:
            return BackfillSelection(candidates, "position_auto", "unique_position")
        if candidates:
            return BackfillSelection(candidates, "position_manual", "multiple_position")
        return BackfillSelection(candidates, "none", "position_empty")

    @staticmethod
    def select_current(processes, reportable, context):
        position_candidates = tuple(
            process
            for process in reportable
            if process.get("process_id") in context.preferred_process_ids
        )
        if context.serial_mode and context.item_process_id:
            selected = next(
                (
                    process
                    for process in processes
                    if process.get("process_id") == context.item_process_id
                ),
                None,
            )
            return ProcessSelection(
                selected,
                (selected,) if selected else (),
                "serial_auto",
                None,
                position_candidates,
                "",
            )
        if context.preferred_scope_supplied and position_candidates:
            source = (
                "position_auto"
                if len(position_candidates) == 1
                else "position_manual"
            )
            return ProcessSelection(
                position_candidates[0],
                position_candidates,
                source,
                True,
                position_candidates,
                "",
            )

        pool = tuple(reportable)
        source = "none"
        if pool:
            source = "authorization_auto" if len(pool) == 1 else "authorization_manual"
        message_key = ""
        position_match = None
        if context.preferred_scope_supplied:
            position_match = False
            message_key = "position_fallback" if pool else "position_empty"
        return ProcessSelection(
            pool[0] if pool else None,
            pool,
            source,
            position_match,
            position_candidates,
            message_key,
        )
