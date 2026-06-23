"""qr-system - BoardRepository

All SQL for kanban board data: order counts, output, efficiency, workers.
"""
from modules.db_unit_of_work import BaseService


class BoardRepository:
    """Board data access."""

    _VALID_CATEGORIES = {"机加工", "结构件", "machining", "structure"}

    @staticmethod
    def category_filter(category):
        """Build SQL filter clause for product category. Whitelist validation."""
        if not category:
            return "", []
        category = str(category).strip()
        if category not in BoardRepository._VALID_CATEGORIES:
            return "", []
        return " AND p.category = ?", [category]

    # ============================================================
    # Order Counts
    # ============================================================
    @staticmethod
    def get_order_counts(cat_sql, cat_params, db=None):
        db = db or BaseService.db()
        base = ("FROM orders o LEFT JOIN products p ON o.product_code = p.product_code "
                "WHERE o.deleted_at IS NULL" + cat_sql)
        total = db.execute("SELECT COUNT(DISTINCT o.id) " + base, cat_params).fetchone()[0]
        producing = db.execute("SELECT COUNT(DISTINCT o.id) " + base + " AND o.status='producing'", cat_params).fetchone()[0]
        completed = db.execute("SELECT COUNT(DISTINCT o.id) " + base + " AND o.status='completed'", cat_params).fetchone()[0]
        return total, producing, completed

    # ============================================================
    # Today Output
    # ============================================================
    @staticmethod
    def get_today_output(today, cat_sql, cat_params, db=None):
        db = db or BaseService.db()
        base = ("FROM work_records wr JOIN orders o ON wr.order_id = o.id "
                "LEFT JOIN products p ON o.product_code = p.product_code "
                "WHERE date(wr.created_at) = ? AND o.deleted_at IS NULL" + cat_sql)
        output = db.execute("SELECT COALESCE(SUM(wr.quantity),0) " + base, [today] + cat_params).fetchone()[0]
        scrap = db.execute("SELECT COALESCE(SUM(wr.quantity),0) " + base + " AND wr.type='scrap'", [today] + cat_params).fetchone()[0]
        reports = db.execute("SELECT COUNT(*) " + base, [today] + cat_params).fetchone()[0]
        rework = db.execute("SELECT COALESCE(SUM(wr.quantity),0) " + base + " AND wr.type='rework'", [today] + cat_params).fetchone()[0]
        return output or 0, scrap or 0, reports or 0, rework or 0

    # ============================================================
    # Recent Work
    # ============================================================
    @staticmethod
    def get_recent_work(cat_sql, cat_params, db=None):
        db = db or BaseService.db()
        rows = db.execute(
            "SELECT wr.*, o.order_no, p.name as process_name, u.name as worker_name "
            "FROM work_records wr LEFT JOIN orders o ON wr.order_id = o.id "
            "LEFT JOIN products pr ON o.product_code = pr.product_code "
            "LEFT JOIN processes p ON wr.process_id = p.id "
            "LEFT JOIN users u ON wr.user_id = u.id "
            "WHERE o.deleted_at IS NULL" + cat_sql + " ORDER BY wr.created_at DESC LIMIT 20",
            cat_params
        ).fetchall()
        return [dict(r) for r in rows]

    # ============================================================
    # Orders In Progress
    # ============================================================
    @staticmethod
    def get_orders_in_progress(cat_sql, cat_params, db=None):
        db = db or BaseService.db()
        rows = db.execute(
            "SELECT o.*, COALESCE(c.name, o.customer) as customer_name "
            "FROM orders o LEFT JOIN customers c ON o.customer_id = c.id "
            "LEFT JOIN products p ON o.product_code = p.product_code "
            "WHERE o.deleted_at IS NULL AND o.status NOT IN ('completed','cancelled')" + cat_sql + " "
            "ORDER BY o.created_at DESC LIMIT 50",
            cat_params
        ).fetchall()
        result = []
        for o in rows:
            d = dict(o)
            qty = d["quantity"] or 1
            d["progress_percent"] = min(round((d["completed"] or 0) / qty * 100), 100)
            result.append(d)
        return result

    # ============================================================
    # Process Efficiency
    # ============================================================
    @staticmethod
    def get_process_efficiency(cat_sql, cat_params, db=None):
        db = db or BaseService.db()
        rows = db.execute(
            "SELECT o.id as order_id, o.order_no, o.product_name, o.quantity, o.completed, "
            "COUNT(op.id) as total_processes, "
            "SUM(CASE WHEN op.status='completed' THEN 1 ELSE 0 END) as done_processes "
            "FROM orders o LEFT JOIN order_processes op ON op.order_id = o.id "
            "LEFT JOIN products p ON o.product_code = p.product_code "
            "WHERE o.deleted_at IS NULL AND o.status NOT IN ('completed','cancelled')" + cat_sql + " "
            "GROUP BY o.id ORDER BY o.created_at DESC LIMIT 20",
            cat_params
        ).fetchall()
        return [dict(r) for r in rows]

    # ============================================================
    # Overdue Orders
    # ============================================================
    @staticmethod
    def get_overdue_orders(today, cat_sql, cat_params, db=None):
        db = db or BaseService.db()
        rows = db.execute(
            "SELECT o.*, COALESCE(c.name, o.customer) as customer_name, "
            "CAST(julianday('now','localtime') - julianday(o.plan_end) AS INTEGER) as overdue_days "
            "FROM orders o LEFT JOIN customers c ON o.customer_id = c.id "
            "LEFT JOIN products p ON o.product_code = p.product_code "
            "WHERE o.deleted_at IS NULL AND o.status NOT IN ('completed','cancelled') "
            "AND o.plan_end != '' AND o.plan_end < ?" + cat_sql + " ORDER BY o.plan_end ASC LIMIT 10",
            [today] + cat_params
        ).fetchall()
        return [dict(r) for r in rows]

    # ============================================================
    # Worker Stats (Today)
    # ============================================================
    @staticmethod
    def get_worker_stats_today(today, cat_sql, cat_params, db=None):
        db = db or BaseService.db()
        rows = db.execute(
            "SELECT u.name as worker_name, COUNT(wr.id) as report_count, "
            "COALESCE(SUM(wr.quantity),0) as output, "
            "COALESCE(SUM(CASE WHEN wr.type='scrap' THEN wr.quantity ELSE 0 END),0) as scrap, "
            "COALESCE(SUM(CASE WHEN wr.type='rework' THEN wr.quantity ELSE 0 END),0) as rework "
            "FROM work_records wr JOIN users u ON wr.user_id = u.id "
            "JOIN orders o ON wr.order_id = o.id "
            "LEFT JOIN products p ON o.product_code = p.product_code "
            "WHERE date(wr.created_at) = ? AND o.deleted_at IS NULL" + cat_sql + " "
            "GROUP BY u.name ORDER BY output DESC LIMIT 10",
            [today] + cat_params
        ).fetchall()
        return [dict(r) for r in rows]

    # ============================================================
    # Monthly Completion
    # ============================================================
    @staticmethod
    def get_monthly_completion(cat_sql, cat_params, db=None):
        db = db or BaseService.db()
        rows = db.execute(
            "SELECT substr(o.created_at,1,7) as month, COUNT(*) as total, "
            "SUM(CASE WHEN o.status='completed' THEN 1 ELSE 0 END) as completed "
            "FROM orders o LEFT JOIN products p ON o.product_code = p.product_code "
            "WHERE o.deleted_at IS NULL AND o.created_at >= date('now','-6 months')" + cat_sql + " "
            "GROUP BY month ORDER BY month ASC",
            cat_params
        ).fetchall()
        return [dict(r) for r in rows]

    # ============================================================
    # Board Auth Sessions
    # ============================================================
    @staticmethod
    def insert_session_txn(token, expires_at, db):
        db.execute("INSERT INTO board_sessions (token, expires_at) VALUES (?, ?)", (token, expires_at))

    @staticmethod
    def upsert_setting_txn(key, value, db):
        db.execute(
            "INSERT INTO system_settings (key, value, updated_at) "
            "VALUES (?, ?, datetime('now','localtime')) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value)
        )

    @staticmethod
    def delete_sessions_txn(db):
        db.execute("DELETE FROM board_sessions")

    @staticmethod
    def count_active_sessions(db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT COUNT(*) FROM board_sessions WHERE expires_at > datetime('now','localtime')"
        ).fetchone()[0]

    @staticmethod
    def find_active_session(token, db=None):
        db = db or BaseService.db()
        return db.execute(
            "SELECT id FROM board_sessions WHERE token = ? AND expires_at > datetime('now','localtime')",
            (token,)
        ).fetchone()

    @staticmethod
    def cleanup_expired_sessions_txn(db):
        db.execute("DELETE FROM board_sessions WHERE expires_at <= datetime('now','localtime')")

