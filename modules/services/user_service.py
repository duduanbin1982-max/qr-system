"""
qr-system — 用户管理 Service 层

从 routes/users.py 提取全部业务逻辑。
路由层只负责 HTTP 解析和响应，业务逻辑集中在此。
"""
import bcrypt
import secrets
from modules.services import BaseService


class UserService:
    """用户管理业务逻辑。所有方法为静态方法，接受纯数据参数。"""

    # ============================================================
    # 查询
    # ============================================================

    @staticmethod
    def list_users(page=1, limit=20, role_filter='', keyword='', status=''):
        """
        分页查询用户列表。

        Returns:
            dict: {users, total, page, limit}
        """
        db = BaseService.db()
        page = max(page, 1)
        limit = min(max(limit, 1), 200)

        where = ['1=1']
        params = []
        if role_filter:
            where.append('role = ?')
            params.append(role_filter)
        if status:
            where.append('status = ?')
            params.append(status)
        if keyword:
            where.append('(username LIKE ? OR name LIKE ? OR nickname LIKE ? OR employee_no LIKE ? OR phone LIKE ?)')
            kw = f'%{keyword}%'
            params.extend([kw, kw, kw, kw, kw])

        where_sql = ' AND '.join(where)
        total = db.execute(f'SELECT COUNT(*) FROM users WHERE {where_sql}', params).fetchone()[0]

        rows = db.execute(f'''
            SELECT u.id, u.username, u.name, u.nickname, u.email, u.group_name, u.role, u.employee_no,
                   u.phone, u.process_ids, u.status, u.created_at, u.last_active, u.position_id,
                   u.locked_until,
                   (SELECT COUNT(*) FROM user_roles ur2 WHERE ur2.user_id = u.id AND ur2.role_id = 1) > 0 as has_admin_role
            FROM users u WHERE {where_sql}
            ORDER BY u.id LIMIT ? OFFSET ?
        ''', params + [limit, (page - 1) * limit]).fetchall()

        return {
            'users': [dict(r) for r in rows],
            'total': total,
            'page': page,
            'limit': limit
        }

    # ============================================================
    # 创建
    # ============================================================

    @staticmethod
    def create_user(data):
        """
        创建新用户。

        Args:
            data: dict with username, name, role, etc.

        Returns:
            (uid, password): 新用户 ID 和密码（用于通知管理员）

        Raises:
            ValueError: 参数校验失败
            RuntimeError: 数据库错误
        """
        username = data.get('username', '').strip()
        name = data.get('name', '').strip()
        if not name and data.get('role') == 'admin':
            name = data.get('nickname', '').strip()
        if not username or not name:
            raise ValueError('用户名和姓名不能为空')

        role = data.get('role', 'worker')
        if role not in ('admin', 'worker'):
            raise ValueError('角色值无效，仅允许 admin/worker')

        db = BaseService.db()

        # 唯一性检查
        existing = db.execute('SELECT id FROM users WHERE username = ?', (username,)).fetchone()
        if existing:
            raise ValueError('用户名已存在')

        # 岗位校验
        position_id = data.get('position_id')
        if position_id:
            pos = db.execute('SELECT id FROM positions WHERE id = ?', (position_id,)).fetchone()
            if not pos:
                raise ValueError('指定岗位不存在')

        # 工序校验
        process_ids_str = data.get('process_ids', '')
        if process_ids_str:
            id_list = [int(x.strip()) for x in process_ids_str.split(',') if x.strip()]
            if id_list:
                placeholders = ','.join(['?'] * len(id_list))
                cnt = db.execute(
                    f'SELECT COUNT(*) as n FROM processes WHERE id IN ({placeholders})', id_list
                ).fetchone()['n']
                if cnt < len(id_list):
                    raise ValueError('部分工序ID不存在')

        # 密码
        raw_pw = data.get('password') or secrets.token_urlsafe(8)
        pw = bcrypt.hashpw(raw_pw.encode(), bcrypt.gensalt(rounds=12)).decode()

        role_id = 1 if role == 'admin' else 2

        with BaseService.transaction() as txn:
            cur = txn.execute(
                'INSERT INTO users (username, password, name, nickname, email, group_name, '
                'role, employee_no, phone, process_ids, position_id, status) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (username, pw, name, data.get('nickname', ''), data.get('email', ''),
                 data.get('group_name', '超级管理组'), role, data.get('employee_no', ''),
                 data.get('phone', ''), data.get('process_ids', ''), position_id or None,
                 data.get('status', 'active'))
            )
            uid = cur.lastrowid
            txn.execute('INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)', (uid, role_id))

        return uid, raw_pw

    # ============================================================
    # 更新
    # ============================================================

    @staticmethod
    def update_user(uid, data, current_user_id=None):
        """
        更新用户信息。

        Args:
            uid: 用户 ID
            data: 要更新的字段 dict

        Raises:
            ValueError: 参数校验失败 / 用户不存在
            RuntimeError: 数据库错误
        """
        db = BaseService.db()
        existing = db.execute('SELECT id, role, position_id FROM users WHERE id = ?', (uid,)).fetchone()
        if not existing:
            raise ValueError('用户不存在')

        # 岗位校验
        if 'position_id' in data:
            position_id = data['position_id']
            if position_id:
                pos = db.execute('SELECT id FROM positions WHERE id = ?', (position_id,)).fetchone()
                if not pos:
                    raise ValueError('指定岗位不存在')

        # 工序校验
        if 'process_ids' in data and data['process_ids']:
            id_list = [int(x.strip()) for x in data['process_ids'].split(',') if x.strip()]
            if id_list:
                placeholders = ','.join(['?'] * len(id_list))
                cnt = db.execute(
                    f'SELECT COUNT(*) as n FROM processes WHERE id IN ({placeholders})', id_list
                ).fetchone()['n']
                if cnt < len(id_list):
                    raise ValueError('部分工序ID不存在')

        old_role = existing['role']

        # C1: Only admins can change roles, and you cannot change your own
        if 'role' in data and data['role'] != old_role:
            if current_user_id is None:
                raise ValueError('Only administrators can change roles')
            if current_user_id == uid:
                raise ValueError('Cannot change your own role')
            admin_check = db.execute(
                'SELECT 1 FROM user_roles WHERE user_id = ? AND role_id = 1', (current_user_id,)
            ).fetchone()
            if not admin_check:
                raise ValueError('Only administrators can change roles')

        sets = []
        params = []
        for field in ['name', 'nickname', 'email', 'group_name', 'role', 'employee_no',
                       'phone', 'process_ids', 'status', 'position_id']:
            if field in data:
                sets.append(f'{field} = ?')
                params.append(data[field])
        if 'password' in data and data['password']:
            sets.append('password = ?')
            params.append(bcrypt.hashpw(data['password'].encode(), bcrypt.gensalt(rounds=12)).decode())
        if not sets:
            raise ValueError('No update fields provided')

        with BaseService.transaction() as txn:
            params.append(uid)
            txn.execute(f'UPDATE users SET {", ".join(sets)} WHERE id = ?', params)

            if 'role' in data and data['role'] != old_role:
                new_role_id = 1 if data['role'] == 'admin' else 2
                old_role_id = 1 if old_role == 'admin' else 2
                txn.execute('DELETE FROM user_roles WHERE user_id = ? AND role_id = ?', (uid, old_role_id))
                txn.execute('INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)', (uid, new_role_id))

        return True

    # ============================================================
    # 删除
    # ============================================================

    @staticmethod
    def delete_user(uid, current_user_id):
        """
        删除用户。

        Args:
            uid: 要删除的用户 ID
            current_user_id: 当前操作用户的 ID（用于禁止自杀）

        Raises:
            ValueError: 校验失败
            RuntimeError: 数据库错误（含 FK 约束）
        """
        if uid == current_user_id:
            raise ValueError('不能删除自己')

        db = BaseService.db()
        user = db.execute('SELECT id, username FROM users WHERE id = ?', (uid,)).fetchone()
        if not user:
            raise ValueError('用户不存在')
        if user['username'] == 'admin':
            raise ValueError('Cannot delete the built-in admin account')

        # C2 FIX: Don't delete the last admin
        admin_count = db.execute(
            'SELECT COUNT(*) FROM user_roles WHERE role_id = 1'
        ).fetchone()[0]
        is_admin = db.execute(
            'SELECT 1 FROM user_roles WHERE user_id = ? AND role_id = 1', (uid,)
        ).fetchone()
        if is_admin and admin_count <= 1:
            raise ValueError('Cannot delete the last administrator')

        with BaseService.transaction() as txn:
            txn.execute('DELETE FROM user_roles WHERE user_id = ?', (uid,))
            txn.execute('DELETE FROM users WHERE id = ?', (uid,))

        return True

    # ============================================================
    # 密码重置
    # ============================================================

    @staticmethod
    def reset_password(uid, password=None):
        """
        重置用户密码。

        Args:
            uid: 用户 ID
            password: 新密码（空字符串 / None 则自动生成随机密码）

        Returns:
            str: 新密码（明文，用于返回给管理员）

        Raises:
            ValueError: 用户不存在
            RuntimeError: 数据库错误
        """
        new_pw = password if password else secrets.token_urlsafe(8)
        hashed = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt(rounds=12)).decode()

        db = BaseService.db()
        existing = db.execute('SELECT id FROM users WHERE id = ?', (uid,)).fetchone()
        if not existing:
            raise ValueError('用户不存在')

        with BaseService.transaction() as txn:
            txn.execute('UPDATE users SET password = ? WHERE id = ?', (hashed, uid))

        return new_pw

    @staticmethod
    def unlock_user(uid):
        """Unlock user (clear brute-force lockout)."""
        db = BaseService.db()
        row = db.execute('SELECT id, username FROM users WHERE id = ?', (uid,)).fetchone()
        if not row:
            raise ValueError('User not found')
        with BaseService.transaction() as txn:
            txn.execute('UPDATE users SET failed_login_count = 0, locked_until = NULL WHERE id = ?', (uid,))
        return row['username']

    # ============================================================
    # 辅助
    # ============================================================

    @staticmethod
    def get_user(uid):
        """获取单个用户（不含密码）。"""
        db = BaseService.db()
        row = db.execute('SELECT * FROM users WHERE id = ?', (uid,)).fetchone()
        if not row:
            raise ValueError('用户不存在')
        u = dict(row)
        u.pop('password', None)
        u.pop('token', None)
        return u
