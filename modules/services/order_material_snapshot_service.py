"""Order material snapshot helpers."""

from modules.repositories.order_material_repository import OrderMaterialRepository
from modules.repositories.product_bom_repository import ProductBomRepository
from modules.repositories.product_repository import ProductRepository


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
        product = ProductRepository.find_active_id_by_code(product_code, db=db)
        return product["id"] if product else None

    @staticmethod
    def copy_product_bom(order_id, product_id, db):
        if not product_id:
            return 0
        copied = 0
        for bom in ProductBomRepository.list_by_product(product_id, db=db):
            process_id = bom["process_id"] if bom["process_id"] else None
            duplicate = OrderMaterialRepository.find_duplicate(
                order_id,
                bom["material_id"],
                process_id,
                db=db,
            )
            if duplicate:
                continue
            OrderMaterialRepository.insert(
                order_id,
                bom["material_id"],
                bom["quantity_per_unit"],
                process_id,
                "auto",
                db=db,
            )
            copied += 1
        return copied
