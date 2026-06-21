"""qr-system -- DashboardService (Repository pattern)"""
from datetime import datetime
from modules.services import BaseService
from modules.repositories.dashboard_repository import DashboardRepository


class DashboardService:
    # ============================================================
    # Dashboard aggregation
    # ============================================================

    @staticmethod
    def _get_dashboard_stats(db, today):
        """Collect 7 order/output KPIs from repository."""
        orders_row = DashboardRepository.get_order_stats(db=db)
        wr_row = DashboardRepository.get_work_record_daily_stats(today, db=db)
        result = {
            "total_orders": orders_row["total_orders"],
            "today_output": wr_row["today_output"] or 0,
            "pending": orders_row["pending"],
            "today_scrap": wr_row["today_scrap"] or 0,
            "producing": orders_row["producing"],
            "completed": orders_row["completed"],
            "today_rework": wr_row["today_rework"] or 0,
        }
        low_rows = DashboardRepository.get_low_stock_items(db=db)
        result["low_stock"] = [dict(r) for r in low_rows]
        result["pending_approvals"] = DashboardRepository.get_pending_approvals_count(db=db)
        return result

    @staticmethod
    def _get_dashboard_security(db, today):
        """Collect login security stats."""
        return {
            "locked_users": DashboardRepository.get_locked_users_count(db=db),
            "today_failed_logins": DashboardRepository.get_today_failed_logins(today, db=db),
            "today_success_logins": DashboardRepository.get_today_success_logins(today, db=db),
            "suspicious_ips": DashboardRepository.get_suspicious_ips_count(today, db=db),
        }

    @staticmethod
    def _get_dashboard_recent(db):
        """Recent 10 work records with order/process/worker names."""
        rows = DashboardRepository.get_recent_work_records(limit=10, db=db)
        return [dict(r) for r in rows]

    @staticmethod
    def _get_dashboard_warnings(db, today):
        """Delivery warnings: overdue + approaching orders."""
        setting_row = DashboardRepository.get_delivery_warning_setting(db=db)
        try:
            warning_days = int(setting_row['value']) if setting_row else 3
        except (ValueError, TypeError):
            warning_days = 3

        if warning_days <= 0:
            return {"warning_days": 0, "overdue": [], "approaching": []}

        overdue = DashboardRepository.get_overdue_orders(today, limit=5, db=db)
        approaching = DashboardRepository.get_approaching_orders(today, warning_days, limit=5, db=db)

        return {
            "warning_days": warning_days,
            "overdue": [dict(r) for r in overdue],
            "approaching": [dict(r) for r in approaching],
        }

    @staticmethod
    def _get_quick_actions(user=None):
        """Permission-based quick-action shortcuts for the workbench."""
        all_actions = [
            {"page": "orders",   "icon": "📋", "label": "订单管理", "desc": "管理生产订单", "perm": "orders:view"},
            {"page": "scan",     "icon": "📱", "label": "扫码报工", "desc": "扫描二维码报工", "perm": "scan:view"},
            {"page": "products", "icon": "🏭", "label": "产品管理", "desc": "维护产品信息", "perm": "products:view"},
            {"page": "prices",   "icon": "💰", "label": "工价管理", "desc": "管理工序工价", "perm": "prices:view"},
            {"page": "users",    "icon": "👥", "label": "员工管理", "desc": "管理用户权限", "perm": "users:view"},
            {"page": "stats",    "icon": "📊", "label": "统计报表", "desc": "查看生产统计", "perm": "stats:view"},
            {"page": "board",    "icon": "📺", "label": "数据看板", "desc": "实时生产大屏", "external": "/board.html", "perm": "board:view"},
            {"page": "settings", "icon": "⚙️", "label": "系统设置", "desc": "系统配置管理", "perm": "settings:manage"},
        ]
        perms = set(user.get("_permissions", []) if user else [])
        has_all = "*" in perms
        return [a for a in all_actions if has_all or a.get("perm", "") in perms]

    @staticmethod
    def get_dashboard(user=None):
        """Aggregated dashboard: stats + security + records + warnings + actions."""
        db = BaseService.db()
        today = datetime.now().strftime("%Y-%m-%d")

        company = DashboardRepository.get_company_name(db=db)

        return {
            "stats": DashboardService._get_dashboard_stats(db, today),
            "security": DashboardService._get_dashboard_security(db, today),
            "recent_records": DashboardService._get_dashboard_recent(db),
            "company_name": company["value"] if company else "",
            "delivery_warnings": DashboardService._get_dashboard_warnings(db, today),
            "quick_actions": DashboardService._get_quick_actions(user),
        }
