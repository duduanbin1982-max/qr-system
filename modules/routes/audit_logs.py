"""
qr-system — 操作日志+权限+用户角色
"""
import json
from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO

from flask import request, jsonify, send_file, g

from modules.app import app
from modules.db import get_db, get_setting
from modules.middleware.auth import check_auth, check_permission, audit_log
from modules.middleware.helpers import get_json_body
from modules.config import PERMISSION_DEFS, generate_product_code


@app.route('/api/logs', methods=['GET'])
@check_auth
@check_permission('logs:view')
def list_logs():
    db = get_db()
    page = request.args.get('page', 1, type=int)
    limit = min(request.args.get('limit', 50, type=int), 200)
    action = request.args.get('action', '').strip()
    keyword = request.args.get('keyword', '').strip()
    user_id = request.args.get('user_id', type=int)
    category = request.args.get('category', '').strip()


    where = ['1=1']
    params = []
    if action:
        where.append('al.action = ?')
        params.append(action)
    if keyword:
        where.append('(al.detail LIKE ? OR al.target_type LIKE ?)')
        params.extend([f'%{keyword}%', f'%{keyword}%'])
    if user_id:
        where.append('al.user_id = ?')
        params.append(user_id)
    if category == 'permission':
        where.append('(al.action LIKE "%role%" OR al.action LIKE "%menu_permission%" OR al.action LIKE "%permission%")')
    where_sql = ' AND '.join(where)


    total = db.execute(f'SELECT COUNT(*) FROM audit_logs al WHERE {where_sql}', params).fetchone()[0]
    rows = db.execute(f'''
        SELECT al.*, u.name as user_name
        FROM audit_logs al LEFT JOIN users u ON al.user_id = u.id
        WHERE {where_sql}
        ORDER BY al.created_at DESC LIMIT ? OFFSET ?
    ''', params + [limit, (page - 1) * limit]).fetchall()
    return jsonify({'logs': [dict(r) for r in rows], 'total': total})

# ============================================================
# Permissions API (权限定义)
# ============================================================
@app.route('/api/permissions', methods=['GET'])
@check_auth
def list_permissions():
    """
    返回权限定义列表，供前端渲染权限勾选
    ---
    tags:
      - Audit
    summary: 返回权限定义列表，供前端渲染权限勾选
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    perms = []
    for code, (label, actions) in PERMISSION_DEFS.items():
        perms.append({
            'code': code,
            'label': label,
            'actions': actions,
        })
    return jsonify({'permissions': perms})

# ============================================================
# User Roles API (用户角色分配)
# ============================================================
@app.route('/api/users/<int:uid>/roles', methods=['GET'])
@check_auth
@check_permission('users:view')
def get_user_roles(uid):
    """
    获取用户已分配的角色
    ---
    tags:
      - Audit
    summary: 获取用户已分配的角色
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    db = get_db()
    rows = db.execute('''
        SELECT r.*, rg.name as group_name
        FROM user_roles ur
        JOIN roles r ON ur.role_id = r.id
        LEFT JOIN role_groups rg ON r.group_id = rg.id
        WHERE ur.user_id = ?
        ORDER BY r.level, r.id
    ''', (uid,)).fetchall()
    return jsonify({'roles': [dict(r) for r in rows]})

@app.route('/api/users/<int:uid>/roles', methods=['PUT'])
@check_auth
@check_permission('users:edit')
def set_user_roles(uid):
    """
    设置用户角色（替换全部）
    ---
    tags:
      - Audit
    summary: 设置用户角色（替换全部）
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    data = get_json_body()
    role_ids = data.get('role_ids', [])
    db = get_db()
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('DELETE FROM user_roles WHERE user_id = ?', (uid,))
        for rid in role_ids:
            db.execute('INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)', (uid, rid))
        db.commit()
    except Exception as e:
        db.execute('ROLLBACK')
        return jsonify({'error': str(e)}), 400
    try:
        audit_log('set_user_roles', 'user', uid, f'roles={role_ids}')
    except Exception:
        pass
    return jsonify({'message': '角色分配成功'})

# ============================================================
# 权限矩阵 (用户权限总览)
# ============================================================
def _parse_permissions(raw):
    """
    安全解析权限JSON，返回权限列表
    ---
    tags:
      - Audit
    summary: 安全解析权限JSON，返回权限列表
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    if not raw:
        return []
    try:
        import json
        arr = json.loads(raw)
        if isinstance(arr, list):
            return arr
        if isinstance(arr, dict):
            # 兼容旧格式 {"report": true} → 转为 ["report:view"]
            return [f"{k}:view" for k, v in arr.items() if v]
        return []
    except:
        return []

@app.route('/api/permission-matrix', methods=['GET'])
@check_auth
@check_permission('settings:manage')
def get_permission_matrix():
    """
    返回所有活跃用户的权限矩阵（含来源标注 + 筛选）
    ---
    tags:
      - Audit
    summary: 返回所有活跃用户的权限矩阵（含来源标注 + 筛选）
    responses:
      200:
        description: OK
    security:
      - Bearer: []
    """
    db = get_db()
    filter_role_id = request.args.get('role_id', type=int)
    filter_group_id = request.args.get('group_id', type=int)
    filter_perm = request.args.get('perm', '').strip().lower()

    users = db.execute("SELECT id, username, name, nickname, role, status FROM users WHERE status='active' ORDER BY id").fetchall()
    if not users:
        return jsonify({'matrix': []})

    # Batch: get all user-role-permission mappings in 2 queries
    user_ids = [u['id'] for u in users]
    uid_placeholders = ','.join('?' for _ in user_ids)

    # Query 1: all permissions for all users
    all_rows = db.execute(f'''
        SELECT ur.user_id, r.permissions, r.name as role_name,
               rg.permissions as group_permissions, rg.name as group_name
        FROM user_roles ur
        JOIN roles r ON ur.role_id = r.id
        LEFT JOIN role_groups rg ON r.group_id = rg.id
        WHERE ur.user_id IN ({uid_placeholders}) AND r.status = 'active'
    ''', user_ids).fetchall()

    # Query 2: all roles for all users
    all_roles = db.execute(f'''
        SELECT ur.user_id, r.id, r.name, r.code, rg.name as group_name, r.group_id
        FROM user_roles ur
        JOIN roles r ON ur.role_id = r.id
        LEFT JOIN role_groups rg ON r.group_id = rg.id
        WHERE ur.user_id IN ({uid_placeholders})
    ''', user_ids).fetchall()

    # Group by user_id
    perm_rows_by_user = {}
    for row in all_rows:
        uid = row['user_id']
        if uid not in perm_rows_by_user:
            perm_rows_by_user[uid] = []
        perm_rows_by_user[uid].append(row)

    roles_by_user = {}
    for row in all_roles:
        uid = row['user_id']
        if uid not in roles_by_user:
            roles_by_user[uid] = []
        roles_by_user[uid].append(dict(row))

    matrix = []
    for u in users:
        uid = u['id']
        rows = perm_rows_by_user.get(uid, [])

        all_perms = set()
        sources = {}
        for row in rows:
            role_perms = _parse_permissions(row['permissions'])
            group_perms = _parse_permissions(row['group_permissions'])
            for p in role_perms:
                all_perms.add(p)
                if p not in sources:
                    sources[p] = {'source_type': 'role', 'source_name': row['role_name']}
            for p in group_perms:
                all_perms.add(p)
                if p not in sources:
                    sources[p] = {'source_type': 'group', 'source_name': row['group_name']}

        perms_list = sorted(all_perms)
        roles = roles_by_user.get(uid, [])

        if filter_perm and "*" not in perms_list and not any(filter_perm in p.lower() for p in perms_list):
            continue
        if filter_role_id and not any(r['id'] == filter_role_id for r in roles):
            continue
        if filter_group_id and not any(r.get('group_id') == filter_group_id for r in roles):
            continue

        matrix.append({
            'user': dict(u),
            'roles': roles,
            'permissions': perms_list,
            'permission_sources': [{'permission': p, **s} for p, s in sorted(sources.items())],
            'perm_count': len(perms_list)
        })

    return jsonify({'matrix': matrix})

# ============================================================
# 菜单权限映射
# ============================================================
@app.route('/api/menu-permissions', methods=['GET'])
@check_auth
@check_permission('settings:manage')
def list_menu_permissions():
    db = get_db()
    rows = db.execute('SELECT * FROM menu_permissions ORDER BY sort_order ASC, id ASC').fetchall()
    return jsonify({'menu_permissions': [dict(r) for r in rows]})

@app.route('/api/menu-permissions', methods=['POST'])
@check_auth
@check_permission('settings:manage')
def create_menu_permission():
    data = get_json_body()
    page = data.get('page', '').strip()
    permission = data.get('permission', '')
    label = data.get('label', '')
    icon = data.get('icon', '')[:20]
    sort_order = max(0, data.get('sort_order', 999))
    if not page:
        return jsonify({'error': 'menu page required'}), 400
    db = get_db()
    existing = db.execute('SELECT id FROM menu_permissions WHERE page = ?', (page,)).fetchone()
    if existing:
        return jsonify({'error': 'menu already exists'}), 409
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute(
            'INSERT INTO menu_permissions (page, permission, label, icon, sort_order) VALUES (?, ?, ?, ?, ?)',
            (page, permission, label, icon, sort_order)
        )
        db.commit()
    except Exception as e:
        db.execute('ROLLBACK')
        err = str(e)
        if 'UNIQUE' in err:
            return jsonify({'error': 'menu already exists'}), 409
        return jsonify({'error': err}), 400
    try:
        audit_log('create_menu_permission', 'menu', 0, '{0}={1}'.format(page, permission))
    except Exception:
        pass
    return jsonify({'message': 'created', 'page': page})

@app.route('/api/menu-permissions/<page>', methods=['PUT'])
@check_auth
@check_permission('settings:manage')
def update_menu_permission(page):
    data = get_json_body()
    db = get_db()
    row = db.execute('SELECT id FROM menu_permissions WHERE page = ?', (page,)).fetchone()
    if not row:
        return jsonify({'error': 'menu not found'}), 404
    updates = {}
    for field in ['permission', 'label', 'icon', 'sort_order']:
        if field in data:
            updates[field] = data[field]
    if not updates:
        return jsonify({'error': 'no fields to update'}), 400
    set_clause = ', '.join('{0} = ?'.format(k) for k in updates.keys())
    values = list(updates.values()) + [page]
    db.execute('BEGIN IMMEDIATE')
    try:
        db.execute('UPDATE menu_permissions SET {0} WHERE page = ?'.format(set_clause), values)
        db.commit()
    except Exception as e:
        db.execute('ROLLBACK')
        return jsonify({'error': str(e)}), 400
    try:
        audit_log('update_menu_permission', 'menu', 0, '{0} updated'.format(page))
    except Exception:
        pass
    return jsonify({'message': 'updated'})

@app.route('/api/menu-permissions/<page>', methods=['DELETE'])
@check_auth
@check_permission('settings:manage')
def delete_menu_permission(page):
    db = get_db()
    row = db.execute('SELECT id FROM menu_permissions WHERE page = ?', (page,)).fetchone()
    if not row:
        return jsonify({'error': 'menu not found'}), 404
    try:
        db.execute('BEGIN IMMEDIATE')
    except (sqlite3.OperationalError, ValueError):
        pass
    db.execute('DELETE FROM menu_permissions WHERE page = ?', (page,))
    db.commit()
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
    db = get_db()
    try:
        db.execute('BEGIN IMMEDIATE')
    except (sqlite3.OperationalError, ValueError):
        pass
    try:
        for item in items:
            page = item.get('page', '').strip()
            if not page:
                continue
            permission = item.get('permission', '')
            label = item.get('label', '')
            icon = (item.get('icon', '') or '')[:20]
            sort_order = item.get('sort_order')
            if sort_order is not None:
                db.execute('UPDATE menu_permissions SET permission=?, label=?, icon=?, sort_order=? WHERE page=?',
                           (permission, label, icon, int(sort_order), page))
            else:
                db.execute('UPDATE menu_permissions SET permission=?, label=?, icon=? WHERE page=?',
                           (permission, label, icon, page))
        db.commit()
    except Exception:
        db.execute('ROLLBACK')
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
    action = data.get('action', 'set')
    if not user_ids:
        return jsonify({'error': '请选择用户'}), 400
    if not role_ids:
        return jsonify({'error': '请选择角色'}), 400
    db = get_db()
    # Validate role_ids
    placeholders = ','.join('?' for _ in role_ids)
    valid = {r[0] for r in db.execute(f'SELECT id FROM roles WHERE id IN ({placeholders})', role_ids).fetchall()}
    invalid = [str(rid) for rid in role_ids if rid not in valid]
    if invalid:
        return jsonify({'error': f'无效角色ID: {", ".join(invalid)}'}), 400
    try:
        db.execute('BEGIN IMMEDIATE')
    except (sqlite3.OperationalError, ValueError):
        pass
    try:
        for uid in user_ids:
            if action == 'set':
                db.execute('DELETE FROM user_roles WHERE user_id = ?', (uid,))
                for rid in role_ids:
                    db.execute('INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)', (uid, rid))
            elif action == 'add':
                for rid in role_ids:
                    db.execute('INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)', (uid, rid))
            elif action == 'remove':
                for rid in role_ids:
                    db.execute('DELETE FROM user_roles WHERE user_id = ? AND role_id = ?', (uid, rid))
        db.commit()
    except Exception:
        db.execute('ROLLBACK')
        return jsonify({'error': '批量操作失败，请重试'}), 400
    audit_log('batch_set_roles', 'users', 0, f'users={user_ids} roles={role_ids} action={action}')
    return jsonify({'message': f'已为 {len(user_ids)} 个用户{("分配" if action!="remove" else "移除")}角色'})
