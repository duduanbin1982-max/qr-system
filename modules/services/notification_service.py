"""qr-system - NotificationService"""
from modules.services import BaseService
from modules.repositories.notification_repository import NotificationRepository


class NotificationService:

    @staticmethod
    def list_unread(user_id, limit=50):
        rows = NotificationRepository.list_unread(user_id, limit=limit)
        return [dict(r) for r in rows]

    @staticmethod
    def list_all(user_id, page=1, limit=20):
        return NotificationRepository.list_all(user_id, page=page, limit=limit)

    @staticmethod
    def mark_read(nid, user_id):
        with BaseService.transaction() as txn:
            NotificationRepository.mark_read_txn(nid, user_id, db=txn)

    @staticmethod
    def mark_all_read(user_id):
        with BaseService.transaction() as txn:
            NotificationRepository.mark_all_read_txn(user_id, db=txn)

    @staticmethod
    def unread_count(user_id):
        return NotificationRepository.unread_count(user_id)
