"""qr-system -- DashboardService"""
from datetime import datetime
from modules.services import BaseService


class DashboardService:
    @staticmethod
    def get_stats():
        db = BaseService.db()
        today = db.execute("SELECT COALESCE(SUM(quantity),0) FROM work_records WHERE DATE(created_at)=DATE('now','localtime')").fetchone()[0]
        month = db.execute("SELECT COALESCE(SUM(quantity),0) FROM work_records WHERE strftime('%Y-%m',created_at)=strftime('%Y-%m','now')").fetchone()[0]
        orders = db.execute("SELECT COUNT(*) FROM orders WHERE deleted_at IS NULL AND status NOT IN ('completed','cancelled')").fetchone()[0]
        return {"today_quantity": today or 0, "month_quantity": month or 0, "active_orders": orders}

    @staticmethod
    def get_trend(days=30):
        db = BaseService.db()
        rows = db.execute(
            "SELECT DATE(created_at) as dt, SUM(quantity) as qty FROM work_records "
            "WHERE created_at >= DATE('now',? || ' days') GROUP BY dt ORDER BY dt", (f'-{days}',)
        ).fetchall()
        return [{"date": r["dt"], "quantity": r["qty"]} for r in rows]

    # ============================================================
    # Dashboard aggregation (decomposed from get_dashboard)
    # ============================================================

    @staticmethod
    def _get_dashboard_stats(db, today):
        """Collect 7 order/output KPIs in one batch."""
        return {
            "total_orders": db.execute("SELECT COUNT(*) FROM orders WHERE deleted_at IS NULL").fetchone()[0],
            "today_output": db.execute("SELECT COALESCE(SUM(quantity),0) FROM work_records WHERE DATE(created_at)=?", (today,)).fetchone()[0] or 0,
            "pending": db.execute("SELECT COUNT(*) FROM orders WHERE deleted_at IS NULL AND status='pending'").fetchone()[0],
            "today_scrap": db.execute("SELECT COALESCE(SUM(quantity),0) FROM work_records WHERE type='scrap' AND DATE(created_at)=?", (today,)).fetchone()[0] or 0,
            "producing": db.execute("SELECT COUNT(*) FROM orders WHERE deleted_at IS NULL AND status='producing'").fetchone()[0],
            "completed": db.execute("SELECT COUNT(*) FROM orders WHERE deleted_at IS NULL AND status='completed'").fetchone()[0],
            "today_rework": db.execute("SELECT COALESCE(SUM(quantity),0) FROM work_records WHERE type='rework' AND DATE(created_at)=?", (today,)).fetchone()[0] or 0,
        }

    @staticmethod
    def _get_dashboard_security(db, today):
        """Collect login security stats."""
        return {
            "locked_users": db.execute("SELECT COUNT(*) FROM users WHERE locked_until IS NOT NULL AND locked_until > datetime('now','localtime')").fetchone()[0],
            "today_failed_logins": db.execute("SELECT COUNT(*) FROM login_logs WHERE DATE(created_at)=? AND success=0", (today,)).fetchone()[0],
            "today_success_logins": db.execute("SELECT COUNT(*) FROM login_logs WHERE DATE(created_at)=? AND success=1", (today,)).fetchone()[0],
            "suspicious_ips": db.execute("SELECT COUNT(DISTINCT ip_address) FROM login_attempts WHERE DATE(created_at)=? AND ip_address NOT IN (SELECT DISTINCT ip_address FROM login_attempts WHERE DATE(created_at)<?)", (today, today)).fetchone()[0],
        }

    @staticmethod
    def _get_dashboard_recent(db):
        """Recent 10 work records with order/process/worker names."""
        rows = db.execute(
            "SELECT wr.*, o.order_no, p.name as process_name, u.name as worker_name "
            "FROM work_records wr "
            "LEFT JOIN orders o ON wr.order_id = o.id "
            "LEFT JOIN processes p ON wr.process_id = p.id "
            "LEFT JOIN users u ON wr.user_id = u.id "
            "WHERE o.deleted_at IS NULL "
            "ORDER BY wr.created_at DESC LIMIT 10"
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _get_dashboard_warnings(db, today):
        """Delivery warnings: overdue + approaching orders."""
        row = db.execute("SELECT value FROM system_settings WHERE key='delivery_warning_days'").fetchone()
        warning_days = int(row["value"]) if row and row["value"] else 3

        if warning_days <= 0:
            return {"warning_days": 0, "overdue": [], "approaching": []}

        overdue = db.execute(
            "SELECT o.*, COALESCE(c.name, o.customer) as customer_name, "
            "CAST(julianday('now') - julianday(o.plan_end) AS INTEGER) as overdue_days "
            "FROM orders o LEFT JOIN customers c ON o.customer_id = c.id "
            "WHERE o.deleted_at IS NULL AND o.status NOT IN ('completed','cancelled') "
            "AND o.plan_end != '' AND o.plan_end < ? ORDER BY o.plan_end ASC LIMIT 5",
            (today,)
        ).fetchall()

        approaching = db.execute(
            "SELECT o.*, COALESCE(c.name, o.customer) as customer_name, "
            "CAST(julianday(o.plan_end) - julianday('now') AS INTEGER) as days_left "
            "FROM orders o LEFT JOIN customers c ON o.customer_id = c.id "
            "WHERE o.deleted_at IS NULL AND o.status NOT IN ('completed','cancelled') "
            "AND o.plan_end != '' AND o.plan_end >= ? AND o.plan_end <= DATE('now','+' || ? || ' days') "
            "ORDER BY o.plan_end ASC LIMIT 5",
            (today, warning_days)
        ).fetchall()

        return {
            "warning_days": warning_days,
            "overdue": [dict(r) for r in overdue],
            "approaching": [dict(r) for r in approaching],
        }

    @staticmethod
    def _get_quick_actions():
        """Default quick-action shortcuts for the workbench."""
        return [
            {"page": "orders",   "icon": "📋", "label": "订单管理", "desc": "管理生产订单"},
            {"page": "scan",     "icon": "📱", "label": "扫码报工", "desc": "扫描二维码报工"},
            {"page": "products", "icon": "🏭", "label": "产品管理", "desc": "维护产品信息"},
            {"page": "prices",   "icon": "💰", "label": "工价管理", "desc": "管理工序工价"},
            {"page": "users",    "icon": "👥", "label": "员工管理", "desc": "管理用户权限"},
            {"page": "stats",    "icon": "📊", "label": "统计报表", "desc": "查看生产统计"},
            {"page": "board",    "icon": "📺", "label": "数据看板", "desc": "实时生产大屏", "external": "/board.html"},
            {"page": "settings", "icon": "⚙️", "label": "系统设置", "desc": "系统配置管理"},
        ]

    @staticmethod
    def get_dashboard():
        """Aggregated dashboard: stats + security + records + warnings + actions."""
        db = BaseService.db()
        today = datetime.now().strftime("%Y-%m-%d")

        company = db.execute("SELECT value FROM system_settings WHERE key='company_name'").fetchone()

        return {
            "stats": DashboardService._get_dashboard_stats(db, today),
            "security": DashboardService._get_dashboard_security(db, today),
            "recent_records": DashboardService._get_dashboard_recent(db),
            "company_name": company["value"] if company else "",
            "delivery_warnings": DashboardService._get_dashboard_warnings(db, today),
            "quick_actions": DashboardService._get_quick_actions(),
        }
