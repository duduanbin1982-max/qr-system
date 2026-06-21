"""qr-system - OrderNotesRepository"""
from modules.services import BaseService


class OrderNotesRepository:

    @staticmethod
    def find_order(oid, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT id, order_no, remark FROM orders WHERE id = ? AND deleted_at IS NULL",
            (oid,)
        ).fetchone()

    @staticmethod
    def count_history(oid, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) FROM order_remark_history WHERE order_id = ?", (oid,)
        ).fetchone()[0]

    @staticmethod
    def list_history(oid, limit, offset, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT id, old_remark, new_remark, user_id, user_name, created_at "
            "FROM order_remark_history WHERE order_id = ? "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            (oid, limit, offset)
        ).fetchall()
