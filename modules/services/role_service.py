"""
qr-system — 角色组 + 角色管理 Service 层
"""
from modules.services import BaseService


class RoleGroupService:

    @staticmethod
    def list_groups():
        db = BaseService.db()
        rows = db.execute('SELECT * FROM role_groups ORDER BY id').fetchall()
        return {'role_groups': [dict(r) for r in rows]}

    @staticmethod
    def create_group(data):
        name = data.get('name', '').strip()
        if not name:
            raise ValueError('角色组名称不能为空')
        db = BaseService.db()
        if db.execute('SELECT id FROM role_groups WHERE name = ?', (name,)).fetchone():
            raise ValueError(f'角色组名称【{name}】已存在')
        parent_id = data.get('parent_id')
        if parent_id is not None:
            if not db.execute('SELECT id FROM role_groups WHERE id = ?', (parent_id,)).fetchone():
                raise ValueError('父级角色组不存在')
            # 新建时不需循环检测（父级已存在，子级尚未创建，不会形成环）
        with BaseService.transaction() as txn:
            cur = txn.execute(
                'INSERT INTO role_groups (name, description, parent_id, status, permissions) '
                'VALUES (?,?,?,?,?)',
                (name, data.get('description', ''), parent_id,
                 data.get('status', 'active'), data.get('permissions', '')))
            return cur.lastrowid

    @staticmethod
    def update_group(gid, data):
        db = BaseService.db()
        existing = db.execute(
            'SELECT id, name FROM role_groups WHERE id = ?', (gid,)).fetchone()
        if not existing:
            raise ValueError('角色组不存在')

        if 'parent_id' in data:
            pid = data['parent_id']
            if pid is not None:
                if pid == gid:
                    raise ValueError('不能将自身设为父级')
                if not db.execute('SELECT id FROM role_groups WHERE id = ?', (pid,)).fetchone():
                    raise ValueError('父级角色组不存在')
                to_check = [pid]; visited = {gid}
                while to_check:
                    cur = to_check.pop()
                    if cur in visited:
                        raise ValueError('不能建立循环引用')
                    visited.add(cur)
                    children = db.execute(
                        'SELECT parent_id FROM role_groups WHERE id = ? AND parent_id IS NOT NULL',
                        (cur,)).fetchall()
                    for c in children:
                        if c['parent_id'] not in visited:
                            to_check.append(c['parent_id'])

        if 'name' in data:
            new_name = data['name'].strip()
            if not new_name:
                raise ValueError('角色组名称不能为空')
            dup = db.execute(
                'SELECT id FROM role_groups WHERE name = ? AND id != ?', (new_name, gid)).fetchone()
            if dup:
                raise ValueError(f'角色组名称【{new_name}】已存在')
            data['name'] = new_name

        # 列名来自硬编码白名单，安全
        sets = []; params = []
        for field in ['name', 'description', 'parent_id', 'status', 'permissions']:
            if field in data:
                sets.append(f'{field} = ?')
                params.append(data[field])
        if not sets:
            raise ValueError('无更新内容')

        with BaseService.transaction() as txn:
            txn.execute(f'UPDATE role_groups SET {", ".join(sets)} WHERE id = ?', params + [gid])

    @staticmethod
    def delete_group(gid):
        db = BaseService.db()
        children = db.execute(
            'SELECT COUNT(*) FROM role_groups WHERE parent_id = ?', (gid,)).fetchone()[0]
        if children > 0:
            raise ValueError('该角色组有下级，无法删除')
        role_count = db.execute(
            'SELECT COUNT(*) FROM roles WHERE group_id = ?', (gid,)).fetchone()[0]
        if role_count > 0:
            raise ValueError(f'该角色组下有 {role_count} 个角色，无法删除')
        with BaseService.transaction() as txn:
            txn.execute('DELETE FROM role_groups WHERE id = ?', (gid,))


# Built-in role IDs (cannot be deleted)
BUILTIN_ROLE_IDS = (1, 2)


class RoleService:

    @staticmethod
    def list_roles():
        db = BaseService.db()
        rows = db.execute('''
            SELECT r.*, rg.name as group_name
            FROM roles r
            LEFT JOIN role_groups rg ON r.group_id = rg.id
            ORDER BY r.level, r.id
        ''').fetchall()
        return {'roles': [dict(r) for r in rows]}

    @staticmethod
    def create_role(data):
        name = data.get('name', '').strip()
        code = data.get('code', '').strip()
        if not name or not code:
            raise ValueError('角色名称和编码不能为空')
        db = BaseService.db()
        group_id = data.get('group_id')
        if group_id and not db.execute('SELECT id FROM role_groups WHERE id = ?', (group_id,)).fetchone():
            raise ValueError('所属角色组不存在')
        parent_id = data.get('parent_id')
        if parent_id and not db.execute('SELECT id FROM roles WHERE id = ?', (parent_id,)).fetchone():
            raise ValueError('父级角色不存在')
        if db.execute('SELECT id FROM roles WHERE code = ?', (code,)).fetchone():
            raise ValueError(f'角色编码【{code}】已存在')
        with BaseService.transaction() as txn:
            cur = txn.execute(
                'INSERT INTO roles (name, code, description, group_id, parent_id, '
                'level, permissions, status) VALUES (?,?,?,?,?,?,?,?)',
                (name, code, data.get('description', ''), group_id, parent_id,
                 data.get('level', 1), data.get('permissions', ''), data.get('status', 'active')))
            return cur.lastrowid

    @staticmethod
    def update_role(rid, data):
        db = BaseService.db()
        role = db.execute('SELECT id, name FROM roles WHERE id = ?', (rid,)).fetchone()
        if not role:
            raise ValueError('角色不存在')
        if 'group_id' in data and data['group_id']:
            if not db.execute('SELECT id FROM role_groups WHERE id = ?', (data['group_id'],)).fetchone():
                raise ValueError('所属角色组不存在')
        if 'parent_id' in data and data['parent_id']:
            if data['parent_id'] == rid:
                raise ValueError('不能将自身设为父级')
            if not db.execute('SELECT id FROM roles WHERE id = ?', (data['parent_id'],)).fetchone():
                raise ValueError('父级角色不存在')
        if 'code' in data:
            new_code = data['code'].strip()
            if not new_code:
                raise ValueError('角色编码不能为空')
            dup = db.execute('SELECT id FROM roles WHERE code = ? AND id != ?', (new_code, rid)).fetchone()
            if dup:
                raise ValueError(f'角色编码【{new_code}】已存在')
            data['code'] = new_code
        if 'name' in data and not data['name'].strip():
            raise ValueError('角色名称不能为空')

        sets = []; params = []
        for field in ['name', 'code', 'description', 'group_id', 'parent_id',
                      'level', 'permissions', 'status']:
            if field in data:
                sets.append(f'{field} = ?')
                params.append(data[field])
        if not sets:
            raise ValueError('无更新内容')

        with BaseService.transaction() as txn:
            txn.execute(f'UPDATE roles SET {", ".join(sets)} WHERE id = ?', params + [rid])

    @staticmethod
    def delete_role(rid):
        db = BaseService.db()
        role = db.execute('SELECT id, name FROM roles WHERE id = ?', (rid,)).fetchone()
        if not role:
            raise ValueError('角色不存在')
        if rid in BUILTIN_ROLE_IDS:
            raise ValueError(f'不能删除内置角色「{role["name"]}」')
        with BaseService.transaction() as txn:
            txn.execute('DELETE FROM roles WHERE id = ?', (rid,))
