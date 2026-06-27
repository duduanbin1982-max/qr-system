"""Order material snapshot helpers."""

import sqlite3

from modules.repositories.order_material_repository import OrderMaterialRepository
from modules.repositories.product_bom_repository import ProductBomRepository


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
        product = db.execute(
            "SELECT id FROM products WHERE product_code = ? AND deleted_at IS NULL",
            (product_code,),
        ).fetchone()
        return product["id"] if product else None

    @staticmethod
    def copy_product_bom(order_id, product_id, db):
        if not product_id:
            return 0
        copied = 0
        for bom in ProductBomRepository.list_by_product(product_id, db=db):
            process_id = bom["process_id"] if bom["process_id"] else None
            try:
                OrderMaterialRepository.insert(
                    order_id,
                    bom["material_id"],
                    bom["quantity_per_unit"],
                    process_id,
                    "auto",
                    db=db,
                )
                copied += 1
            except sqlite3.IntegrityError:
                duplicate = OrderMaterialRepository.find_duplicate(
                    order_id,
                    bom["material_id"],
                    process_id,
                    db=db,
                )
                if not duplicate:
                    raise
        return copied
