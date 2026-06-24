"""qr-system - SystemRepository"""
from modules.db_unit_of_work import BaseService


class SystemRepository:

    @staticmethod
    def get_tables(db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()

    @staticmethod
    def count_table(name, db=None):
        db = db or BaseService.db()
        return db.execute('SELECT COUNT(*) FROM "' + name + '"').fetchone()[0]

    @staticmethod
    def vacuum(db=None):
        db = db or BaseService.db()
        db.execute("VACUUM")

    @staticmethod
    def check_integrity(db=None):
        db = db or BaseService.db()
        return db.execute("PRAGMA integrity_check").fetchone()
