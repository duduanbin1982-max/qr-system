"""qr-system - OrderAttachmentsRepository"""
from modules.repositories.context import resolve_db


class OrderAttachmentsRepository:

    @staticmethod
    def list_by_order(order_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM order_attachments WHERE order_id = ? ORDER BY id DESC",
            (order_id,)
        ).fetchall()

    @staticmethod
    def insert_txn(order_id, file_name, file_type, file_size, uploaded_by, db):
        cur = db.execute(
            "INSERT INTO order_attachments (order_id, file_name, file_type, file_size, uploaded_by) "
            "VALUES (?,?,?,?,?)",
            (order_id, file_name, file_type, file_size, uploaded_by)
        )
        return cur.lastrowid

    @staticmethod
    def update_file_path_txn(aid, fpath, db):
        db.execute("UPDATE order_attachments SET file_path = ? WHERE id = ?", (fpath, aid))

    @staticmethod
    def find_by_id(attachment_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT order_id FROM order_attachments WHERE id = ?", (attachment_id,)
        ).fetchone()

    @staticmethod
    def find_with_meta(attachment_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT order_id, file_name, file_type, file_path FROM order_attachments WHERE id = ?",
            (attachment_id,)
        ).fetchone()

    @staticmethod
    def delete_txn(attachment_id, db):
        db.execute("DELETE FROM order_attachments WHERE id = ?", (attachment_id,))
