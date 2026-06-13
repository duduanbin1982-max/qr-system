"""qr-system — 操作日志+权限+用户角色（Refactored: SQL → AuditLogService）"""
from flask import request, jsonify, g
from modules.app import app
from modules.db import get_db
from modules.middleware.auth import check_auth, check_permission, audit_log
from modules.middleware.helpers import get_json_body
from modules.config import PERMISSION_DEFS
from modules.services.audit_log_service import AuditLogService


# ============================================================
# 操作日志
# ============================================================
@app.route('/api/logs', methods=['GET'])
@check_auth
@check_permission('logs:view')
def list_logs():
    result = AuditLogService.list_logs(
        page=request.args.get('page', 1, type=int),
        limit=min(request.args.get('limit', 50, type=int), 200),
        action=request.args.get('action', '').strip(),
        keyword=request.args.get('keyword', '').strip(),
        user_id=request.args.get('user_id', type=int),
        category=request.args.get('category', '').strip(),
    )
    return jsonify(result)


# ============================================================
# 权限定义列表
# ============================================================
@app.route('/api/permissions', methods=['GET'])
@check_auth
def list_permissions():
    perms = [{'code': code, 'label': label, 'actions': actions}
             for code, (label, actions) in PERMISSION_DEFS.items()]
    return jsonify({'permissions': perms})


# ============================================================
# 用户角色
# ============================================================
@app.route('/api/users/<int:uid>/roles', methods=['GET'])
@check_auth
@check_permission('users:view')
def get_user_roles(uid):
    return jsonify({'roles': AuditLogService.get_user_roles(uid)})


@app.route('/api/users/<int:uid>/roles', methods=['PUT'])
@check_auth
@check_permission('users:edit')
def set_user_roles(uid):
    data = get_json_body()
    try:
        AuditLogService.set_user_roles(uid, data.get('role_ids', []))
    except Exception as e:
        return jsonify({'error': str(e)}), 400
    try:
        audit_log('set_user_roles', 'user', uid, f'roles={data.get("role_ids", [])}')
    except Exception:
        pass
    return jsonify({'message': '角色分配成功'})


# ============================================================
# 权限矩阵
# ============================================================
@app.route('/api/permission-matrix', methods=['GET'])
@check_auth
@check_permission('users:view')
def get_permission_matrix():
    data = AuditLogService.get_permission_matrix()
    users = data['users']
    all_rows = data['all_rows']
    all_roles = data['all_roles']

    user_role_map = {}
    for row in all_rows:
        uid = row['user_id']
        if uid not in user_role_map:
            user_role_map[uid] = []
        user_role_map[uid].append({
            'role_id': row['role_id'], 'role_name': row['role_name'],
            'role_code': row['role_code'], 'permissions': row['permissions'],
            'role_status': row['role_status'],
        })

    user_list = []
    for u in users:
        uid = u['id']
        roles = user_role_map.get(uid, [])
        user_list.append({
            'id': uid, 'username': u['username'], 'name': u['name'] or u['nickname'] or u['username'],
            'role': u['role'], 'status': u['status'], 'roles': roles,
            'role_count': len(roles),
        })

    role_list = [{'id': r['id'], 'name': r['name'], 'code': r['code'],
                  'permissions': r['permissions'], 'status': r['status'], 'level': r['level']}
                 for r in all_roles]

    return jsonify({'users': user_list, 'roles': role_list})


# ============================================================
# 菜单权限 CRUD
# ============================================================
@app.route('/api/menu-permissions', methods=['GET'])
@check_auth
@check_permission('settings:manage')
def list_menu_permissions():
    return jsonify({'items': AuditLogService.list_menu_permissions()})


@app.route('/api/menu-permissions', methods=['POST'])
@check_auth
@check_permission('settings:manage')
def create_menu_permission():
    data = get_json_body()
    try:
        AuditLogService.create_menu_permission(data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    try:
        audit_log('create_menu_permission', 'menu', 0, data.get('page', ''))
    except Exception:
        pass
    return jsonify({'message': 'created'})


@app.route('/api/menu-permissions/<page>', methods=['PUT'])
@check_auth
@check_permission('settings:manage')
def update_menu_permission(page):
    data = get_json_body()
    try:
        AuditLogService.update_menu_permission(page, data)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404 if '不存在' in str(e) else 400
    try:
        audit_log('update_menu_permission', 'menu', 0, f'{page} updated')
    except Exception:
        pass
    return jsonify({'message': 'updated'})


@app.route('/api/menu-permissions/<page>', methods=['DELETE'])
@check_auth
@check_permission('settings:manage')
def delete_menu_permission(page):
    try:
        AuditLogService.delete_menu_permission(page)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    try:
        audit_log('delete_menu_permission', 'menu', 0, page)
    except Exception:
        pass
    return jsonify({'message': 'deleted'})


@app.route('/api/menu-permissions/batch', methods=['PUT'])
@check_auth
@check_permission('settings:manage')
def batch_update_menu_permissions():
    data = get_json_body()
    items = data.get('items', [])
    if not isinstance(items, list):
        return jsonify({'error': 'items must be array'}), 400
    try:
        AuditLogService.batch_update_menu_permissions(items)
    except Exception:
        return jsonify({'error': '保存失败，请重试'}), 400
    try:
        audit_log('batch_update_menu_permissions', 'menu', 0, f'{len(items)} items')
    except Exception:
        pass
    return jsonify({'message': f'已保存 {len(items)} 条菜单配置'})


# ============================================================
# 批量角色分配
# ============================================================
@app.route('/api/users/batch-roles', methods=['POST'])
@check_auth
@check_permission('users:edit')
def batch_set_roles():
    data = get_json_body()
    user_ids = data.get('user_ids', [])
    role_ids = data.get('role_ids', [])
    act = data.get('action', 'set')
    if not user_ids:
        return jsonify({'error': '请选择用户'}), 400
    if not role_ids:
        return jsonify({'error': '请选择角色'}), 400
    try:
        AuditLogService.batch_set_roles(user_ids, role_ids, act)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception:
        return jsonify({'error': '批量操作失败，请重试'}), 400
    audit_log('batch_set_roles', 'users', 0, f'users={user_ids} roles={role_ids} action={act}')
    return jsonify({'message': f'已为 {len(user_ids)} 个用户{("分配" if act!="remove" else "移除")}角色'})


@app.route('/api/logs', methods=['DELETE'])
@check_auth
@check_permission('logs:delete')
def clear_logs():
    days = request.args.get('before_days', 90, type=int)
    if days < 1 or days > 3650:
        return jsonify({'error': 'days must be 1-3650'}), 400
    try:
        count = AuditLogService.clear_logs(days)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    try:
        audit_log('clear_logs', detail='deleted ' + str(count) + ' logs older than ' + str(days) + ' days')
    except Exception:
        pass
    return jsonify({'message': 'Cleared ' + str(count) + ' logs', 'deleted': count})