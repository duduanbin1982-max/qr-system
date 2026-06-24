"""Product BOM Repository"""
from modules.db_unit_of_work import BaseService

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
        own_db = db is None
        db = db or BaseService.db()
        cur = db.execute(
            "INSERT INTO product_bom (product_id, material_id, quantity_per_unit, process_id) VALUES (?,?,?,?)",
            (product_id, material_id, quantity_per_unit, process_id)
        )
        if own_db:
            db.commit()
        return cur.lastrowid

    @staticmethod
    def delete(bom_id, db=None):
        own_db = db is None
        db = db or BaseService.db()
        db.execute("DELETE FROM product_bom WHERE id = ?", (bom_id,))
        if own_db:
            db.commit()

    @staticmethod
    def delete_by_product(product_id, db=None):
        db = db or BaseService.db()
        db.execute("DELETE FROM product_bom WHERE product_id = ?", (product_id,))

    @staticmethod
    def product_exists(product_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT id FROM products WHERE id = ? AND deleted_at IS NULL",
            (product_id,)
        ).fetchone() is not None

    @staticmethod
    def find_by_id(bom_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT pb.*, m.name as material_name, m.spec as material_spec, m.material_type, "
            "p.name as process_name FROM product_bom pb "
            "LEFT JOIN materials m ON pb.material_id = m.id "
            "LEFT JOIN processes p ON pb.process_id = p.id "
            "WHERE pb.id = ?",
            (bom_id,)
        ).fetchone()

    @staticmethod
    def find_by_id_and_product(bom_id, product_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT id FROM product_bom WHERE id = ? AND product_id = ?",
            (bom_id, product_id)
        ).fetchone()
