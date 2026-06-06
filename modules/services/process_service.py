"""
qr-system — 工序管理 Service 层

从 routes/processes.py 提取全部业务逻辑。
"""
import sqlite3
from modules.services import BaseService


class ProcessService:
    """工序管理业务逻辑。"""

    @staticmethod
    def list_processes(category=''):
        """工序列表（支持分类筛选）。"""
        db = BaseService.db()
        sql = ('SELECT id, name AS process_name, description, category, '
               'seq_order AS seq, status, created_at FROM processes')
        params = []
        if category:
            sql += ' WHERE category = ?'
            params.append(category)
        sql += ' ORDER BY seq_order, id'
        rows = db.execute(sql, params).fetchall()
        return {'processes': [dict(r) for r in rows]}

    @staticmethod
    def create_process(data):
        """
        创建工序。Raises ValueError on empty name or duplicate.
        """
        name = data.get('name', '').strip()
        if not name:
            raise ValueError('工序名称不能为空')

        db = BaseService.db()
        seq_order = data.get('seq_order')
        if seq_order is not None:
            try:
                seq_order = int(seq_order)
            except (ValueError, TypeError):
                seq_order = None
        if seq_order is None:
            max_seq = db.execute(
                'SELECT COALESCE(MAX(seq_order),0) FROM processes'
            ).fetchone()[0]
            seq_order = max_seq + 1

        try:
            with BaseService.transaction() as txn:
                cur = txn.execute(
                    'INSERT INTO processes (name, description, category, seq_order) '
                    'VALUES (?,?,?,?)',
                    (name, data.get('description', ''),
                     data.get('category', '结构件'), seq_order)
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
            data['name'] = name

        sets = []
        params = []
        for field in ['name', 'description', 'category', 'seq_order', 'status']:
            if field in data:
                sets.append(f'{field} = ?')
                params.append(data[field])
        if not sets:
            raise ValueError('无更新内容')

        with BaseService.transaction() as txn:
            txn.execute(
                f'UPDATE processes SET {", ".join(sets)} WHERE id = ?',
                params + [pid]
            )

    @staticmethod
    def delete_process(pid):
        """
        删除工序（级联清理关联数据）。

        注意：material_consumptions 的 FK 无 ON DELETE CASCADE，
        需显式清理。其余子表（order_processes/work_records/scrap/
        quality/rework/prices/route_items/positions）有 CASCADE 自动处理。

        Raises ValueError on not found or already used in production.
        """
        db = BaseService.db()
        existing = db.execute(
            'SELECT id, name FROM processes WHERE id = ?', (pid,)
        ).fetchone()
        if not existing:
            raise ValueError('工序不存在')

        with BaseService.transaction() as txn:
            # 清理无 CASCADE 的物料消耗引用
            txn.execute('DELETE FROM material_consumptions WHERE process_id = ?', (pid,))
            txn.execute('DELETE FROM processes WHERE id = ?', (pid,))
