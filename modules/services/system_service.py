"""qr-system — SystemService (DB maintenance)"""
from modules.services import BaseService


class SystemService:
    @staticmethod
    def check_orphans():
        """Check for orphaned records across all related tables."""
        db = BaseService.db()
        checks = [
            ("order_processes -> orders", "SELECT COUNT(*) FROM order_processes op LEFT JOIN orders o ON op.order_id = o.id WHERE o.id IS NULL"),
            ("work_records -> orders", "SELECT COUNT(*) FROM work_records wr LEFT JOIN orders o ON wr.order_id = o.id WHERE o.id IS NULL"),
            ("work_records -> users", "SELECT COUNT(*) FROM work_records wr LEFT JOIN users u ON wr.user_id = u.id WHERE u.id IS NULL"),
            ("user_roles -> users", "SELECT COUNT(*) FROM user_roles ur LEFT JOIN users u ON ur.user_id = u.id WHERE u.id IS NULL"),
            ("order_attachments -> orders", "SELECT COUNT(*) FROM order_attachments oa LEFT JOIN orders o ON oa.order_id = o.id WHERE o.id IS NULL"),
            ("inventory -> products", "SELECT COUNT(*) FROM inventory i LEFT JOIN products p ON i.product_model = p.model WHERE p.id IS NULL AND i.product_model != ''"),
        ]
        results = []
        all_clean = True
        for label, sql in checks:
            try:
                cnt = db.execute(sql).fetchone()[0]
                ok = cnt == 0
                results.append({"check": label, "pass": ok, "orphans": cnt})
                if not ok: all_clean = False
            except Exception as e:
                results.append({"check": label, "pass": False, "detail": str(e)})
                all_clean = False
        return {"all_clean": all_clean, "checks": results}


    @staticmethod
    def ping():
        """数据库连通性检查"""
        db = BaseService.db()
        db.execute("SELECT 1")
        return True

    @staticmethod
    def get_db_stats():
        db = BaseService.db()
        tables = []
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall():
            cnt = db.execute(f'SELECT COUNT(*) FROM "{row["name"]}"').fetchone()[0]
            tables.append({"name": row["name"], "count": cnt})
        return tables

    @staticmethod
    def vacuum():
        db = BaseService.db()
        db.execute("VACUUM")

    @staticmethod
    def check_integrity():
        db = BaseService.db()
        ok = db.execute("PRAGMA integrity_check").fetchone()
        return list(ok) if ok else ["unknown"]
