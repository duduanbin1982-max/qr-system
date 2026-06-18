"""qr-system -- DashboardService"""
from datetime import datetime
from modules.services import BaseService


class DashboardService:
    # ============================================================
    # Dashboard aggregation
    # ============================================================

    @staticmethod
    def _get_dashboard_stats(db, today):
        """Collect 7 order/output KPIs in 2 queries."""
        orders_row = db.execute("""
            SELECT
                COUNT(*) as total_orders,
                SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status='producing' THEN 1 ELSE 0 END) as producing,
                SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed
            FROM orders WHERE deleted_at IS NULL
        """).fetchone()
        wr_row = db.execute("""
            SELECT
                COALESCE(SUM(CASE WHEN DATE(created_at)=? THEN quantity ELSE 0 END),0) as today_output,
                COALESCE(SUM(CASE WHEN type='scrap' AND DATE(created_at)=? THEN quantity ELSE 0 END),0) as today_scrap,
                COALESCE(SUM(CASE WHEN type='rework' AND DATE(created_at)=? THEN quantity ELSE 0 END),0) as today_rework
            FROM work_records WHERE DATE(created_at)=?
        """, (today, today, today, today)).fetchone()
        result = {
            "total_orders": orders_row["total_orders"],
            "today_output": wr_row["today_output"] or 0,
            "pending": orders_row["pending"],
            "today_scrap": wr_row["today_scrap"] or 0,
            "producing": orders_row["producing"],
            "completed": orders_row["completed"],
            "today_rework": wr_row["today_rework"] or 0,
        }
        # Low stock inventory items
        low_rows = db.execute(
            "SELECT product_model, product_name, quantity, safe_stock FROM inventory WHERE safe_stock > 0 AND quantity <= safe_stock LIMIT 10"
        ).fetchall()
        result["low_stock"] = [dict(r) for r in low_rows]

        result["pending_approvals"] = db.execute(
            "SELECT COUNT(*) FROM approval_records WHERE status='pending'"
        ).fetchone()[0]
        return result

    @staticmethod
    def _get_dashboard_security(db, today):
        """Collect login security stats."""
        return {
            "locked_users": db.execute("SELECT COUNT(*) FROM users WHERE locked_until IS NOT NULL AND locked_until > datetime('now','localtime')").fetchone()[0],
            "today_failed_logins": db.execute("SELECT COUNT(*) FROM login_logs WHERE DATE(created_at)=? AND success=0", (today,)).fetchone()[0],
            "today_success_logins": db.execute("SELECT COUNT(*) FROM login_logs WHERE DATE(created_at)=? AND success=1", (today,)).fetchone()[0],
            "suspicious_ips": db.execute("SELECT COUNT(DISTINCT ip_address) FROM login_logs WHERE DATE(created_at)=? AND ip_address NOT IN (SELECT DISTINCT ip_address FROM login_logs WHERE DATE(created_at)<?)", (today, today)).fetchone()[0],
        }

    @staticmethod
    def _get_dashboard_recent(db):
        """Recent 10 work records with order/process/worker names."""
        rows = db.execute(
            "SELECT wr.*, COALESCE(o.order_no,'-') as order_no, p.name as process_name, u.name as worker_name "
            "FROM work_records wr "
            "LEFT JOIN orders o ON wr.order_id = o.id AND o.deleted_at IS NULL "
            "LEFT JOIN processes p ON wr.process_id = p.id "
            "LEFT JOIN users u ON wr.user_id = u.id "
            "ORDER BY wr.created_at DESC LIMIT 10"
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _get_dashboard_warnings(db, today):
        """Delivery warnings: overdue + approaching orders."""
        from modules.db import get_setting
        try:
            warning_days = int(get_setting("delivery_warning_days", "3"))
        except (ValueError, TypeError):
            warning_days = 3

        if warning_days <= 0:
            return {"warning_days": 0, "overdue": [], "approaching": []}

        overdue = db.execute(
            "SELECT o.*, COALESCE(c.name, o.customer) as customer_name, "
            "CAST(julianday('now','localtime') - julianday(o.plan_end) AS INTEGER) as overdue_days "
            "FROM orders o LEFT JOIN customers c ON o.customer_id = c.id "
            "WHERE o.deleted_at IS NULL AND o.status NOT IN ('completed','cancelled') "
            "AND o.plan_end != '' AND o.plan_end < ? "
            "ORDER BY o.plan_end ASC LIMIT 5",
            (today,)
        ).fetchall()

        approaching = db.execute(
            "SELECT o.*, COALESCE(c.name, o.customer) as customer_name, "
            "CAST(julianday(o.plan_end) - julianday('now','localtime') AS INTEGER) as days_left "
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
    def _get_quick_actions(user=None):
        """Role-aware quick-action shortcuts for the workbench."""
        all_actions = [
            {"page": "orders",   "icon": "📋", "label": "订单管理", "desc": "管理生产订单", "roles": ["admin","manager"]},
            {"page": "scan",     "icon": "📱", "label": "扫码报工", "desc": "扫描二维码报工", "roles": ["admin","manager","worker"]},
            {"page": "products", "icon": "🏭", "label": "产品管理", "desc": "维护产品信息", "roles": ["admin","manager"]},
            {"page": "prices",   "icon": "💰", "label": "工价管理", "desc": "管理工序工价", "roles": ["admin","manager"]},
            {"page": "users",    "icon": "👥", "label": "员工管理", "desc": "管理用户权限", "roles": ["admin","manager"]},
            {"page": "stats",    "icon": "📊", "label": "统计报表", "desc": "查看生产统计", "roles": ["admin","manager","worker"]},
            {"page": "board",    "icon": "📺", "label": "数据看板", "desc": "实时生产大屏", "external": "/board.html", "roles": ["admin","manager","worker"]},
            {"page": "settings", "icon": "⚙️", "label": "系统设置", "desc": "系统配置管理", "roles": ["admin"]},
        ]
        role = (user or {}).get("role", "worker")
        return [a for a in all_actions if role in a.get("roles", [])]

    @staticmethod
    def get_dashboard(user=None):
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
            "quick_actions": DashboardService._get_quick_actions(user),
        }
