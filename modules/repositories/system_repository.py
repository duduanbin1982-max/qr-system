"""qr-system - SystemRepository"""
from modules.repositories.context import resolve_db


class SystemRepository:

    ORPHAN_CHECKS = (
        ("order_processes -> orders", "SELECT COUNT(*) FROM order_processes op LEFT JOIN orders o ON op.order_id = o.id WHERE o.id IS NULL"),
        ("work_records -> orders", "SELECT COUNT(*) FROM work_records wr LEFT JOIN orders o ON wr.order_id = o.id WHERE o.id IS NULL"),
        ("work_records -> users", "SELECT COUNT(*) FROM work_records wr LEFT JOIN users u ON wr.user_id = u.id WHERE u.id IS NULL"),
        ("user_roles -> users", "SELECT COUNT(*) FROM user_roles ur LEFT JOIN users u ON ur.user_id = u.id WHERE u.id IS NULL"),
        ("order_attachments -> orders", "SELECT COUNT(*) FROM order_attachments oa LEFT JOIN orders o ON oa.order_id = o.id WHERE o.id IS NULL"),
        ("inventory -> products", "SELECT COUNT(*) FROM inventory i LEFT JOIN products p ON i.product_model = p.model WHERE p.id IS NULL AND i.product_model != ''"),
    )

    @staticmethod
    def orphan_counts(db=None):
        db = resolve_db(db)
        results = []
        for label, sql in SystemRepository.ORPHAN_CHECKS:
            try:
                results.append({"check": label, "orphans": db.execute(sql).fetchone()[0]})
            except Exception as exc:
                results.append({"check": label, "detail": str(exc)})
        return results

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
