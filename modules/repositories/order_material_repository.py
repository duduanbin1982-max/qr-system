"""Order Material Repository"""
from modules.services import BaseService

class OrderMaterialRepository:
    @staticmethod
    def list_by_order(order_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT om.*, m.name as material_name, m.spec as material_spec, m.material_type, m.unit, "
            "m.quantity as stock_qty, p.name as process_name FROM order_materials om "
            "LEFT JOIN materials m ON om.material_id = m.id "
            "LEFT JOIN processes p ON om.process_id = p.id "
            "WHERE om.order_id = ? ORDER BY om.id", (order_id,)
        ).fetchall()

    @staticmethod
    def insert(order_id, material_id, quantity_per_unit, process_id, source="auto", db=None):
        own_db = db is None
        db = db or BaseService.db()
        db.execute(
            "INSERT INTO order_materials (order_id, material_id, quantity_per_unit, process_id, source) VALUES (?,?,?,?,?)",
            (order_id, material_id, quantity_per_unit, process_id, source)
        )
        if own_db:
            db.commit()

    @staticmethod
    def delete(order_material_id, db=None):
        own_db = db is None
        db = db or BaseService.db()
        db.execute("DELETE FROM order_materials WHERE id = ?", (order_material_id,))
        if own_db:
            db.commit()

    @staticmethod
    def delete_by_order(order_id, db=None):
        db = db or BaseService.db()
        db.execute("DELETE FROM order_materials WHERE order_id = ?", (order_id,))

    @staticmethod
    def get_by_order_and_process(order_id, process_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT om.*, m.name as material_name, m.quantity as stock_qty FROM order_materials om "
            "JOIN materials m ON om.material_id = m.id "
            "WHERE om.order_id = ? AND om.process_id = ?", (order_id, process_id)
        ).fetchall()
