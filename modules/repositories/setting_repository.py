"""qr-system - SettingRepository"""
from modules.services import BaseService


class SettingRepository:

    @staticmethod
    def get_all(db=None):
        db = db or BaseService.db()
        return db.execute("SELECT * FROM system_settings").fetchall()

    @staticmethod
    def upsert_txn(key, value, db):
        db.execute(
            "INSERT INTO system_settings (key, value, updated_at) "
            "VALUES (?,?,datetime('now','localtime')) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value)
        )

    @staticmethod
    def delete_txn(key, db):
        db.execute("DELETE FROM system_settings WHERE key = ?", (key,))
