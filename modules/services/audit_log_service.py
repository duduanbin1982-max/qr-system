"""qr-system — AuditLogService（操作日志 + 用户角色 + 权限矩阵 + 菜单权限）"""
from modules.services import BaseService


class AuditLogService:
    """操作日志 + 用户角色 + 权限矩阵 + 菜单权限 — 统一数据访问层。"""

    # ============================================================
    # 操作日志查询
    # ============================================================
    @staticmethod
    def list_logs(page=1, limit=50, action='', keyword='', user_id=None, category=''):
        db = BaseService.db()
        where = ['1=1']
        params = []
        if action:
            where.append('al.action = ?'); params.append(action)
        if keyword:
            where.append('(al.detail LIKE ? OR al.target_type LIKE ?)')
            params.extend([f'%{keyword}%', f'%{keyword}%'])
        if user_id:
            where.append('al.user_id = ?'); params.append(user_id)
        if category == 'permission':
            where.append('(al.action LIKE "%role%" OR al.action LIKE "%menu_permission%" OR al.action LIKE "%permission%")')
        where_sql = ' AND '.join(where)

        total = db.execute(
            f'SELECT COUNT(*) FROM audit_logs al WHERE {where_sql}', params
        ).fetchone()[0]
        rows = db.execute(f'''
            SELECT al.*, u.name as user_name
            FROM audit_logs al LEFT JOIN users u ON al.user_id = u.id
            WHERE {where_sql}
            ORDER BY al.created_at DESC LIMIT ? OFFSET ?
        ''', params + [limit, (page - 1) * limit]).fetchall()
        return {'logs': [dict(r) for r in rows], 'total': total}

    # ============================================================
    # 用户角色
    # ============================================================
    @staticmethod
    def get_user_roles(uid):
        db = BaseService.db()
        rows = db.execute('''
            SELECT r.*, rg.name as group_name
            FROM user_roles ur
            JOIN roles r ON ur.role_id = r.id
            LEFT JOIN role_groups rg ON r.group_id = rg.id
            WHERE ur.user_id = ?
            ORDER BY r.level, r.id
        ''', (uid,)).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def set_user_roles(uid, role_ids):
        with BaseService.transaction() as txn:
            txn.execute('DELETE FROM user_roles WHERE user_id = ?', (uid,))
            for rid in role_ids:
                txn.execute('INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)', (uid, rid))

    @staticmethod
    def batch_set_roles(user_ids, role_ids, action='set'):
        db = BaseService.db()
        placeholders = ','.join('?' for _ in role_ids)
        valid = {r[0] for r in db.execute(
            f'SELECT id FROM roles WHERE id IN ({placeholders})', role_ids
        ).fetchall()}
        invalid = [str(rid) for rid in role_ids if rid not in valid]
        if invalid:
            raise ValueError(f'无效角色ID: {", ".join(invalid)}')

        with BaseService.transaction() as txn:
            for uid in user_ids:
                if action == 'set':
                    txn.execute('DELETE FROM user_roles WHERE user_id = ?', (uid,))
                    for rid in role_ids:
                        txn.execute('INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)', (uid, rid))
                elif action == 'add':
                    for rid in role_ids:
                        txn.execute('INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)', (uid, rid))
                elif action == 'remove':
                    for rid in role_ids:
                        txn.execute('DELETE FROM user_roles WHERE user_id = ? AND role_id = ?', (uid, rid))

    # ============================================================
    # 权限矩阵
    # ============================================================
    @staticmethod
    def get_permission_matrix():
        db = BaseService.db()
        users = db.execute(
            "SELECT id, username, name, nickname, role, status FROM users WHERE status='active' ORDER BY id"
        ).fetchall()

        all_rows = db.execute(
            "SELECT ur.user_id, ur.role_id, r.name as role_name, r.code as role_code, "
            "r.permissions, r.status as role_status "
            "FROM user_roles ur JOIN roles r ON ur.role_id = r.id ORDER BY r.level"
        ).fetchall()

        all_roles = db.execute(
            "SELECT id, name, code, permissions, status, level FROM roles ORDER BY level"
        ).fetchall()

        return {
            'users': [dict(u) for u in users],
            'all_rows': [dict(r) for r in all_rows],
            'all_roles': [dict(r) for r in all_roles],
        }

    # ============================================================
    # 菜单权限 CRUD
    # ============================================================
    @staticmethod
    def list_menu_permissions():
        db = BaseService.db()
        rows = db.execute(
            'SELECT * FROM menu_permissions ORDER BY sort_order ASC, id ASC'
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def create_menu_permission(data):
        page = data.get('page', '').strip()
        if not page:
            raise ValueError('页面标识不能为空')
        db = BaseService.db()
        existing = db.execute(
            'SELECT id FROM menu_permissions WHERE page = ?', (page,)
        ).fetchone()
        if existing:
            raise ValueError(f'菜单页面 {page} 已存在')
        with BaseService.transaction() as txn:
            txn.execute(
                'INSERT INTO menu_permissions (page, permission, label, icon, sort_order) VALUES (?,?,?,?,?)',
                (page, data.get('permission', ''), data.get('label', ''),
                 (data.get('icon', '') or '')[:20], data.get('sort_order', 0))
            )

    @staticmethod
    def update_menu_permission(page, data):
        db = BaseService.db()
        row = db.execute(
            'SELECT id FROM menu_permissions WHERE page = ?', (page,)
        ).fetchone()
        if not row:
            raise ValueError('菜单不存在')
        updates = {}
        for field in ['permission', 'label', 'icon', 'sort_order']:
            if field in data:
                updates[field] = data[field]
        if not updates:
            raise ValueError('no fields to update')
        set_clause = ', '.join(f'{k} = ?' for k in updates)
        values = list(updates.values()) + [page]
        with BaseService.transaction() as txn:
            txn.execute(f'UPDATE menu_permissions SET {set_clause} WHERE page = ?', values)

    @staticmethod
    def delete_menu_permission(page):
        db = BaseService.db()
        row = db.execute(
            'SELECT id FROM menu_permissions WHERE page = ?', (page,)
        ).fetchone()
        if not row:
            raise ValueError('菜单不存在')
        with BaseService.transaction() as txn:
            txn.execute('DELETE FROM menu_permissions WHERE page = ?', (page,))

    @staticmethod
    def batch_update_menu_permissions(items):
        with BaseService.transaction() as txn:
            for item in items:
                page = item.get('page', '').strip()
                if not page:
                    continue
                permission = item.get('permission', '')
                label = item.get('label', '')
                icon = (item.get('icon', '') or '')[:20]
                sort_order = item.get('sort_order')
                if sort_order is not None:
                    txn.execute(
                        'UPDATE menu_permissions SET permission=?, label=?, icon=?, sort_order=? WHERE page=?',
                        (permission, label, icon, int(sort_order), page))
                else:
                    txn.execute(
                        'UPDATE menu_permissions SET permission=?, label=?, icon=? WHERE page=?',
                        (permission, label, icon, page))

    # ============================================================
    # Log cleanup
    # ============================================================
    @staticmethod
    def clear_logs(before_days=90):
        db = BaseService.db()
        with BaseService.transaction() as txn:
            cur = txn.execute(
                "DELETE FROM audit_logs WHERE created_at < datetime('now','localtime','-' || ? || ' days')",
                (str(before_days),)
            )
            return cur.rowcount
