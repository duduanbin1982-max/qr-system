"""Mobile scan target resolution and response shaping."""

import json

from modules.services.access_policy_service import has_permission, get_user_process_ids
from modules.services.mobile_scan_resolver import MobileScanResolver
from modules.services.scan_helper_service import ScanHelperService
from modules.services.process_quality_evaluation_service import ProcessQualityEvaluationService
from modules.services.order_focus_service import OrderFocusService
from modules.services.process_order_service import ProcessOrderService
from modules.services.active_position_service import ActivePositionService
from modules.services.serial_backfill_service import SerialBackfillService


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
    def _attach_item_qr_data(item_info):
        if not item_info:
            return None
        try:
            item_info["qr_data"] = json.loads(item_info.get("qr_content") or "{}")
        except (json.JSONDecodeError, TypeError):
            item_info["qr_data"] = {}
        return item_info

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

        user_process_ids = get_user_process_ids(user)
        if not ScanHelperService.check_order_scope(order_data["id"], user_process_ids):
            return {"error": "您无权查看此订单"}, 403
        position_context = ActivePositionService.get_context(user)
        active_position = position_context.get("active_position")
        preferred_process_ids = (
            active_position.get("process_ids") if active_position else None
        )

        order_data["processes"] = [
            dict(process) for process in ScanHelperService.get_order_processes(order_data["id"])
        ]
        order_data["records"] = [
            dict(record) for record in ScanHelperService.get_work_records(order_data["id"], limit=20)
        ]

        ProcessOrderService.attach_context(
            order_data,
            item_info=item_info,
            serial_no=serial_no,
            user_process_ids=user_process_ids,
            preferred_process_ids=preferred_process_ids,
            serial_backfill_available=SerialBackfillService.is_available(user),
            serial_report_states=(
                ScanHelperService.list_serial_report_states(order_data["id"], serial_no)
                if serial_no else None
            ),
        )
        order_data["active_position"] = active_position

        quality_evaluation_pending_count = ProcessQualityEvaluationService.pending_count(user["id"])
        completion_focus_warning = OrderFocusService.scan_priority_warning(
            order_data, order_data.get("current_process"), user=user
        )
        if completion_focus_warning:
            order_data["completion_focus_warning"] = completion_focus_warning

        if item_info:
            return {
                "order": order_data,
                "item": MobileScanService._attach_item_qr_data(item_info),
                "quality_evaluation_pending_count": quality_evaluation_pending_count,
                "completion_focus_warning": completion_focus_warning,
                "position_context": position_context,
            }, 200
        return {
            "order": order_data,
            "quality_evaluation_pending_count": quality_evaluation_pending_count,
            "completion_focus_warning": completion_focus_warning,
            "position_context": position_context,
        }, 200
