"""Read-only orchestration for product-group inventory queries."""
from modules import config
from modules.domain.errors import InventoryProductQueryDisabledError, NotFoundError
from modules.repositories.inventory_product_repository import InventoryProductRepository


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
        identity_status="", page=1, limit=50
    ):
        if not config.INVENTORY_PRODUCT_QUERY_ENABLED:
            raise InventoryProductQueryDisabledError("产品编码库存视图尚未启用")
        filters = {
            "keyword": (keyword or "").strip(),
            "low_stock": bool(low_stock),
            "location": (location or "").strip(),
            "quality_status": (quality_status or "").strip(),
            "identity_status": (identity_status or "").strip(),
        }
        size = min(max(int(limit), 1), 200)
        current_page = max(int(page), 1)
        total = InventoryProductRepository.count_groups(filters)
        rows = InventoryProductRepository.list_groups(filters, current_page, size)
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
            "items": [dict(row) for row in rows],
            "identity_exceptions": exceptions,
            "total": total,
            "page": current_page,
            "limit": size,
        }

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
