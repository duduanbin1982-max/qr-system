"""qr-system - ScanQRRepository"""
from modules.db_unit_of_work import BaseService


class ScanQRRepository:

    @staticmethod
    def find_order_by_no(order_no, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT * FROM orders WHERE order_no = ? AND deleted_at IS NULL", (order_no,)
        ).fetchone()

    @staticmethod
    def find_order_by_id(order_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT * FROM orders WHERE id = ? AND deleted_at IS NULL", (order_id,)
        ).fetchone()

    @staticmethod
    def find_order_for_qr(order_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT order_no, product_name, product_code, quantity FROM orders WHERE id = ? AND deleted_at IS NULL",
            (order_id,)
        ).fetchone()

    @staticmethod
    def find_items_by_order(order_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT * FROM product_items WHERE order_id = ? ORDER BY position_no", (order_id,)
        ).fetchall()

    @staticmethod
    def insert_product_item_txn(serial_no, order_id, position_no, qr_content, db):
        db.execute(
            "INSERT OR IGNORE INTO product_items (serial_no, order_id, position_no, qr_content, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', datetime('now', 'localtime'))",
            (serial_no, order_id, position_no, qr_content)
        )

    @staticmethod
    def find_product_code(product_name, db=None):
        db = db or BaseService.db()
        row = db.execute(
            "SELECT product_code FROM products WHERE product_name = ? LIMIT 1", (product_name,)
        ).fetchone()
        return row["product_code"] if row else ""

    @staticmethod
    def set_qr_mode_txn(order_id, mode, db):
        db.execute("UPDATE orders SET qr_mode = ? WHERE id = ?", (mode, order_id))
