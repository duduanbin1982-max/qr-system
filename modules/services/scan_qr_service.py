"""qr-system — ScanQRService"""
from modules.services import BaseService


class ScanQRService:
    @staticmethod
    def find_order_by_no(order_no):
        db = BaseService.db()
        return db.execute(
            "SELECT * FROM orders WHERE order_no = ? AND deleted_at IS NULL", (order_no,)
        ).fetchone()

    @staticmethod
    def find_order_by_id(order_id):
        db = BaseService.db()
        return db.execute(
            "SELECT * FROM orders WHERE id = ? AND deleted_at IS NULL", (order_id,)
        ).fetchone()

    @staticmethod
    def find_order_for_qr(order_id):
        db = BaseService.db()
        return db.execute(
            "SELECT order_no, product_name, product_code, quantity FROM orders WHERE id = ? AND deleted_at IS NULL",
            (order_id,)
        ).fetchone()

    @staticmethod
    def find_items_by_order(order_id):
        db = BaseService.db()
        return db.execute(
            "SELECT * FROM product_items WHERE order_id = ? ORDER BY position_no", (order_id,)
        ).fetchall()

    @staticmethod
    def generate_serial_numbers(order_id, order_no, quantity):
        import json
        db = BaseService.db()
        with BaseService.transaction() as txn:
            for i in range(1, quantity + 1):
                serial_no = f"{order_no}-{i:03d}"
                qr_content = json.dumps({
                    "t": "pi", "sn": serial_no, "oid": order_id, "on": order_no
                }, ensure_ascii=False)
                txn.execute(
                    "INSERT INTO product_items (serial_no, order_id, position_no, qr_content, status, created_at) "
                    "VALUES (?, ?, ?, ?, 'pending', datetime('now', 'localtime'))",
                    (serial_no, order_id, i, qr_content)
                )
        return ScanQRService.find_items_by_order(order_id)

    @staticmethod
    def find_product_code(product_name):
        db = BaseService.db()
        row = db.execute(
            "SELECT product_code FROM products WHERE product_name = ? LIMIT 1", (product_name,)
        ).fetchone()
        return row["product_code"] if row else ""
