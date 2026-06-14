"""qr-system — OrderAttachmentsService"""
import os
from modules.services import BaseService


class OrderAttachmentsService:
    @staticmethod
    def list_attachments(order_id):
        db = BaseService.db()
        rows = db.execute(
            "SELECT * FROM order_attachments WHERE order_id = ? ORDER BY id DESC",
            (order_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def upload_attachment(order_id, file_name, file_type, file_size, uploaded_by, upload_dir):
        db = BaseService.db()
        with BaseService.transaction() as txn:
            cur = txn.execute(
                "INSERT INTO order_attachments (order_id, file_name, file_type, file_size, uploaded_by) "
                "VALUES (?,?,?,?,?)",
                (order_id, file_name, file_type, file_size, uploaded_by)
            )
            aid = cur.lastrowid
            fpath = os.path.join(upload_dir, f"{aid}_{file_name}")
    @staticmethod
    def get_attachment_meta(attachment_id):
        db = BaseService.db()
        return db.execute("SELECT order_id FROM order_attachments WHERE id = ?", (attachment_id,)).fetchone()

            txn.execute("UPDATE order_attachments SET file_path = ? WHERE id = ?", (fpath, aid))
        return aid, fpath

    @staticmethod
    def delete_attachment(attachment_id):
        db = BaseService.db()
        row = db.execute(
            "SELECT order_id, file_name, file_path FROM order_attachments WHERE id = ?",
            (attachment_id,)
        ).fetchone()
        if not row:
            raise ValueError("附件不存在")
        with BaseService.transaction() as txn:
            txn.execute("DELETE FROM order_attachments WHERE id = ?", (attachment_id,))
        return row
