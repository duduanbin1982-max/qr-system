"""qr-system — User Roles & Permission Matrix Routes"""
from flask import request, jsonify, g
from modules.app import app
from modules.middleware.auth import check_auth, check_permission, audit_log
from modules.middleware.helpers import get_json_body
from modules.services.audit_log_service import AuditLogService


# ============================================================
# 用户角色
# ============================================================
@app.route("/api/users/<int:uid>/roles", methods=["GET"])
@check_auth
@check_permission("users:view")
def get_user_roles(uid):
    return jsonify({"roles": AuditLogService.get_user_roles(uid)})


@app.route("/api/users/<int:uid>/roles", methods=["PUT"])
@check_auth
@check_permission("users:edit")
def set_user_roles(uid):
    data = get_json_body()
    try:
        AuditLogService.set_user_roles(uid, data.get("role_ids", []))
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    audit_log("set_user_roles", "user", uid, f"roles={data.get('role_ids', [])}")
    return jsonify({"message": "角色分配成功"})


# ============================================================
# 权限矩阵
# ============================================================
@app.route("/api/permission-matrix", methods=["GET"])
@check_auth
@check_permission("users:view")
def get_permission_matrix():
    data = AuditLogService.get_permission_matrix()
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
@check_permission("users:edit")
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
        AuditLogService.batch_set_roles(user_ids, role_ids, act)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": "批量操作失败，请重试"}), 400
    audit_log("batch_set_roles", "users", 0, f"users={user_ids} roles={role_ids} action={act}")
    return jsonify({"message": f"已为 {len(user_ids)} 个用户{('分配' if act!='remove' else '移除')}角色"})
