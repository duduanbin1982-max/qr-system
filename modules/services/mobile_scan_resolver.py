"""Mobile scan code parsing and target resolution."""

import json
from dataclasses import dataclass

from modules.services.scan_helper_service import ScanHelperService


@dataclass(frozen=True)
class MobileScanTarget:
    order: object
    item_info: dict | None
    serial_no: str | None


class MobileScanResolver:
    """Resolves a scanned text payload into an order, optional item, and serial number."""

    @staticmethod
    def extract_code(data):
        code = (data.get("code") or "").strip()
        if code:
            return code
        return (data.get("qr_text") or "").strip()

    @staticmethod
    def parse_code(code):
        try:
            parsed = json.loads(code)
        except (json.JSONDecodeError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def resolve(code):
        parsed = MobileScanResolver.parse_code(code)
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

        return MobileScanTarget(order=order, item_info=item_info, serial_no=serial_no)
