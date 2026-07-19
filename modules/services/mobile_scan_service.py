"""Mobile scan target resolution and response shaping."""

import json

from modules.services.access_policy_service import has_permission, get_user_process_ids
from modules.services.mobile_scan_resolver import MobileScanResolver
from modules.services.scan_helper_service import ScanHelperService
from modules.services.handoff_review_service import HandoffReviewService
from modules.services.order_focus_service import OrderFocusService


class MobileScanService:
    """Builds the mobile scan payload without route-level branching noise."""

    @staticmethod
    def _extract_code(data):
        return MobileScanResolver.extract_code(data)

    @staticmethod
    def _parse_code(code):
        return MobileScanResolver.parse_code(code)

    @staticmethod
    def _resolve_target(code):
        target = MobileScanResolver.resolve(code)
        return target.order, target.item_info, target.serial_no

    @staticmethod
    def _current_process(order_data, item_info):
        for proc in order_data["processes"]:
            if not MobileScanService._is_process_completed(proc, order_data):
                return MobileScanService._process_summary(proc, order_data)
        if item_info and item_info.get("current_process_id"):
            return MobileScanService._current_process_for_item(order_data, item_info)
        return None

    @staticmethod
    def _is_process_completed(proc, order_data):
        if proc.get("status") == "completed":
            return True
        total = proc.get("total_quantity", order_data.get("quantity", 0)) or 0
        return total > 0 and (proc.get("completed") or 0) >= total

    @staticmethod
    def _current_process_for_item(order_data, item_info):
        item_process_id = item_info["current_process_id"]
        for proc in order_data["processes"]:
            if proc["process_id"] == item_process_id:
                return MobileScanService._process_summary(proc, order_data)
        return None

    @staticmethod
    def _process_summary(proc, order_data):
        return {
            "process_id": proc["process_id"],
            "process_name": proc.get("process_name", ""),
            "completed": proc.get("completed") or 0,
            "total": proc.get("total_quantity", order_data.get("quantity", 0)),
        }

    @staticmethod
    def _attach_item_qr_data(item_info):
        if not item_info:
            return None
        try:
            item_info["qr_data"] = json.loads(item_info.get("qr_content") or "{}")
        except (json.JSONDecodeError, TypeError):
            item_info["qr_data"] = {}
        return item_info

    @staticmethod
    def _handoff_pending_for_scan(order_id, user, serial_no):
        if not user or not user.get("id"):
            return {"required": False, "reason": "未登录"}
        try:
            return HandoffReviewService.pending_latest_evaluator_work(
                order_id, user.get("id"), serial_no or ""
            )
        except Exception as exc:
            return {"required": False, "reason": f"交接评价检查失败: {exc}"}

    @staticmethod
    def scan(data, user):
        code = MobileScanService._extract_code(data)
        if not code:
            return {"error": "请扫描二维码"}, 400

        order, item_info, serial_no = MobileScanService._resolve_target(code)
        if not order:
            return {"error": f"未找到订单或产品: {code}"}, 404

        if not serial_no:
            order_preview = dict(order)
            qr_mode = (order_preview.get("qr_mode") or "").strip()
            has_items = bool(ScanHelperService.get_product_items_by_order(order_preview["id"]))
            if (qr_mode == "serial" or has_items) and not has_permission(user, "quality:view"):
                return {"error": "此订单为序列号模式，请扫描工件二维码"}, 400

        order_data = dict(order)
        if order_data.get("status") == "completed":
            return {"error": "订单已完成并归档，如需继续报工请先重新打开订单"}, 400

        if not ScanHelperService.check_order_scope(order_data["id"], get_user_process_ids(user)):
            return {"error": "您无权查看此订单"}, 403

        order_data["processes"] = [
            dict(process) for process in ScanHelperService.get_order_processes(order_data["id"])
        ]
        order_data["records"] = [
            dict(record) for record in ScanHelperService.get_work_records(order_data["id"], limit=20)
        ]

        if serial_no and item_info and item_info.get("current_process_id"):
            order_data["current_process"] = MobileScanService._current_process_for_item(order_data, item_info)
        else:
            order_data["current_process"] = MobileScanService._current_process(order_data, item_info)

        handoff_pending = MobileScanService._handoff_pending_for_scan(
            order_data["id"], user, serial_no or ""
        )
        completion_focus_warning = OrderFocusService.scan_priority_warning(
            order_data, order_data.get("current_process"), user=user
        )
        if completion_focus_warning:
            order_data["completion_focus_warning"] = completion_focus_warning

        if item_info:
            return {
                "order": order_data,
                "item": MobileScanService._attach_item_qr_data(item_info),
                "handoff_pending": handoff_pending,
                "completion_focus_warning": completion_focus_warning,
            }, 200
        return {
            "order": order_data,
            "handoff_pending": handoff_pending,
            "completion_focus_warning": completion_focus_warning,
        }, 200
