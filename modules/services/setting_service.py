"""
qr-system — SettingsService
"""
from modules.services import BaseService


class SettingsService:

    @staticmethod
    def get_all():
        db = BaseService.db()
        rows = db.execute("SELECT * FROM system_settings").fetchall()
        return {r["key"]: r["value"] for r in rows}

    @staticmethod
    def save(updates, deleted_keys):
        db = BaseService.db()
        with BaseService.transaction() as txn:
            for k, v in updates.items():
                txn.execute(
                    "INSERT INTO system_settings (key, value, updated_at) "
                    "VALUES (?,?,datetime('now','localtime')) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (k, v)
                )
            for k in deleted_keys:
                txn.execute("DELETE FROM system_settings WHERE key = ?", (k,))

