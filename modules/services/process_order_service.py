"""Process-order policy shared by scan presentation and report validation."""

from modules.setting_reader import get_setting


class ProcessOrderService:
    SEQUENTIAL = "sequential"
    OUT_OF_ORDER = "out_of_order"

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
        if process.get("status") == "completed":
            return True
        total = process.get("total_quantity", order_quantity) or 0
        return total > 0 and (process.get("completed") or 0) >= total

    @staticmethod
    def _summary(process, order_quantity):
        if not process:
            return None
        return {
            "process_id": process["process_id"],
            "process_name": process.get("process_name", ""),
            "completed": process.get("completed") or 0,
            "total": process.get("total_quantity", order_quantity),
        }

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
        order_quantity = int(order_data.get("quantity") or 0)
        processes = sorted(
            [dict(process) for process in order_data.get("processes", [])],
            key=lambda process: (process.get("seq_order") or 0, process.get("id") or 0),
        )
        policy = cls.policy()
        serial_mode = bool(serial_no or item_info)
        item_process_id = item_info.get("current_process_id") if item_info else None
        preferred_scope_supplied = preferred_process_ids is not None
        preferred_set = set(preferred_process_ids or [])
        prior_started = True
        reportable = []
        serial_states = {}
        if serial_mode and serial_no:
            for row in serial_report_states or []:
                serial_states.setdefault(int(row["process_id"]), row["status"])

        for index, process in enumerate(processes):
            process_id = process.get("process_id")
            completed = int(process.get("completed") or 0)
            total = int(process.get("total_quantity", order_quantity) or order_quantity)
            remaining = max(0, total - completed)
            authorized = user_process_ids is None or process_id in user_process_ids
            completed_process = cls._is_completed(process, order_quantity)
            max_quantity = remaining
            serial_report_status = serial_states.get(int(process_id or 0), "unreported")

            if serial_mode:
                sequence_allowed = bool(
                    item_process_id
                    and process_id == item_process_id
                    and serial_report_status == "unreported"
                )
                max_quantity = 1 if sequence_allowed and not completed_process else 0
            elif policy["mode"] == cls.OUT_OF_ORDER:
                sequence_allowed = True
            else:
                sequence_allowed = prior_started
                if policy["effective_previous_limit"] and index > 0:
                    previous_completed = int(processes[index - 1].get("completed") or 0)
                    max_quantity = min(remaining, max(0, previous_completed - completed))

            normal_reportable = bool(
                authorized and sequence_allowed and not completed_process and max_quantity > 0
            )
            process.update({
                "process_authorized": authorized,
                "normal_reportable": normal_reportable,
                "max_report_quantity": max_quantity if normal_reportable else 0,
                "position_preferred": (
                    not preferred_scope_supplied or process_id in preferred_set
                ),
                "serial_report_status": serial_report_status if serial_mode else None,
                "serial_backfill_reportable": bool(
                    serial_mode
                    and serial_backfill_available
                    and preferred_scope_supplied
                    and process_id in preferred_set
                    and authorized
                    and process_id != item_process_id
                    and serial_report_status == "unreported"
                    and not completed_process
                    and remaining > 0
                ),
            })
            if normal_reportable:
                reportable.append(process)
            processes[index] = process
            prior_started = prior_started and (completed > 0 or completed_process)

        serial_backfill_candidates = [
            process for process in processes if process.get("serial_backfill_reportable")
        ]
        if not serial_mode or not serial_backfill_available:
            serial_backfill_selection_source = "none"
            serial_backfill_message = ""
        elif not preferred_scope_supplied:
            serial_backfill_selection_source = "none"
            serial_backfill_message = "请先选择当前岗位"
        elif len(serial_backfill_candidates) == 1:
            serial_backfill_selection_source = "position_auto"
            serial_backfill_message = "已按当前岗位自动匹配唯一可补报工序"
        elif serial_backfill_candidates:
            serial_backfill_selection_source = "position_manual"
            serial_backfill_message = "当前岗位有多个可补报工序，请选择本次工序"
        else:
            serial_backfill_selection_source = "none"
            serial_backfill_message = "当前岗位没有可补报工序，请切换岗位"

        position_candidates = [
            process
            for process in reportable
            if process.get("process_id") in preferred_set
        ]
        position_process_match = None
        selection_message = ""

        if serial_mode and item_process_id:
            selected = next(
                (process for process in processes if process.get("process_id") == item_process_id),
                None,
            )
            selection_pool = [selected] if selected else []
            selection_source = "serial_auto"
        elif preferred_scope_supplied and position_candidates:
            selection_pool = position_candidates
            selected = selection_pool[0]
            position_process_match = True
            selection_source = (
                "position_auto" if len(selection_pool) == 1 else "position_manual"
            )
        else:
            selection_pool = reportable
            selected = selection_pool[0] if selection_pool else None
            if preferred_scope_supplied:
                position_process_match = False
                selection_message = (
                    "当前岗位暂无匹配的可报工序，已按个人补充授权提供候选"
                    if reportable
                    else "当前岗位暂无可报工序"
                )
            if not selection_pool:
                selection_source = "none"
            else:
                selection_source = (
                    "authorization_auto"
                    if len(selection_pool) == 1
                    else "authorization_manual"
                )

        selectable_ids = {
            process.get("process_id") for process in selection_pool if process
        }
        for process in processes:
            process["position_reportable"] = bool(
                process.get("normal_reportable")
                and process.get("process_id") in selectable_ids
            )

        order_data["processes"] = processes
        order_data["current_process"] = cls._summary(selected, order_quantity)
        order_data["process_order_mode"] = policy["mode"]
        order_data["process_order_scope"] = "serial_sequential" if serial_mode else "order"
        order_data["serial_backfill_available"] = bool(
            serial_mode and serial_backfill_available
        )
        order_data["serial_backfill_selection_source"] = serial_backfill_selection_source
        order_data["serial_backfill_candidate_count"] = len(serial_backfill_candidates)
        order_data["serial_backfill_message"] = serial_backfill_message
        order_data["limit_by_prev_process_effective"] = policy["effective_previous_limit"]
        order_data["requires_process_selection"] = (
            not serial_mode and len(selection_pool) > 1
        )
        order_data["process_selection_source"] = selection_source
        order_data["position_process_match"] = position_process_match
        order_data["position_candidate_count"] = len(position_candidates)
        order_data["process_selection_message"] = selection_message
        return order_data
