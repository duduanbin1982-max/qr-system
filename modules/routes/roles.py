"""
qr-system — 角色管理（路由层）

注：Swagger docstring 仅供文档参考。
"""
from flask import g, jsonify
from modules.route_decorators import (
    app,
    check_auth,
    check_permission,
    get_json_body,
)
from modules.services.role_service import RoleGroupService, RoleService


# ============================================================
# 角色组
# ============================================================
@app.route('/api/role-groups', methods=['GET'])
@check_auth
@check_permission('role_groups:view')
def list_role_groups():
    """
    ---
    tags:
      - Roles
    summary: List Role Groups
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    return jsonify(RoleGroupService.list_groups())


@app.route('/api/role-groups', methods=['POST'])
@check_auth
@check_permission('role_groups:create')
def create_role_group():
    """
    ---
    tags:
      - Roles
    summary: Create Role Group
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    data = get_json_body()
    gid = RoleGroupService.create_group(data, g.current_user.get('id'))
    return jsonify({'message': '添加成功', 'id': gid})


@app.route('/api/role-groups/<int:gid>', methods=['PUT'])
@check_auth
@check_permission('role_groups:edit')
def update_role_group(gid):
    """
    ---
    tags:
      - Roles
    summary: Update Role Group
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    data = get_json_body()
    RoleGroupService.update_group(gid, data, g.current_user.get('id'))
    return jsonify({'message': '更新成功'})


@app.route('/api/role-groups/<int:gid>', methods=['DELETE'])
@check_auth
@check_permission('role_groups:delete')
def delete_role_group(gid):
    """
    ---
    tags:
      - Roles
    summary: Delete Role Group
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    RoleGroupService.delete_group(gid, g.current_user.get('id'))
    return jsonify({'message': '删除成功'})


# ============================================================
# 角色
# ============================================================
@app.route('/api/roles', methods=['GET'])
@check_auth
@check_permission('roles:view')
def list_roles():
    """
    ---
    tags:
      - Roles
    summary: List Roles
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    return jsonify(RoleService.list_roles())


@app.route('/api/roles', methods=['POST'])
@check_auth
@check_permission('roles:create')
def create_role():
    """
    ---
    tags:
      - Roles
    summary: Create Role
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    data = get_json_body()
    rid = RoleService.create_role(data, g.current_user.get('id'))
    return jsonify({'message': '添加成功', 'id': rid})


@app.route('/api/roles/<int:rid>', methods=['PUT'])
@check_auth
@check_permission('roles:edit')
def update_role(rid):
    """
    ---
    tags:
      - Roles
    summary: Update Role
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    data = get_json_body()
    RoleService.update_role(rid, data, g.current_user.get('id'))
    return jsonify({'message': '更新成功'})


@app.route('/api/roles/<int:rid>', methods=['DELETE'])
@check_auth
@check_permission('roles:delete')
def delete_role(rid):
    """
    ---
    tags:
      - Roles
    summary: Delete Role
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    RoleService.delete_role(rid, g.current_user.get('id'))
    return jsonify({'message': '删除成功'})
