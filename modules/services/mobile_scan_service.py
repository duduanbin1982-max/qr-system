"""Mobile scan target resolution and response shaping."""

import json

from modules.access_policy import has_permission, get_user_process_ids
from modules.services.scan_helper_service import ScanHelperService


class MobileScanService:
    """Builds the mobile scan payload without route-level branching noise."""

    @staticmethod
    def _extract_code(data):
        code = (data.get("code") or "").strip()
        if code:
            return code
        return (data.get("qr_text") or "").strip()

    @staticmethod
    def _parse_code(code):
        try:
            parsed = json.loads(code)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _resolve_target(code):
        parsed = MobileScanService._parse_code(code)
        order_id = parsed.get("order_id") if parsed else None
        serial_no = parsed.get("serial_no") if parsed else None

        order = ScanHelperService.get_order(order_id) if order_id else None
        item_info = None
        if not order:
            order = ScanHelperService.get_order_by_no(code)

        if serial_no:
            item = ScanHelperService.get_product_item(serial_no)
            if item:
                item_info = dict(item)
                if not order:
                    order = ScanHelperService.get_order(item["order_id"])

        if not order:
            item = ScanHelperService.get_product_item(code)
            if item:
                item_info = dict(item)
                serial_no = code
                order = ScanHelperService.get_order(item["order_id"])

        return order, item_info, serial_no

    @staticmethod
    def _current_process(order_data, item_info):
        for proc in order_data["processes"]:
            if proc.get("status") != "completed":
                return MobileScanService._process_summary(proc, order_data)
        if item_info and item_info.get("current_process_id"):
            return MobileScanService._current_process_for_item(order_data, item_info)
        return None

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

        if item_info:
            return {
                "order": order_data,
                "item": MobileScanService._attach_item_qr_data(item_info),
            }, 200
        return {"order": order_data}, 200
