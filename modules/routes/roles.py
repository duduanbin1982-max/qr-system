"""
qr-system — 角色管理（路由层）

注：Swagger docstring 仅供文档参考。
"""
from flask import request, jsonify
from modules.app import app
from modules.middleware.audit import safe_audit_log
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.helpers import get_json_body
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
    try:
        gid = RoleGroupService.create_group(data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 409 if '已存在' in str(e) else 400
    safe_audit_log('create_role_group', 'role_group', gid, data.get('name', ''))
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
    try:
        RoleGroupService.update_group(gid, data)
    except ValueError as e:
        code = 404 if '不存在' in str(e) else (409 if '已存在' in str(e) else 400)
        return jsonify({'error': str(e)}), code
    safe_audit_log('update_role_group', 'role_group', gid, str(data))
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
    try:
        RoleGroupService.delete_group(gid)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    safe_audit_log('delete_role_group', 'role_group', gid)
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
    try:
        rid = RoleService.create_role(data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 409 if '已存在' in str(e) else 400
    safe_audit_log('create_role', 'role', rid, f'{data.get("name","")}/{data.get("code","")}')
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
    try:
        RoleService.update_role(rid, data)
    except ValueError as e:
        code = 404 if '不存在' in str(e) else (409 if '已存在' in str(e) else 400)
        return jsonify({'error': str(e)}), code
    safe_audit_log('update_role', 'role', rid, str(data))
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
    try:
        RoleService.delete_role(rid)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    safe_audit_log('delete_role', 'role', rid)
    return jsonify({'message': '删除成功'})
