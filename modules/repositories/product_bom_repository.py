"""Product BOM Repository"""
from modules.services import BaseService

class ProductBomRepository:
    @staticmethod
    def list_by_product(product_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT pb.*, m.name as material_name, m.spec as material_spec, m.material_type, m.unit, "
            "p.name as process_name FROM product_bom pb "
            "LEFT JOIN materials m ON pb.material_id = m.id "
            "LEFT JOIN processes p ON pb.process_id = p.id "
            "WHERE pb.product_id = ? ORDER BY pb.id", (product_id,)
        ).fetchall()

    @staticmethod
    def insert(product_id, material_id, quantity_per_unit, process_id, db=None):
        db = db or BaseService.db()
        db.execute(
            "INSERT OR REPLACE INTO product_bom (product_id, material_id, quantity_per_unit, process_id) VALUES (?,?,?,?)",
            (product_id, material_id, quantity_per_unit, process_id)
        )
        db.commit()

    @staticmethod
    def delete(bom_id, db=None):
        db = db or BaseService.db()
        db.execute("DELETE FROM product_bom WHERE id = ?", (bom_id,))
        db.commit()

    @staticmethod
    def delete_by_product(product_id, db=None):
        db = db or BaseService.db()
        db.execute("DELETE FROM product_bom WHERE product_id = ?", (product_id,))
