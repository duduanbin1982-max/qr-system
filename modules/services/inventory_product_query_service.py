"""Read-only orchestration for product-group inventory queries."""
from modules import config
from modules.domain.errors import InventoryProductQueryDisabledError, NotFoundError
from modules.repositories.inventory_product_repository import InventoryProductRepository
from modules.domain.errors import InventoryAllocationValidationError
from modules.services import BaseService


class InventoryProductQueryService:
    @staticmethod
    def capabilities():
        return {
            "product_query_enabled": bool(config.INVENTORY_PRODUCT_QUERY_ENABLED),
            "allocation_preview_enabled": bool(config.INVENTORY_ALLOCATION_PREVIEW_ENABLED),
            "cross_order_outbound_enabled": bool(config.INVENTORY_CROSS_ORDER_OUTBOUND_ENABLED),
            "product_threshold_enabled": bool(config.INVENTORY_PRODUCT_THRESHOLD_ENABLED),
        }

    @classmethod
    def list_groups(
        cls, *, keyword="", low_stock=False, location="", quality_status="",
        identity_status="", specifications=None, page=1, limit=50
    ):
        if not config.INVENTORY_PRODUCT_QUERY_ENABLED:
            raise InventoryProductQueryDisabledError("产品编码库存视图尚未启用")
        filters = {
            "keyword": (keyword or "").strip(),
            "low_stock": bool(low_stock),
            "location": (location or "").strip(),
            "quality_status": (quality_status or "").strip(),
            "identity_status": (identity_status or "").strip(),
            "specifications": tuple(specifications or ()),
        }
        size = min(max(int(limit), 1), 200)
        current_page = max(int(page), 1)
        total = InventoryProductRepository.count_groups(filters)
        rows = InventoryProductRepository.list_groups(filters, current_page, size)
        enriched = []
        for row in rows:
            item = dict(row)
            threshold = InventoryProductRepository.get_threshold(item["product_id"])
            if config.INVENTORY_PRODUCT_THRESHOLD_ENABLED and threshold:
                safe_stock = float(threshold["safe_stock"] or 0)
                warning_buffer = float(threshold["warning_buffer"] or 0)
                available = float(item["available_quantity"] or 0)
                item["safe_stock"] = safe_stock
                item["warning_buffer"] = warning_buffer
                item["is_low"] = int(available <= safe_stock and safe_stock > 0)
                item["product_alert_level"] = (
                    "out_of_stock" if available <= 0 else
                    "low" if available <= safe_stock and safe_stock > 0 else
                    "attention" if available <= safe_stock + warning_buffer and (safe_stock + warning_buffer) > 0 else
                    "normal"
                )
            enriched.append(item)
        exceptions = []
        if filters["identity_status"] in {"unresolved", "conflict", "exceptions"}:
            expected_reason = {
                "unresolved": "product_identity_unresolved",
                "conflict": "product_identity_conflict",
            }.get(filters["identity_status"])
            exceptions = [
                dict(row) for row in InventoryProductRepository.list_identity_exceptions(size)
                if expected_reason is None or row["reason"] == expected_reason
            ]
        return {
            "items": enriched,
            "identity_exceptions": exceptions,
            "total": total,
            "page": current_page,
            "limit": size,
        }

    @classmethod
    def filter_options(cls):
        if not config.INVENTORY_PRODUCT_QUERY_ENABLED:
            raise InventoryProductQueryDisabledError("产品编码库存视图尚未启用")
        return InventoryProductRepository.list_filter_options()

    @classmethod
    def get_summary(cls, filters):
        if not config.INVENTORY_PRODUCT_QUERY_ENABLED:
            raise InventoryProductQueryDisabledError("产品编码库存视图尚未启用")
        return InventoryProductRepository.get_group_summary(filters)

    @classmethod
    def set_threshold(cls, product_id, safe_stock, warning_buffer, *, updated_by=None, updated_by_name=""):
        if not config.INVENTORY_PRODUCT_THRESHOLD_ENABLED:
            raise InventoryAllocationValidationError("产品级安全库存尚未启用")
        try:
            safe_stock = float(safe_stock)
            warning_buffer = float(warning_buffer)
        except (TypeError, ValueError):
            raise InventoryAllocationValidationError("安全库存阈值必须为数字")
        if safe_stock < 0 or warning_buffer < 0:
            raise InventoryAllocationValidationError("安全库存阈值不能为负数")
        if not InventoryProductRepository.get_product(product_id):
            raise NotFoundError("产品不存在")
        with BaseService.transaction() as txn:
            InventoryProductRepository.upsert_threshold_txn(
                product_id, safe_stock, warning_buffer, updated_by, updated_by_name, txn
            )
        return dict(InventoryProductRepository.get_threshold(product_id))

    @classmethod
    def get_details(cls, product_id, compatibility_key=""):
        if not config.INVENTORY_PRODUCT_QUERY_ENABLED:
            raise InventoryProductQueryDisabledError("产品编码库存视图尚未启用")
        product = InventoryProductRepository.get_product(product_id)
        if not product:
            raise NotFoundError("产品不存在")
        details = InventoryProductRepository.get_group_details(
            product_id, compatibility_key=(compatibility_key or "").strip()
        )
        return {
            "product": dict(product),
            "product_id": product["product_id"],
            "product_code": product["product_code"],
            "product_name": product["product_name"],
            "aliases": [dict(row) for row in details["aliases"]],
            "compatibility_groups": details["compatibility_groups"],
            "inventory_items": [dict(row) for row in details["inventory_items"]],
            "identity_warnings": details["identity_warnings"],
        }

    @classmethod
    def export_groups(cls, **filters):
        from io import BytesIO
        from openpyxl import Workbook
        from modules.export_utils import style_header, auto_width, THIN_BORDER, CELL_ALIGN
        items = []
        page = 1
        while True:
            result = cls.list_groups(page=page, limit=200, **filters)
            page_items = result.get("items", [])
            items.extend(page_items)
            if not page_items or len(items) >= int(result.get("total", 0)):
                break
            page += 1
        wb = Workbook()
        ws = wb.active
        ws.title = "产品库存汇总"
        headers = ["产品编码", "产品名称", "总库存", "预留", "冻结", "可用", "安全库存", "预警缓冲", "订单数", "批次数", "库位数", "预警等级"]
        style_header(ws, headers)
        for row_index, item in enumerate(items, start=2):
            values = [item.get("product_code", ""), item.get("product_name", ""), item.get("quantity", 0), item.get("reserved_quantity", 0), item.get("frozen_quantity", 0), item.get("available_quantity", 0), item.get("safe_stock", 0), item.get("warning_buffer", 0), item.get("order_count", 0), item.get("lot_count", 0), item.get("location_count", 0), item.get("product_alert_level", "normal")]
            for column, value in enumerate(values, start=1):
                cell = ws.cell(row=row_index, column=column, value=value)
                cell.border = THIN_BORDER
                cell.alignment = CELL_ALIGN
        auto_width(ws)
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        return output

    @classmethod
    def export_details(cls, product_id, compatibility_key=""):
        from io import BytesIO
        from openpyxl import Workbook
        from modules.export_utils import style_header, auto_width, THIN_BORDER, CELL_ALIGN
        payload = cls.get_details(product_id, compatibility_key=compatibility_key)
        wb = Workbook()
        ws = wb.active
        ws.title = "产品库存明细"
        headers = ["产品编码", "产品名称", "订单号", "规格", "质量状态", "数量", "预留", "冻结", "可用", "库位", "批次", "序列号"]
        style_header(ws, headers)
        for row_index, item in enumerate(payload["inventory_items"], start=2):
            values = [payload["product_code"], payload["product_name"], item.get("order_no", ""), item.get("specification", ""), item.get("quality_status", ""), item.get("quantity", 0), item.get("reserved_quantity", 0), item.get("frozen_quantity", 0), item.get("available_quantity", 0), item.get("location", ""), item.get("lot_no", ""), item.get("serial_no", "")]
            for column, value in enumerate(values, start=1):
                cell = ws.cell(row=row_index, column=column, value=value)
                cell.border = THIN_BORDER
                cell.alignment = CELL_ALIGN
        auto_width(ws)
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        return output
