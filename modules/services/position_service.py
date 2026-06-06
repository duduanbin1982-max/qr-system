"""
qr-system — 岗位管理 Service 层
"""
from modules.services import BaseService


class PositionService:

    @staticmethod
    def list_positions():
        db = BaseService.db()
        rows = db.execute('SELECT * FROM positions ORDER BY id').fetchall()
        pos_ids = [r['id'] for r in rows]
        proc_map = {}
        if pos_ids:
            procs = db.execute(f'''
                SELECT pp.position_id, pp.process_id, p.name as process_name
                FROM position_processes pp
                JOIN processes p ON pp.process_id = p.id
                WHERE pp.position_id IN ({",".join("?" for _ in pos_ids)})
            ''', pos_ids).fetchall()
            for p in procs:
                proc_map.setdefault(p['position_id'], []).append(dict(p))
        result = []
        for r in rows:
            pos = dict(r)
            pos['processes'] = proc_map.get(pos['id'], [])
            result.append(pos)
        return {'positions': result}

    @staticmethod
    def create_position(data):
        name = data.get('name', '').strip()
        if not name:
            raise ValueError('岗位名称不能为空')
        db = BaseService.db()
        if db.execute('SELECT id FROM positions WHERE name = ?', (name,)).fetchone():
            raise ValueError(f'岗位名称【{name}】已存在')
        process_ids = data.get('process_ids', [])
        if process_ids:
            placeholders = ','.join('?' for _ in process_ids)
            valid = {r[0] for r in db.execute(
                f'SELECT id FROM processes WHERE id IN ({placeholders})', process_ids
            ).fetchall()}
            invalid = [str(pid) for pid in process_ids if pid not in valid]
            if invalid:
                raise ValueError(f'无效工序ID: {", ".join(invalid)}')
        with BaseService.transaction() as txn:
            cur = txn.execute(
                'INSERT INTO positions (name, description) VALUES (?, ?)',
                (name, data.get('description', '')))
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
        if 'name' in data and not data['name'].strip():
            raise ValueError('岗位名称不能为空')
        if 'name' in data and data['name'].strip():
            new_name = data['name'].strip()
            dup = db.execute(
                'SELECT id FROM positions WHERE name = ? AND id != ?',
                (new_name, pos_id)).fetchone()
            if dup:
                raise ValueError(f'岗位名称【{new_name}】已存在')
            data['name'] = new_name
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

        with BaseService.transaction() as txn:
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
        with BaseService.transaction() as txn:
            txn.execute('DELETE FROM positions WHERE id = ?', (pos_id,))
        return pos['name']
