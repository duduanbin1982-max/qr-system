"""
qr-system — 用户管理 Service 层

从 routes/users.py 提取全部业务逻辑。
路由层只负责 HTTP 解析和响应，业务逻辑集中在此。
"""
import bcrypt
import secrets
from modules.services import BaseService
from modules.services.query_utils import paginate, build_sort_clause


class UserService:
    """用户管理业务逻辑。所有方法为静态方法，接受纯数据参数。"""

    @staticmethod
    def _validate_process_ids(data):
        """共享工序校验 — 自动过滤不存在的工序ID（自愈）"""
        if 'process_ids' in data and data['process_ids']:
            id_list = [int(x.strip()) for x in data['process_ids'].split(',') if x.strip()]
            if id_list:
                placeholders = ','.join(['?'] * len(id_list))
                db = BaseService.db()
                rows = db.execute(
                    f'SELECT id FROM processes WHERE id IN ({placeholders})', id_list
                ).fetchall()
                valid_ids = set(row['id'] for row in rows)
                filtered = [str(x) for x in id_list if x in valid_ids]
                data['process_ids'] = ','.join(filtered) if filtered else ''
                data['_valid_process_ids'] = [int(x) for x in filtered] if filtered else []

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

        base_sql = f'''
            SELECT u.id, u.username, u.name, u.nickname, u.email, u.group_name, u.role, u.employee_no,
                   u.phone, u.process_ids, u.status, u.created_at,
                   (SELECT GROUP_CONCAT(up2.process_id) FROM user_processes up2 WHERE up2.user_id = u.id) as process_ids_junction, u.last_active, u.position_id,
                   u.locked_until,
                   (SELECT r.code FROM user_roles ur2 JOIN roles r ON ur2.role_id = r.id WHERE ur2.user_id = u.id ORDER BY r.level LIMIT 1) as role_code,
                   (SELECT COUNT(*) FROM user_roles ur2 WHERE ur2.user_id = u.id AND ur2.role_id = 1) > 0 as has_admin_role
            FROM users u WHERE {where_sql}
            {build_sort_clause("u.id", {"u.id": "u.id"}, default="u.id")}
        '''
        paginated_sql, all_params, size, offset = paginate(base_sql, params, page=page, page_size=limit)
        rows = db.execute(paginated_sql, all_params).fetchall()

        return {
            'users': [dict(r) for r in rows],
            'total': total,
            'page': page,
            'limit': size
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
            name = username
        if not username or not name:
            raise ValueError('用户名和姓名不能为空')
        if len(username) < 2 or len(username) > 32:
            raise ValueError('用户名长度须在2-32个字符之间')
        if not all(c.isalnum() or c in '_-.' for c in username):
            raise ValueError('用户名只能包含字母、数字、下划线、连字符和点号')

        db = BaseService.db()

        # Resolve role from DB (supports custom roles)
        role = data.get('role', 'worker')
        role_id = data.get('role_id')
        if not role_id and role:
            role_row = db.execute('SELECT id FROM roles WHERE code = ? LIMIT 1', (role,)).fetchone()
            if not role_row:
                role_row = db.execute('SELECT id FROM roles WHERE code = ? LIMIT 1', ('worker',)).fetchone()
            role_id = role_row[0] if role_row else 2
        if not role_id:
            role_id = 2

        # P0 Fix: Only admins can create users with admin-level role (role_id=1)
        if role_id == 1:
            caller_id = data.get('_caller_user_id')
            if not caller_id:
                raise ValueError('只有管理员可以创建管理员账户')
            chk = db.execute(
                'SELECT 1 FROM user_roles WHERE user_id = ? AND role_id = 1', (caller_id,)
            ).fetchone()
            if not chk:
                raise ValueError('只有管理员可以创建管理员账户')

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

        # 工序校验 — 自动过滤不存在的工序ID（自愈）
        UserService._validate_process_ids(data)

        # 工号 — 未提供则自动生成4位顺序号
        employee_no = (data.get('employee_no') or '').strip()
        if not employee_no:
            last = db.execute(
                "SELECT MAX(CAST(employee_no AS INTEGER)) as max_no FROM users WHERE employee_no GLOB '[0-9]*'"
            ).fetchone()
            next_no = (last['max_no'] or 0) + 1
            employee_no = str(next_no).zfill(4)
            # 防碰撞：若已存在则递增
            while db.execute("SELECT 1 FROM users WHERE employee_no = ?", (employee_no,)).fetchone():
                next_no += 1
                employee_no = str(next_no).zfill(4)
        data['employee_no'] = employee_no

        # 密码
        raw_pw = (data.get('password') or '').strip() or secrets.token_urlsafe(8)
        if data.get('password') and len(raw_pw) < 6:
            raise ValueError('密码长度不能少于6位')
        pw = bcrypt.hashpw(raw_pw.encode(), bcrypt.gensalt(rounds=12)).decode()

# role_id already resolved above

        with BaseService.transaction() as txn:
            cur = txn.execute(
                'INSERT INTO users (username, password, name, nickname, email, group_name, '
                'role, employee_no, phone, process_ids, position_id, status) '
                'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (username, pw, name, data.get('nickname', ''), data.get('email', ''),
                 data.get('group_name', '员工组'), role, data.get('employee_no', ''),
                 data.get('phone', ''), '', position_id or None,  # P0-2: process_ids deprecated
                 data.get('status', 'active'))
            )
            uid = cur.lastrowid
            txn.execute('INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)', (uid, role_id))
            # P1: Sync process assignments to user_processes
            valid_pids = data.get('_valid_process_ids', [])
            if not valid_pids and data.get('process_ids'):
                valid_pids = [int(x.strip()) for x in data['process_ids'].split(',') if x.strip()]
            for pid in valid_pids:
                txn.execute('INSERT OR IGNORE INTO user_processes (user_id, process_id) VALUES (?,?)', (uid, pid))

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
        existing = db.execute('SELECT id, username, name, nickname, email, phone, role, employee_no, group_name, position_id, status FROM users WHERE id = ?', (uid,)).fetchone()
        if not existing:
            raise ValueError('用户不存在')

        # 岗位校验
        if 'position_id' in data:
            position_id = data['position_id']
            if position_id:
                pos = db.execute('SELECT id FROM positions WHERE id = ?', (position_id,)).fetchone()
                if not pos:
                    raise ValueError('指定岗位不存在')

        # 工序校验 — 自动过滤不存在的工序ID（自愈）
        UserService._validate_process_ids(data)

        old_role = existing['role']

        # Compute new_role_id once for reuse
        new_role_id = None
        if ('role' in data and data['role'] != old_role) or ('role_id' in data):
            new_role_id = data.get('role_id')
            if not new_role_id:
                new_role_id = db.execute(
                    'SELECT id FROM roles WHERE code = ? LIMIT 1',
                    (data.get('role', 'worker'),)
                ).fetchone()[0]
            gn_row = db.execute(
                'SELECT rg.name FROM roles r JOIN role_groups rg ON r.group_id = rg.id WHERE r.id = ?',
                (new_role_id,)
            ).fetchone()
            if gn_row:
                data['group_name'] = gn_row[0]

        # P1-2: Only admins can promote users to admin role
        new_role_id_for_check = new_role_id
        if not new_role_id_for_check and 'role' in data:
            rr = db.execute('SELECT id FROM roles WHERE code = ? LIMIT 1', (data['role'],)).fetchone()
            new_role_id_for_check = rr[0] if rr else None
        old_role_id_for_check = db.execute(
            'SELECT id FROM roles WHERE code = ? LIMIT 1', (old_role,)
        ).fetchone()
        old_role_id_for_check = old_role_id_for_check[0] if old_role_id_for_check else None
        if new_role_id_for_check == 1 and old_role_id_for_check != 1:
            is_admin = db.execute(
                'SELECT 1 FROM user_roles WHERE user_id = ? AND role_id = 1', (current_user_id,)
            ).fetchone()
            if not is_admin:
                raise ValueError('only administrators can promote users to admin role')

        # C1: Only admins can change roles, and you cannot change your own
        if new_role_id_for_check is not None and new_role_id_for_check != old_role_id_for_check:
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
        # P2: Prevent empty employee_no UNIQUE conflict
        if 'employee_no' in data and not data['employee_no']:
            del data['employee_no']
        for field in ['name', 'nickname', 'email', 'group_name', 'role', 'employee_no',
                       'phone', 'status', 'position_id', 'department_id']:  # P0-2: process_ids removed from direct update
            if field in data:
                sets.append(f'{field} = ?')
                params.append(data[field])
        if 'password' in data and data['password']:
            sets.append('password = ?')
            params.append(bcrypt.hashpw(data['password'].encode(), bcrypt.gensalt(rounds=12)).decode())
        if not sets:
            raise ValueError('No update fields provided')

        with BaseService.transaction() as txn:
            # P1: Sync process assignments to user_processes
            if 'process_ids' in data or '_valid_process_ids' in data:
                txn.execute('DELETE FROM user_processes WHERE user_id = ?', (uid,))
                valid_pids = data.get('_valid_process_ids', [])
                if not valid_pids and data.get('process_ids'):
                    valid_pids = [int(x.strip()) for x in data['process_ids'].split(',') if x.strip()]
                for pid in valid_pids:
                    txn.execute('INSERT OR IGNORE INTO user_processes (user_id, process_id) VALUES (?,?)', (uid, pid))

            params.append(uid)
            txn.execute(f'UPDATE users SET {", ".join(sets)} WHERE id = ?', params)

            if new_role_id is not None:
                # Prevent downgrading the last admin
                if new_role_id != 1:  # changing away from admin
                    remaining = txn.execute(
                        'SELECT COUNT(*) FROM user_roles WHERE role_id = 1 AND user_id != ?', (uid,)
                    ).fetchone()[0]
                    if remaining == 0:
                        remaining2 = txn.execute(
                            "SELECT COUNT(*) FROM users WHERE role = 'admin' AND id != ?", (uid,)
                        ).fetchone()[0]
                        if remaining2 == 0:
                            raise ValueError('不能移除最后一个管理员')
                old_role_id = db.execute('SELECT id FROM roles WHERE code = ? LIMIT 1', (old_role,)).fetchone()
                old_role_id = old_role_id[0] if old_role_id else 2
                txn.execute('DELETE FROM user_roles WHERE user_id = ? AND role_id = ?', (uid, old_role_id))
                txn.execute('INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?, ?)', (uid, new_role_id))

        # P3-12: Audit field changes
        try:
            changed = []
            field_labels = {
                "name": "姓名", "nickname": "昵称", "email": "邮箱", "phone": "手机号",
                "role": "角色", "employee_no": "工号", "group_name": "角色组",
                "position_id": "岗位ID", "status": "状态"
            }
            for field, label in field_labels.items():
                old_val = existing[field] if field in existing.keys() else None
                new_val = data.get(field)
                if new_val is not None and str(old_val) != str(new_val):
                    changed.append(f"{label}: {old_val} → {new_val}")
            if "password" in data and data["password"]:
                changed.append("密码: 已修改")
            if changed:
                detail = "; ".join(changed)
                db.execute(
                    "INSERT INTO audit_logs (user_id, action, target_type, target_id, detail) VALUES (?,?,?,?,?)",
                    (current_user_id, "update_user", "user", uid, detail)
                )
                db.commit()
        except Exception:
            pass

        return True

    # ============================================================
    # 删除
    # ============================================================


    # ============================================================
    # P0-1: Soft delete ? restore & permanent delete
    # ============================================================

    @staticmethod
    def restore_user(uid):
        db = BaseService.db()
        user = db.execute("SELECT id, username FROM users WHERE id = ? AND status = 'deleted'", (uid,)).fetchone()
        if not user:
            raise ValueError('user not found or not deleted')
        db.execute("UPDATE users SET status = 'active', deleted_at = NULL WHERE id = ?", (uid,))
        db.commit()
        return True

    @staticmethod
    def permanent_delete_user(uid):
        db = BaseService.db()
        user = db.execute("SELECT id FROM users WHERE id = ? AND status = 'deleted'", (uid,)).fetchone()
        if not user:
            raise ValueError('can only permanently delete trashed users')
        with BaseService.transaction() as txn:
            txn.execute('DELETE FROM user_sessions WHERE user_id = ?', (uid,))
            txn.execute('DELETE FROM login_logs WHERE user_id = ?', (uid,))
            txn.execute('DELETE FROM user_processes WHERE user_id = ?', (uid,))
            txn.execute('DELETE FROM user_roles WHERE user_id = ?', (uid,))
            txn.execute('DELETE FROM audit_logs WHERE user_id = ?', (uid,))
            txn.execute('DELETE FROM audit_logs WHERE target_id = ? AND target_type = ?', (uid, 'user'))
            txn.execute('DELETE FROM order_remark_history WHERE user_id = ?', (uid,))
            txn.execute('DELETE FROM wage_snapshots WHERE employee_id = ?', (uid,))
            txn.execute('DELETE FROM wage_adjustments WHERE user_id = ?', (uid,))
            txn.execute('DELETE FROM users WHERE id = ?', (uid,))
        return True

    @staticmethod

    def delete_user(uid, current_user_id):

        """Soft-delete user by setting status='deleted'."""

        if uid == current_user_id:

            raise ValueError('cannot delete self')

        db = BaseService.db()

        user = db.execute("SELECT id, username FROM users WHERE id = ?", (uid,)).fetchone()

        if not user:

            raise ValueError('user not found')

        # Role-based admin check via junction table
        is_admin = db.execute(
            'SELECT 1 FROM user_roles WHERE user_id = ? AND role_id = 1', (uid,)
        ).fetchone()
        if is_admin:
            active_admins = db.execute(
                'SELECT COUNT(*) FROM user_roles WHERE role_id = 1'
            ).fetchone()[0]
            if active_admins <= 1:
                raise ValueError('cannot delete the last administrator')

        db.execute(

            "UPDATE users SET status = 'deleted', deleted_at = datetime('now','localtime') WHERE id = ?",

            (uid,)

        )

        db.commit()

        return True




    @staticmethod
    def batch_update_status(ids, status, current_user_id=None):
        """Batch update user status (active/inactive)."""
        if not ids:
            return 0
        if current_user_id and current_user_id in ids:
            raise ValueError('cannot change own status')
        if status not in ('active', 'inactive'):
            raise ValueError('invalid status')
        db = BaseService.db()
        placeholders = ','.join(['?'] * len(ids))
        cur = db.execute(
            "UPDATE users SET status = ? WHERE id IN (%s) AND status IN ('active','inactive')" % placeholders,
            [status] + ids
        )
        db.commit()
        return cur.rowcount
    @staticmethod
    def batch_delete_users(ids, current_user_id):
        """Soft-delete multiple users (set status='deleted')."""
        if not ids:
            return 0
        db = BaseService.db()
        # Prevent self-deletion
        if current_user_id in ids:
            raise ValueError('不能删除自己')
        # Prevent deleting last admin (role-based check)
        placeholders = ','.join(['?'] * len(ids))
        # Check if any of the target users have admin role
        admin_check = db.execute(
            f'SELECT COUNT(*) FROM user_roles WHERE role_id = 1 AND user_id IN ({placeholders})',
            ids
        ).fetchone()[0]
        if admin_check > 0:
            total_admins = db.execute(
                'SELECT COUNT(*) FROM user_roles WHERE role_id = 1'
            ).fetchone()[0]
            if total_admins <= admin_check:
                raise ValueError('不能移除所有管理员')
        cur = db.execute(
            f"UPDATE users SET status = 'deleted', deleted_at = datetime('now','localtime') WHERE id IN ({placeholders})",
            ids
        )
        db.commit()
        return cur.rowcount

    @staticmethod
    def reset_password(uid, password=None):
        """Reset user password with validation and account unlock.

        Args:
            uid: User ID
            password: New password (empty/None generates random 8-char token)

        Returns:
            str: New password in plaintext

        Raises:
            ValueError: User not found / password too weak / user disabled
            RuntimeError: Database error
        """
        new_pw = password if password else secrets.token_urlsafe(8)
        if password:
            if len(password) < 8:
                raise ValueError('密码至少需要8个字符')
            if not any(c.isalpha() for c in password):
                raise ValueError('密码需包含至少一个字母')
            if not any(c.isdigit() for c in password):
                raise ValueError('密码需包含至少一个数字')
        hashed = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt(rounds=12)).decode()

        db = BaseService.db()
        existing = db.execute('SELECT id, status FROM users WHERE id = ?', (uid,)).fetchone()
        if not existing:
            raise ValueError('用户不存在')
        if existing['status'] != 'active':
            raise ValueError('用户已禁用，无法重置密码')

        with BaseService.transaction() as txn:
            txn.execute(
                'UPDATE users SET password = ?, password_version = 2, '
                'must_change_password = 1, locked_until = NULL, '
                'failed_login_count = 0 WHERE id = ?',
                (hashed, uid)
            )

        return new_pw

    @staticmethod
    def unlock_user(uid):
        """Unlock user (clear brute-force lockout)."""
        db = BaseService.db()
        row = db.execute('SELECT id, username FROM users WHERE id = ?', (uid,)).fetchone()
        if not row:
            raise ValueError('用户不存在')
        with BaseService.transaction() as txn:
            txn.execute('UPDATE users SET failed_login_count = 0, locked_until = NULL WHERE id = ?', (uid,))
        return row['username']

    @staticmethod
    def import_users(filepath):
        """Import users from .xlsx file. Returns {success, skipped, errors}."""
        import openpyxl
        wb = openpyxl.load_workbook(filepath)
        ws = wb.active
        headers = [cell.value for cell in ws[1]]
        # Map Chinese headers to field names
        field_map = {
            "???": "username", "??": "name", "??": "employee_no",
            "???": "phone", "??": "email", "??": "nickname",
            "??": "position_name", "??": "role", "??": "password",
            "??(??)": "process_names",
        }
        # Also try English headers
        en_map = {k.lower(): k for k in ["username","name","employee_no","phone","email","nickname","position_name","role","password","process_names"]}
        
        col_map = {}
        for i, h in enumerate(headers):
            if h is None: continue
            h_str = str(h).strip()
            if h_str in field_map:
                col_map[i] = field_map[h_str]
            elif h_str.lower() in en_map:
                col_map[i] = en_map[h_str.lower()]
        
        if not col_map:
            raise ValueError("????????????: ???/??/??/???/??")
        
        db = BaseService.db()
        # Preload positions
        pos_rows = db.execute("SELECT id, name FROM positions WHERE status='active'").fetchall()
        pos_map = {r["name"]: r["id"] for r in pos_rows}
        
        success = 0
        skipped = 0
        errors = []
        
        for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            try:
                data = {}
                for col_idx, field in col_map.items():
                    val = row[col_idx] if col_idx < len(row) else None
                    data[field] = str(val).strip() if val is not None else ""
                
                username = data.get("username", "")
                name = data.get("name", "")
                if not username and not name:
                    skipped += 1
                    errors.append(f"?{row_idx}?: ?????")
                    continue
                if not username:
                    username = name
                if not name:
                    name = username
                
                # Check duplicate
                existing = db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
                if existing:
                    skipped += 1
                    errors.append(f"?{row_idx}?: ??? {username} ???")
                    continue
                
                # Resolve position
                pos_name = data.get("position_name", "")
                position_id = pos_map.get(pos_name) if pos_name else None
                
                # Resolve role
                role = data.get("role", "worker")
                # Resolve role from DB (supports custom roles)
                role = data.get("role", "worker")
                role_id = db.execute("SELECT id FROM roles WHERE code = ? LIMIT 1", (role,)).fetchone()
                role_id = role_id[0] if role_id else 2
                
                # Auto employee_no
                employee_no = data.get("employee_no", "")
                if not employee_no:
                    last = db.execute(
                        "SELECT MAX(CAST(employee_no AS INTEGER)) as max_no FROM users WHERE employee_no GLOB '[0-9]*'"
                    ).fetchone()
                    next_no = (last["max_no"] or 0) + 1
                    employee_no = str(next_no).zfill(4)
                
                # Password
                raw_pw = data.get("password", "") or secrets.token_urlsafe(8)
                pw_hash = bcrypt.hashpw(raw_pw.encode(), bcrypt.gensalt(rounds=12)).decode()
                
                with BaseService.transaction() as txn:
                    cur = txn.execute(
                        "INSERT INTO users (username, password, name, nickname, email, group_name, role, employee_no, phone, position_id, status, department_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (username, pw_hash, name, data.get("nickname",""), data.get("email",""),
                         "???", role, employee_no, data.get("phone",""), position_id, "active")
                    )
                    uid = cur.lastrowid
                    txn.execute("INSERT OR IGNORE INTO user_roles (user_id, role_id) VALUES (?,?)", (uid, role_id))
                
                success += 1
            except Exception as e:
                skipped += 1
                errors.append(f"?{row_idx}?: {str(e)[:80]}")
        
        wb.close()
        return {
            "success": success,
            "skipped": skipped,
            "total": success + skipped,
            "errors": errors[:20],
            "error_summary": "; ".join(errors[:5]) if errors else "",
        }

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
