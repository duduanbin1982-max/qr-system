"""
qr-system — 岗位管理 Service 层
"""
from modules.services import BaseService


class PositionService:

    @staticmethod
    def list_positions(page=1, limit=100):
        db = BaseService.db()
        total = db.execute('SELECT COUNT(*) FROM positions').fetchone()[0]
        offset = (page - 1) * limit
        rows = db.execute(
            'SELECT * FROM positions ORDER BY id LIMIT ? OFFSET ?',
            (limit, offset)
        ).fetchall()
        pos_ids = [r['id'] for r in rows]
        proc_map = {}
        if pos_ids:
            # placeholders are all '?' chars from trusted integer list
            procs = db.execute(
                f'SELECT pp.position_id, pp.process_id, p.name as process_name'
                f' FROM position_processes pp'
                f' JOIN processes p ON pp.process_id = p.id'
                f' WHERE pp.position_id IN ({",".join("?" for _ in pos_ids)})',
                pos_ids
            ).fetchall()
            for p in procs:
                proc_map.setdefault(p['position_id'], []).append(dict(p))
        result = []
        for r in rows:
            pos = dict(r)
            pos['processes'] = proc_map.get(pos['id'], [])
            result.append(pos)
        return {'positions': result, 'total': total, 'page': page, 'limit': limit}

    @staticmethod
    def create_position(data):
        name = data.get('name', '').strip()
        if not name:
            raise ValueError('岗位名称不能为空')
        process_ids = data.get('process_ids', [])
        if process_ids:
            db = BaseService.db()
            placeholders = ','.join('?' for _ in process_ids)
            valid = {r[0] for r in db.execute(
                f'SELECT id FROM processes WHERE id IN ({placeholders})', process_ids
            ).fetchall()}
            invalid = [str(pid) for pid in process_ids if pid not in valid]
            if invalid:
                raise ValueError(f'无效工序ID: {", ".join(invalid)}')
        import sqlite3
        with BaseService.transaction() as txn:
            if txn.execute(
                'SELECT id FROM positions WHERE name = ?', (name,)
            ).fetchone():
                raise ValueError(f'岗位名称【{name}】已存在')
            try:
                cur = txn.execute(
                    'INSERT INTO positions (name, description, status) VALUES (?, ?, ?)',
                    (name, data.get('description', ''), data.get('status', 'active')))
            except sqlite3.IntegrityError:
                raise ValueError(f'岗位名称【{name}】已存在')
            pos_id = cur.lastrowid
            for pid in process_ids:
                txn.execute(
                    'INSERT OR IGNORE INTO position_processes (position_id, process_id) '
                    'VALUES (?, ?)', (pos_id, pid))
            return pos_id

    @staticmethod
    def update_position(pos_id, data):
        db = BaseService.db()
        pos = db.execute('SELECT * FROM positions WHERE id = ?', (pos_id,)).fetchone()
        if not pos:
            raise ValueError('岗位不存在')
        if 'name' in data:
            data['name'] = data['name'].strip()
            if not data['name']:
                raise ValueError('岗位名称不能为空')
        if 'process_ids' in data:
            pids = data['process_ids']
            if pids:
                placeholders = ','.join('?' for _ in pids)
                valid = {r[0] for r in db.execute(
                    f'SELECT id FROM processes WHERE id IN ({placeholders})', pids
                ).fetchall()}
                invalid = [str(pid) for pid in pids if pid not in valid]
                if invalid:
                    raise ValueError(f'无效工序ID: {", ".join(invalid)}')

        sets = []
        params = []
        for field in ['name', 'description', 'status']:
            if field in data:
                val = data[field].strip() if isinstance(data[field], str) else data[field]
                sets.append(f'{field} = ?')
                params.append(val)
        changed = len(sets) > 0
        if 'process_ids' in data:
            changed = True
        if not changed:
            raise ValueError('无更新内容')

        sets.append('updated_at = datetime("now","localtime")')
        with BaseService.transaction() as txn:
            if 'name' in data:
                dup = txn.execute(
                    'SELECT id FROM positions WHERE name = ? AND id != ?',
                    (data['name'], pos_id)).fetchone()
                if dup:
                    raise ValueError(f'岗位名称【{data["name"]}】已存在')
            if sets:
                txn.execute(
                    f'UPDATE positions SET {", ".join(sets)} WHERE id = ?',
                    params + [pos_id])
            if 'process_ids' in data:
                txn.execute(
                    'DELETE FROM position_processes WHERE position_id = ?', (pos_id,))
                for pid in data['process_ids']:
                    txn.execute(
                        'INSERT OR IGNORE INTO position_processes '
                        '(position_id, process_id) VALUES (?, ?)', (pos_id, pid))

    @staticmethod
    def delete_position(pos_id):
        db = BaseService.db()
        pos = db.execute('SELECT * FROM positions WHERE id = ?', (pos_id,)).fetchone()
        if not pos:
            raise ValueError('岗位不存在')
        user_count = db.execute(
            'SELECT COUNT(*) FROM users WHERE position_id = ?', (pos_id,)
        ).fetchone()[0]
        if user_count > 0:
            raise ValueError("该岗位下有 " + str(user_count) + " 个用户，请先将用户调岗后再删除")
        with BaseService.transaction() as txn:
            txn.execute('DELETE FROM positions WHERE id = ?', (pos_id,))
        return pos['name']
