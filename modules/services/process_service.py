"""
qr-system — 工序管理 Service 层

从 routes/processes.py 提取全部业务逻辑。
"""
import re
import sqlite3
from modules.services import BaseService


class ProcessService:
    """工序管理业务逻辑。"""

    @staticmethod
    def list_processes(category='', search='', sort_by='seq_order', sort_dir='asc', limit=None, offset=0):
        """工序列表（支持分类筛选、搜索、排序、分页）。"""
        db = BaseService.db()
        # 白名单校验排序字段
        allowed_sort = {'seq_order', 'name', 'category', 'status', 'created_at'}
        if sort_by not in allowed_sort:
            sort_by = 'seq_order'
        if sort_dir.lower() not in ('asc', 'desc'):
            raise ValueError('sort_dir must be asc or desc')
        sort_dir = sort_dir.upper()
        limit = max(1, min(int(limit), 200)) if limit else None
        sql = ('SELECT id, name AS process_name, description, category, '
               'seq_order, status, created_at FROM processes')
        params = []
        conditions = []
        if category:
            conditions.append('category = ?')
            params.append(category)
        if search:
            conditions.append('name LIKE ? ESCAPE "\\"')
            safe_search = search.replace('%', '\\%').replace('_', '\\_')
            params.append(f'%{safe_search}%')
        if conditions:
            sql += ' WHERE ' + ' AND '.join(conditions)
        sql += f' ORDER BY {sort_by} {sort_dir}, id {sort_dir}'
        category_counts = {}
        for r in db.execute("SELECT category, COUNT(*) as cnt FROM processes GROUP BY category").fetchall():
            category_counts[r['category']] = r['cnt']

        if limit:
            # 分页：先查总数
            count_sql = 'SELECT COUNT(*) FROM processes'
            if conditions:
                count_sql += ' WHERE ' + ' AND '.join(conditions)
            total = db.execute(count_sql, params).fetchone()[0]
            sql += ' LIMIT ? OFFSET ?'
            params.extend([limit, offset])
            rows = db.execute(sql, params).fetchall()
            return {'processes': [dict(r) for r in rows], 'total': total, 'category_counts': category_counts}
        rows = db.execute(sql, params).fetchall()
        return {'processes': [dict(r) for r in rows], 'total': len(rows), 'category_counts': category_counts}

    @staticmethod
    def create_process(data):
        """
        创建工序。Raises ValueError on empty name or duplicate.
        """
        name = data.get('name', '').strip()
        if not name:
            raise ValueError('工序名称不能为空')
        if re.search(r"[';<>]", name):
            raise ValueError('工序名称不能包含特殊字符')

        db = BaseService.db()
        seq_order = data.get('seq_order')
        if seq_order is not None:
            try:
                seq_order = int(seq_order)
            except (ValueError, TypeError):
                seq_order = None
        # Pre-check duplicate name (friendly error, before transaction)
        existing = db.execute('SELECT id FROM processes WHERE name = ?', (name,)).fetchone()
        if existing:
            raise ValueError(f'工序【{name}】已存在，不能重复添加')
        try:
            with BaseService.transaction() as txn:
                if seq_order is None:
                    category = data.get('category', '结构件')
                    max_seq = txn.execute(
                        'SELECT COALESCE(MAX(seq_order),0) FROM processes WHERE category = ?',
                        (category,)
                    ).fetchone()[0]
                    seq_order = max_seq + 1
                cur = txn.execute(
                    'INSERT INTO processes (name, description, category, seq_order, status) '
                    'VALUES (?,?,?,?,?)',
                    (name, data.get('description', ''),
                     data.get('category', '结构件'), seq_order,
                     data.get('status', 'active'))
                )
                return cur.lastrowid
        except sqlite3.IntegrityError:
            raise ValueError(f'工序【{name}】已存在，不能重复添加')

    @staticmethod
    def update_process(pid, data):
        """更新工序。Raises ValueError on not found or empty name."""
        db = BaseService.db()
        existing = db.execute(
            'SELECT id, name FROM processes WHERE id = ?', (pid,)
        ).fetchone()
        if not existing:
            raise ValueError('工序不存在')

        if 'name' in data:
            name = (data.get('name') or '').strip()
            if not name:
                raise ValueError('工序名称不能为空')
            if re.search(r"[';<>]", name):
                raise ValueError('工序名称不能包含特殊字符')
            data['name'] = name

        field_map = {
            'name': 'name', 'description': 'description',
            'category': 'category', 'seq_order': 'seq_order', 'status': 'status'
        }
        sets = []
        params = []
        for field in ['name', 'description', 'category', 'seq_order', 'status']:
            if field in data:
                sets.append(f'{field_map[field]} = ?')
                params.append(data[field])
        if not sets:
            raise ValueError('无更新内容')

        # Pre-check duplicate name if name is being changed
        if 'name' in data:
            dup = db.execute('SELECT id FROM processes WHERE name = ? AND id != ?', (data['name'], pid)).fetchone()
            if dup:
                raise ValueError(f'工序名称【{data["name"]}】已存在，不能重复')

        # Always set updated_at
        sets.append('updated_at = datetime("now","localtime")')

        with BaseService.transaction() as txn:
            try:
                txn.execute(
                    f'UPDATE processes SET {", ".join(sets)} WHERE id = ?',
                    params + [pid]
                )
            except sqlite3.IntegrityError:
                raise ValueError(f'工序名称已存在，不能重复')

    @staticmethod
    def delete_process(pid):
        """Delete process with impact audit and full cascade cleanup."""
        db = BaseService.db()
        existing = db.execute(
            'SELECT id, name FROM processes WHERE id = ?', (pid,)
        ).fetchone()
        if not existing:
            raise ValueError('不存在')

        related_tables = ['work_records','scrap_records','rework_records',
                          'quality_inspections','process_prices','process_route_items',
                          'order_processes','position_processes','material_consumptions']
        union_parts = []
        for tbl in related_tables:
            union_parts.append(f"SELECT '{tbl}' as tbl, COUNT(*) as cnt FROM {tbl} WHERE process_id = ?")
        union_sql = ' UNION ALL '.join(union_parts)
        rows = db.execute(union_sql, [pid] * len(related_tables)).fetchall()
        impact = {r['tbl']: r['cnt'] for r in rows if r['cnt'] > 0}

        with BaseService.transaction() as txn:
            for tbl in related_tables:
                txn.execute(f'DELETE FROM {tbl} WHERE process_id = ?', (pid,))
            txn.execute('DELETE FROM processes WHERE id = ?', (pid,))

        return {'name': existing['name'], 'impact': impact}
