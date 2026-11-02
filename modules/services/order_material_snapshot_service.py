"""Order material snapshot helpers."""

from modules.domain.errors import ConflictError
from modules.domain.material_recipe import MaterialRecipePolicy
from modules.repositories.order_material_repository import OrderMaterialRepository
from modules.repositories.product_bom_repository import ProductBomRepository
from modules.repositories.product_repository import ProductRepository
from modules.services.order_material_state_service import OrderMaterialStateService


class OrderMaterialSnapshotService:
    """Copies product BOM rows into an order's material snapshot."""

    @staticmethod
    def resolve_product_id(data, db):
        product_id = data.get("product_id")
        if product_id:
            return product_id
        product_code = data.get("product_code", "")
        if not product_code:
            return None
        product = ProductRepository.find_active_snapshot_by_code(product_code, db=db)
        return product["id"] if product else None

    @staticmethod
    def copy_product_bom(order_id, product_id, db):
        OrderMaterialStateService.assert_can_initialize(order_id, db)
        copied = 0
        bom_rows = (
            ProductBomRepository.list_by_product(product_id, db=db)
            if product_id else []
        )
        for bom in bom_rows:
            normalized = MaterialRecipePolicy.normalize(dict(bom))
            process_id = normalized["process_id"]
            duplicate = OrderMaterialRepository.find_duplicate(
                order_id,
                normalized["material_id"],
                process_id,
                db=db,
            )
            if duplicate:
                raise ConflictError("产品物料配方存在重复项，禁止生成不完整的订单快照")
            OrderMaterialRepository.insert(
                order_id,
                normalized["material_id"],
                normalized["quantity_per_unit"],
                process_id,
                "auto",
                db=db,
            )
            copied += 1
        OrderMaterialStateService.mark_initialized(order_id, product_id, copied, db)
        return copied
