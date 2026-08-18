"""Canonical audit action metadata.

The catalog is intentionally small and extensible.  Unknown legacy actions
remain visible as ``legacy`` instead of silently disappearing from queries.
"""

from dataclasses import dataclass


AUDIT_CATEGORY_LABELS = {
    "security": "安全认证",
    "permission": "权限变更",
    "system": "系统配置",
    "business": "业务操作",
    "inventory": "库存物料",
    "quality": "质量管理",
    "payroll": "工资核算",
    "master_data": "主数据",
    "legacy": "历史未分类",
}


@dataclass(frozen=True)
class AuditAction:
    category: str = "legacy"
    severity: str = "info"
    mandatory: bool = False


_SECURITY_ACTIONS = {
    "login_success",
    "login_failed",
    "change_password",
    "reset_password",
    "unlock_user",
}

_PERMISSION_ACTIONS = {
    "set_user_roles",
    "batch_set_roles",
    "create_role_group",
    "update_role_group",
    "delete_role_group",
    "create_role",
    "update_role",
    "delete_role",
    "create_menu_permission",
    "update_menu_permission",
    "delete_menu_permission",
    "batch_update_menu_permissions",
    "save_permissions",
    "replace_performance_department_scopes",
    "performance_v57_account_base_role_repair",
    "role_group_permission_cutover",
}

_SYSTEM_ACTIONS = {
    "save_settings",
    "company_profile_update",
    "system_backup",
    "integrity_check",
    "clear_logs",
    "audit_cleanup_requested",
    "audit_cleanup_rejected",
    "audit_cleanup_executed",
}

_DESTRUCTIVE_ACTIONS = {
    "delete_customer",
    "delete_product",
    "purge_product",
    "delete_order",
    "purge_order",
    "delete_role",
    "delete_role_group",
    "delete_menu_permission",
    "clear_logs",
}


def describe_action(action: str) -> AuditAction:
    """Return stable metadata for an action without requiring callers to know it."""

    name = str(action or "").strip()
    if name in _SECURITY_ACTIONS:
        return AuditAction("security", "warning", True)
    if name in _PERMISSION_ACTIONS:
        return AuditAction("permission", "warning", True)
    if name in _SYSTEM_ACTIONS:
        return AuditAction("system", "warning", True)
    if name in _DESTRUCTIVE_ACTIONS:
        return AuditAction("business", "warning", True)
    if name.startswith(("payroll_", "wage_")):
        return AuditAction("payroll", "info", True)
    if name.startswith(("stock_", "inventory_", "material_", "consume")):
        return AuditAction("inventory", "info", True)
    if name.startswith(("quality_", "process_quality_", "ncr_", "capa_")):
        return AuditAction("quality", "info", True)
    if name.startswith(("create_process", "update_process", "delete_process", "process_", "route_")):
        return AuditAction("master_data", "info", True)
    if name.startswith(("create_", "update_", "delete_", "restore_", "purge_", "cancel_", "complete_")):
        return AuditAction("business", "info", True)
    return AuditAction()


def category_for_action(action: str) -> str:
    return describe_action(action).category


def category_options():
    return [
        {"code": code, "label": label}
        for code, label in AUDIT_CATEGORY_LABELS.items()
    ]
