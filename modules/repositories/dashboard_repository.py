"""qr-system — DashboardRepository（看板数据访问层）
All raw SQL lives here. Methods accept optional db for transaction sharing.
"""
from modules.db_unit_of_work import BaseService


class DashboardRepository:
    """Dashboard database operations — queries only, no business logic."""

    @staticmethod
    def get_order_stats(db=None):
        db = db or BaseService.db()
        return db.execute("""
            SELECT
                COUNT(*) as total_orders,
                SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status='producing' THEN 1 ELSE 0 END) as producing,
                SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed
            FROM orders WHERE deleted_at IS NULL
        """).fetchone()

    @staticmethod
    def get_work_record_daily_stats(today, db=None):
        db = db or BaseService.db()
        return db.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN DATE(created_at)=? THEN quantity ELSE 0 END),0) as today_output,
                COALESCE(SUM(CASE WHEN type='scrap' AND DATE(created_at)=? THEN quantity ELSE 0 END),0) as today_scrap,
                COALESCE(SUM(CASE WHEN type='rework' AND DATE(created_at)=? THEN quantity ELSE 0 END),0) as today_rework
            FROM work_records WHERE DATE(created_at)=?
        """, (today, today, today, today)).fetchone()

    @staticmethod
    def get_low_stock_items(db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT product_model, product_name, quantity, safe_stock "
            "FROM inventory WHERE safe_stock > 0 AND quantity <= safe_stock LIMIT 10"
        ).fetchall()

    @staticmethod
    def get_pending_approvals_count(db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) FROM approval_records WHERE status='pending'"
        ).fetchone()[0]

    @staticmethod
    def get_locked_users_count(db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) FROM users WHERE locked_until IS NOT NULL "
            "AND locked_until > datetime('now','localtime')"
        ).fetchone()[0]

    @staticmethod
    def get_today_failed_logins(today, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) FROM login_logs WHERE DATE(created_at)=? AND success=0",
            (today,)
        ).fetchone()[0]

    @staticmethod
    def get_today_success_logins(today, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) FROM login_logs WHERE DATE(created_at)=? AND success=1",
            (today,)
        ).fetchone()[0]

    @staticmethod
    def get_suspicious_ips_count(today, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(DISTINCT ip_address) FROM login_logs "
            "WHERE DATE(created_at)=? AND ip_address NOT IN "
            "(SELECT DISTINCT ip_address FROM login_logs WHERE DATE(created_at)<?)",
            (today, today)
        ).fetchone()[0]

    @staticmethod
    def get_recent_work_records(limit=10, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT wr.*, COALESCE(o.order_no,'-') as order_no, "
            "p.name as process_name, u.name as worker_name "
            "FROM work_records wr "
            "LEFT JOIN orders o ON wr.order_id = o.id AND o.deleted_at IS NULL "
            "LEFT JOIN processes p ON wr.process_id = p.id "
            "LEFT JOIN users u ON wr.user_id = u.id "
            "ORDER BY wr.created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()

    @staticmethod
    def get_company_name(db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT value FROM system_settings WHERE key='company_name'"
        ).fetchone()

    @staticmethod
    def get_delivery_warning_setting(db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT value FROM system_settings WHERE key='delivery_warning_days'"
        ).fetchone()

    @staticmethod
    def get_overdue_orders(today, limit=5, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT o.*, COALESCE(c.name, o.customer) as customer_name, "
            "CAST(julianday('now','localtime') - julianday(o.plan_end) AS INTEGER) as overdue_days "
            "FROM orders o LEFT JOIN customers c ON o.customer_id = c.id "
            "WHERE o.deleted_at IS NULL AND o.status NOT IN ('completed','cancelled') "
            "AND o.plan_end != '' AND o.plan_end < ? "
            "ORDER BY o.plan_end ASC LIMIT ?",
            (today, limit)
        ).fetchall()

    @staticmethod
    def get_approaching_orders(today, warning_days, limit=5, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT o.*, COALESCE(c.name, o.customer) as customer_name, "
            "CAST(julianday(o.plan_end) - julianday('now','localtime') AS INTEGER) as days_left "
            "FROM orders o LEFT JOIN customers c ON o.customer_id = c.id "
            "WHERE o.deleted_at IS NULL AND o.status NOT IN ('completed','cancelled') "
            "AND o.plan_end != '' AND o.plan_end >= ? "
            "AND o.plan_end <= DATE('now','+' || ? || ' days') "
            "ORDER BY o.plan_end ASC LIMIT ?",
            (today, warning_days, limit)
        ).fetchall()
