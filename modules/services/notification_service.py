"""
qr-system — NotificationService
"""
from modules.services import BaseService


class NotificationService:

    @staticmethod
    def list_unread(user_id, limit=50):
        db = BaseService.db()
        rows = db.execute(
            "SELECT * FROM notifications WHERE user_id = ? AND is_read = 0 "
            "ORDER BY created_at DESC LIMIT ?", (user_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def mark_read(nid, user_id):
        db = BaseService.db()
        db.execute(
            "UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?", (nid, user_id)
        )
        db.commit()

    @staticmethod
    def mark_all_read(user_id):
        db = BaseService.db()
        db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (user_id,))
        db.commit()

    @staticmethod
    def unread_count(user_id):
        db = BaseService.db()
        return db.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0", (user_id,)
        ).fetchone()[0]

