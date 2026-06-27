"""qr-system — Permission & Menu Routes"""
from flask import request, jsonify, g
from modules.app import app
from modules.middleware.audit import safe_audit_log
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.helpers import get_json_body
from modules.permission_catalog import build_permission_payload
from modules.services.audit_log_service import AuditLogService


# ============================================================
# 权限定义列表
# ============================================================
@app.route("/api/permissions", methods=["GET"])
@check_auth
def list_permissions():
    return jsonify(build_permission_payload())


# ============================================================
# 菜单权限 CRUD
# ============================================================
@app.route("/api/menu-permissions", methods=["GET"])
@check_auth
@check_permission("settings:manage")
def list_menu_permissions():
    return jsonify({"items": AuditLogService.list_menu_permissions()})


@app.route("/api/menu-permissions", methods=["POST"])
@check_auth
@check_permission("settings:manage")
def create_menu_permission():
    data = get_json_body()
    try:
        AuditLogService.create_menu_permission(data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    safe_audit_log("create_menu_permission", "menu", 0, data.get("page", ""))
    return jsonify({"message": "created"})


@app.route("/api/menu-permissions/<page>", methods=["PUT"])
@check_auth
@check_permission("settings:manage")
def update_menu_permission(page):
    data = get_json_body()
    try:
        AuditLogService.update_menu_permission(page, data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404 if "不存在" in str(e) else 400
    safe_audit_log("update_menu_permission", "menu", 0, f"{page} updated")
    return jsonify({"message": "updated"})


@app.route("/api/menu-permissions/<page>", methods=["DELETE"])
@check_auth
@check_permission("settings:manage")
def delete_menu_permission(page):
    try:
        AuditLogService.delete_menu_permission(page)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    safe_audit_log("delete_menu_permission", "menu", 0, page)
    return jsonify({"message": "deleted"})


@app.route("/api/menu-permissions/batch", methods=["PUT"])
@check_auth
@check_permission("settings:manage")
def batch_update_menu_permissions():
    data = get_json_body()
    items = data.get("items", [])
    if not isinstance(items, list):
        return jsonify({"error": "items must be array"}), 400
    try:
        AuditLogService.batch_update_menu_permissions(items)
    except Exception:
        return jsonify({"error": "保存失败，请重试"}), 400
    safe_audit_log("batch_update_menu_permissions", "menu", 0, f"{len(items)} items")
    return jsonify({"message": f"已保存 {len(items)} 条菜单配置"})
