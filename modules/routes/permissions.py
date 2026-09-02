"""qr-system — Permission & Menu Routes"""
from flask import request, jsonify, g
from modules.route_decorators import (
    app,
    check_auth,
    check_permission,
    get_json_body,
    safe_audit_log,
)
from modules.permission_catalog import build_permission_payload
from modules.services.menu_permission_service import MenuPermissionService


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
    return jsonify({"items": MenuPermissionService.list_items()})


@app.route("/api/menu-permissions", methods=["POST"])
@check_auth
@check_permission("settings:manage")
def create_menu_permission():
    data = get_json_body()
    try:
        MenuPermissionService.create(data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    safe_audit_log("create_menu_permission", "menu", 0, data.get("page", ""))
    return jsonify({"message": "created"})


@app.route("/api/menu-permissions/<page>", methods=["PUT"])
@check_auth
@check_permission("settings:manage")
def update_menu_permission(page):
    data = get_json_body()
    MenuPermissionService.update(page, data)
    safe_audit_log("update_menu_permission", "menu", 0, f"{page} updated")
    return jsonify({"message": "updated"})


@app.route("/api/menu-permissions/<page>", methods=["DELETE"])
@check_auth
@check_permission("settings:manage")
def delete_menu_permission(page):
    try:
        MenuPermissionService.delete(page)
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
    MenuPermissionService.batch_update(items)
    safe_audit_log("batch_update_menu_permissions", "menu", 0, f"{len(items)} items")
    return jsonify({"message": f"已保存 {len(items)} 条菜单配置"})
