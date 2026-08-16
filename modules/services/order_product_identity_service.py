"""Stable product identity and immutable order snapshot handling."""

from modules.domain.errors import NotFoundError, ValidationError
from modules.repositories.product_repository import ProductRepository


class OrderProductIdentityService:
    """Resolve product selections while preserving historical order semantics."""

    SNAPSHOT_FIELDS = (
        "product_name",
        "product_code",
        "model",
        "spec",
        "style",
        "upper_opening",
        "lower_opening",
        "plate_thickness",
        "category",
        "weight",
        "price",
    )

    @staticmethod
    def _product_id(value):
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError("产品 ID 无效") from exc

    @staticmethod
    def _resolve(data, db):
        product_id = OrderProductIdentityService._product_id(data.get("product_id"))
        product_code = (data.get("product_code") or "").strip()

        if product_id is not None:
            product = ProductRepository.find_active_snapshot(product_id, db=db)
            if not product:
                raise NotFoundError("所选产品不存在或已停用")
            if product_code:
                alias = ProductRepository.find_code_alias(product_code, db=db)
                if not alias or alias["product_id"] != product_id:
                    raise ValidationError("产品 ID 与产品编码不匹配，请重新选择产品")
            return dict(product)

        if product_code:
            product = ProductRepository.find_active_snapshot_by_code(product_code, db=db)
            return dict(product) if product else None

        return None

    @staticmethod
    def _apply_current_snapshot(data, product):
        normalized = dict(data)
        normalized["product_id"] = product["id"]
        for field in OrderProductIdentityService.SNAPSHOT_FIELDS:
            normalized[field] = product.get(field)
        if "route_id" not in normalized and product.get("process_route_id") is not None:
            normalized["route_id"] = product["process_route_id"]
        return normalized

    @staticmethod
    def normalize_create(data, db):
        """Resolve a new order and freeze the selected product's current identity."""
        product = OrderProductIdentityService._resolve(data, db)
        if product:
            return OrderProductIdentityService._apply_current_snapshot(data, product)
        normalized = dict(data)
        normalized["product_id"] = None
        return normalized

    @staticmethod
    def normalize_update(current_order, data, db):
        """Only replace snapshots when the order is linked to a different product."""
        has_selection = "product_id" in data or "product_code" in data
        if not has_selection:
            normalized = dict(data)
            if current_order["product_id"] is not None:
                normalized.pop("product_name", None)
            return normalized

        product = OrderProductIdentityService._resolve(data, db)
        if not product:
            normalized = dict(data)
            normalized["product_id"] = None
            return normalized

        if current_order["product_id"] == product["id"]:
            normalized = dict(data)
            normalized["product_id"] = current_order["product_id"]
            normalized["product_code"] = current_order["product_code"] or ""
            normalized["product_name"] = current_order["product_name"] or product["product_name"]
            return normalized

        return OrderProductIdentityService._apply_current_snapshot(data, product)
