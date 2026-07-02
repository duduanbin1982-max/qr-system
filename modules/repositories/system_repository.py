"""qr-system - SystemRepository"""
from modules.repositories.context import resolve_db


class SystemRepository:

    @staticmethod
    def count_orphans(sql, db=None):
        db = resolve_db(db)
        return db.execute(sql).fetchone()[0]

    @staticmethod
    def ping(db=None):
        db = resolve_db(db)
        db.execute("SELECT 1")
        return True

    @staticmethod
    def get_tables(db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()

    @staticmethod
    def count_table(name, db=None):
        db = resolve_db(db)
        return db.execute('SELECT COUNT(*) FROM "' + name + '"').fetchone()[0]

    @staticmethod
    def vacuum(db=None):
        db = resolve_db(db)
        db.execute("VACUUM")

    @staticmethod
    def check_integrity(db=None):
        db = resolve_db(db)
        return db.execute("PRAGMA integrity_check").fetchone()
