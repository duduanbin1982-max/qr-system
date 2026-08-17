"""qr-system — User Roles & Permission Matrix Routes"""
from flask import request, jsonify, g
from modules.route_decorators import (
    app,
    check_auth,
    check_permission,
    get_json_body,
)
from modules.services.permission_query_service import PermissionQueryService
from modules.services.user_service import UserService


# ============================================================
# 用户角色
# ============================================================
@app.route("/api/users/<int:uid>/roles", methods=["GET"])
@check_auth
@check_permission("users:view")
def get_user_roles(uid):
    return jsonify({"roles": PermissionQueryService.get_user_roles(uid)})


@app.route("/api/users/<int:uid>/roles", methods=["PUT"])
@check_auth
@check_permission("users:admin")
def set_user_roles(uid):
    data = get_json_body()
    try:
        UserService.set_user_roles(
            uid, data.get("role_ids", []), g.current_user.get("id")
        )
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    return jsonify({"message": "角色分配成功"})


# ============================================================
# 权限矩阵
# ============================================================
@app.route("/api/permission-matrix", methods=["GET"])
@check_auth
@check_permission("users:view")
def get_permission_matrix():
    data = PermissionQueryService.get_permission_matrix()
    users = data["users"]
    all_rows = data["all_rows"]
    all_roles = data["all_roles"]

    user_role_map = {}
    for row in all_rows:
        uid = row["user_id"]
        if uid not in user_role_map:
            user_role_map[uid] = []
        user_role_map[uid].append({
            "role_id": row["role_id"], "role_name": row["role_name"],
            "role_code": row["role_code"], "permissions": row["permissions"],
            "role_status": row["role_status"],
        })

    user_list = []
    for u in users:
        uid = u["id"]
        roles = user_role_map.get(uid, [])
        user_list.append({
            "id": uid, "username": u["username"],
            "name": u["name"] or u["nickname"] or u["username"],
            "role": u["role"], "status": u["status"], "roles": roles,
            "role_count": len(roles),
        })

    role_list = [{"id": r["id"], "name": r["name"], "code": r["code"],
                  "permissions": r["permissions"], "status": r["status"], "level": r["level"]}
                 for r in all_roles]

    return jsonify({"users": user_list, "roles": role_list})


# ============================================================
# 批量角色分配
# ============================================================
@app.route("/api/users/batch-roles", methods=["POST"])
@check_auth
@check_permission("users:admin")
def batch_set_roles():
    data = get_json_body()
    user_ids = data.get("user_ids", [])
    role_ids = data.get("role_ids", [])
    act = data.get("action", "set")
    if not user_ids:
        return jsonify({"error": "请选择用户"}), 400
    if not role_ids:
        return jsonify({"error": "请选择角色"}), 400
    try:
        changed = UserService.batch_set_user_roles(
            user_ids, role_ids, act, g.current_user.get("id")
        )
    except PermissionError as exc:
        return jsonify({"error": str(exc)}), 403
    return jsonify({
        "message": f"已为 {changed} 个用户{('分配' if act!='remove' else '移除')}角色",
        "updated": changed,
    })
