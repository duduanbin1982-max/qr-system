"""qr-system - OrderAttachmentsService"""
import os
from modules.services import BaseService
from modules.repositories.order_attachments_repository import OrderAttachmentsRepository


class OrderAttachmentsService:
    @staticmethod
    def list_attachments(order_id):
        rows = OrderAttachmentsRepository.list_by_order(order_id)
        return [dict(r) for r in rows]

    @staticmethod
    def upload_attachment(order_id, file_name, file_type, file_size, uploaded_by, upload_dir):
        with BaseService.transaction() as txn:
            aid = OrderAttachmentsRepository.insert_txn(
                order_id, file_name, file_type, file_size, uploaded_by, db=txn
            )
            fpath = os.path.join(upload_dir, str(aid) + "_" + file_name)
            OrderAttachmentsRepository.update_file_path_txn(aid, fpath, db=txn)
        return aid, fpath

    @staticmethod
    def get_attachment_meta(attachment_id):
        return OrderAttachmentsRepository.find_by_id(attachment_id)

    @staticmethod
    def get_attachment_file(attachment_id):
        row = OrderAttachmentsRepository.find_with_meta(attachment_id)
        if not row:
            raise ValueError("Attachment not found")
        return row

    @staticmethod
    def delete_attachment(attachment_id):
        row = OrderAttachmentsRepository.find_with_meta(attachment_id)
        if not row:
            raise ValueError("Attachment not found")
        with BaseService.transaction() as txn:
            OrderAttachmentsRepository.delete_txn(attachment_id, db=txn)
        return row
