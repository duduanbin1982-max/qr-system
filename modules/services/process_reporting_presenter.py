"""Presentation text for process-reporting selection results."""


SERIAL_BACKFILL_MESSAGES = {
    "": "",
    "active_position_required": "请先选择当前岗位",
    "unique_position": "已按当前岗位自动匹配唯一可补报工序",
    "multiple_position": "当前岗位有多个可补报工序，请选择本次工序",
    "position_empty": "当前岗位没有可补报工序，请切换岗位",
}

PROCESS_SELECTION_MESSAGES = {
    "": "",
    "position_fallback": "当前岗位暂无匹配的可报工序，已按个人补充授权提供候选",
    "position_empty": "当前岗位暂无可报工序",
}


class ProcessReportingPresenter:
    @staticmethod
    def attach_messages(order_data, result):
        order_data["serial_backfill_message"] = SERIAL_BACKFILL_MESSAGES[
            result.backfill.message_key
        ]
        order_data["process_selection_message"] = PROCESS_SELECTION_MESSAGES[
            result.selection.message_key
        ]
        return order_data
