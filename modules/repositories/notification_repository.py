"""qr-system - NotificationRepository"""
from modules.services import BaseService


class NotificationRepository:

    @staticmethod
    def list_unread(user_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT * FROM notifications WHERE user_id = ? AND is_read = 0 ORDER BY created_at DESC LIMIT 50",
            (user_id,)
        ).fetchall()

    @staticmethod
    def list_all(user_id, page=1, limit=20, db=None):
        db = db or BaseService.db()
        total = db.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        offset = (page - 1) * limit
        rows = db.execute(
            "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset)
        ).fetchall()
        return {"items": [dict(r) for r in rows], "total": total, "page": page, "limit": limit}

    @staticmethod
    def mark_read_txn(nid, user_id, db):
        db.execute(
            "UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?", (nid, user_id)
        )

    @staticmethod
    def mark_all_read_txn(user_id, db):
        db.execute("UPDATE notifications SET is_read = 1 WHERE user_id = ?", (user_id,))

    @staticmethod
    def unread_count(user_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0", (user_id,)
        ).fetchone()[0]
