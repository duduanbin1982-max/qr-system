"""Route module registry.

Importing route modules registers their @app.route decorators on the shared Flask app.
Keeping the list here prevents server.py from becoming the system-wide change hotspot.
"""

ROUTE_MODULES = (
    "modules.routes.auth",  # login/logout/info
    "modules.routes.dashboard",
    "modules.routes.board",  # dashboard/board
    "modules.routes.orders",  # orders CRUD + batch + work-records
    "modules.routes.customers",  # customers CRUD + order history
    "modules.routes.prices",  # process-prices + route-prices + wages
    "modules.routes.products",  # products CRUD + import + attachments
    "modules.routes.scan_work",
    "modules.routes.scan_qr",
    "modules.routes.reports",  # stats + production trends + efficiency
    "modules.routes.processes",  # 工序管理
    "modules.routes.users",  # 用户管理
    "modules.routes.order_attachments",  # 订单附件
    "modules.routes.settings",  # 系统设置
    "modules.routes.roles",  # 角色组+角色管理
    "modules.routes.audit_logs",  # 操作日志
    "modules.routes.permissions",  # 权限+菜单权限
    "modules.routes.user_roles",  # 用户角色+权限矩阵+批量角色
    "modules.routes.inventory",  # 库存管理
    "modules.routes.shipments",  # 出库管理
    "modules.routes.process_routes",  # 工序路线管理
    "modules.routes.trace",  # 产品追溯
    "modules.routes.approvals",  # 审批管理
    "modules.routes.positions",  # 岗位管理
    "modules.routes.materials",  # 物料管理
    "modules.routes.departments",  # 部门班组管理
    "modules.routes.schedule",  # 生产排程
    "modules.routes.rework",  # 返工管理
    "modules.routes.quality",  # 质量检验
    "modules.routes.stats",  # 统计报表
    "modules.routes.exports",  # Excel export
    "modules.routes.notifications",  # 通百中心
    "modules.routes.password_security",  # 密码安全Bpassword policy
    "modules.routes.imports",  # CSV/Excel bulk import
    "modules.routes.order_notes",  # order remark history
    "modules.routes.personal_stats",  # personal mobile stats
    "modules.routes.email_reports",  # email reports
    "modules.routes.progress",  # process progress + delivery alerts
    "modules.routes.system",  # health, backup, integrity checks
)


def register_routes():
    """Import all route modules for decorator-based registration."""
    for module_name in ROUTE_MODULES:
        __import__(module_name)
