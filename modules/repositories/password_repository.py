"""qr-system - PasswordRepository"""
from modules.db_unit_of_work import BaseService


class PasswordRepository:

    @staticmethod
    def find_active_user(user_id, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT id, username, status FROM users WHERE id = ?", (user_id,)
        ).fetchone()

    @staticmethod
    def reset_password_txn(user_id, hashed, db):
        db.execute(
            "UPDATE users SET password = ?, password_version = 2, "
            "must_change_password = 1, locked_until = NULL, "
            "failed_login_count = 0 WHERE id = ?",
            (hashed, user_id)
        )
