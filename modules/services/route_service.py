"""
qr-system — 工序路线管理 Service 层

从 routes/process_routes.py 提取全部业务逻辑。
"""
from modules.services import BaseService


class ProcessRouteService:
    """工序路线管理业务逻辑。"""

    @staticmethod
    def list_routes(category='', search='', limit=None, offset=0):
        """获取所有工序路线（含工序明细，批量预取避免 N+1）。
        支持分类筛选、名称搜索、分页。"""
        db = BaseService.db()
        sql = 'SELECT * FROM process_routes'
        params = []
        conditions = []
        if category:
            conditions.append('category = ?')
            params.append(category)
        if search:
            conditions.append('name LIKE ?')
            params.append(f'%{search}%')
        if conditions:
            sql += ' WHERE ' + ' AND '.join(conditions)
        sql += ' ORDER BY created_at DESC'

        if limit:
            limit = max(1, min(int(limit), 200))
            # Count total
            count_sql = sql.replace('SELECT *', 'SELECT COUNT(*)', 1)
            total = db.execute(count_sql, params).fetchone()[0]
            sql += ' LIMIT ? OFFSET ?'
            params.extend([limit, offset])
            rows = db.execute(sql, params).fetchall()
        else:
            rows = db.execute(sql, params).fetchall()
            total = None

        items_by_route = {}
        if rows:
            route_ids = [r['id'] for r in rows]
            placeholders = ",".join("?" for _ in route_ids)
            # Safe: placeholders are literal "?" strings, route_ids are integers from DB
            query = ('SELECT pri.*, p.name as process_name, p.category as category '
                     'FROM process_route_items pri '
                     'LEFT JOIN processes p ON pri.process_id = p.id '
                     'WHERE pri.route_id IN ({}) '
                     'ORDER BY pri.route_id, pri.seq_order').format(placeholders)
            items = db.execute(query, route_ids).fetchall()
            for item in items:
                items_by_route.setdefault(item['route_id'], []).append(dict(item))

        result = []
        for r in rows:
            route = dict(r)
            route['processes'] = items_by_route.get(r['id'], [])
            result.append(route)
        ret = {'routes': result}
        if total is not None:
            ret['total'] = total
        return ret

    @staticmethod
    def create_route(data):
        """创建工序路线。Raises ValueError on empty name, missing processes, etc."""
        name = (data.get('name') or '').strip()
        if not name:
            raise ValueError('路线名称不能为空')

        processes = data.get('processes', [])
        if not processes:
            raise ValueError('工序列表不能为空')

        db = BaseService.db()
        existing = db.execute(
            'SELECT id FROM process_routes WHERE name = ?', (name,)
        ).fetchone()
        if existing:
            raise ValueError(f'路线名称【{name}】已存在')

        with BaseService.transaction() as txn:
            cur = txn.execute(
                'INSERT INTO process_routes (name, description, category) VALUES (?, ?, ?)',
                (name, data.get('description', ''), data.get('category', '结构件'))
            )
            route_id = cur.lastrowid
            # 批量预取工序验证（避免 N+1）
            pids = [p.get('process_id') for p in processes if p.get('process_id')]
            if pids:
                placeholders = ",".join("?" for _ in pids)
                existing_ids = set(r['id'] for r in txn.execute(
                    f'SELECT id FROM processes WHERE id IN ({placeholders})', pids
                ).fetchall())
                for pid in pids:
                    if pid not in existing_ids:
                        raise ValueError(f'工序 ID {pid} 不存在')
            for idx, p in enumerate(processes):
                pid = p.get('process_id')
                if not pid:
                    continue
                txn.execute(
                    'INSERT INTO process_route_items '
                    '(route_id, process_id, seq_order, required_audit) '
                    'VALUES (?, ?, ?, ?)',
                    (route_id, pid, idx, p.get('required_audit', 0))
                )
            return route_id

    @staticmethod
    def update_route(rid, data):
        """更新工序路线（替换工序明细）。"""
        db = BaseService.db()
        route = db.execute(
            'SELECT * FROM process_routes WHERE id = ?', (rid,)
        ).fetchone()
        if not route:
            raise ValueError('路线不存在')

        new_name = data.get('name', route['name']).strip()
        if new_name != route['name']:
            dup = db.execute(
                'SELECT id FROM process_routes WHERE name = ? AND id != ?',
                (new_name, rid)
            ).fetchone()
            if dup:
                raise ValueError(f'路线名称【{new_name}】已存在')

        processes = data.get('processes', [])
        if not processes:
            raise ValueError('工序列表不能为空')

        with BaseService.transaction() as txn:
            category = data.get('category', route['category'] if route['category'] else '结构件')
            txn.execute(
                'UPDATE process_routes SET name = ?, description = ?, category = ?, '
                'updated_at = datetime("now","localtime") WHERE id = ?',
                (new_name, data.get('description', route['description']), category, rid)
            )
            txn.execute('DELETE FROM process_route_items WHERE route_id = ?', (rid,))
            # 批量预取工序验证（避免 N+1）
            pids = [p.get('process_id') for p in processes if p.get('process_id')]
            if pids:
                placeholders = ",".join("?" for _ in pids)
                existing_ids = set(r['id'] for r in txn.execute(
                    f'SELECT id FROM processes WHERE id IN ({placeholders})', pids
                ).fetchall())
                for pid in pids:
                    if pid not in existing_ids:
                        raise ValueError(f'工序 ID {pid} 不存在')
            for idx, p in enumerate(processes):
                pid = p.get('process_id')
                if not pid:
                    continue
                txn.execute(
                    'INSERT INTO process_route_items '
                    '(route_id, process_id, seq_order, required_audit) '
                    'VALUES (?, ?, ?, ?)',
                    (rid, pid, idx, p.get('required_audit', 0))
                )

    @staticmethod
    def delete_route(rid):
        """删除工序路线（仅当无活跃订单引用时才允许）。"""
        db = BaseService.db()
        route = db.execute(
            'SELECT * FROM process_routes WHERE id = ?', (rid,)
        ).fetchone()
        if not route:
            raise ValueError('路线不存在')
        used = db.execute(
            'SELECT COUNT(*) as cnt FROM orders WHERE deleted_at IS NULL AND route_id = ?',
            (rid,)
        ).fetchone()
        if used['cnt'] > 0:
            raise ValueError(f'该路线已被 {used["cnt"]} 个订单使用，无法删除')
        with BaseService.transaction() as txn:
            txn.execute('DELETE FROM process_route_items WHERE route_id = ?', (rid,))
            txn.execute('DELETE FROM process_routes WHERE id = ?', (rid,))
        return route['name']

    @staticmethod
    def apply_route(rid, order_id):
        """将工序路线应用到订单（拷贝 route_items 到 order_processes）。"""
        db = BaseService.db()
        route = db.execute(
            'SELECT * FROM process_routes WHERE id = ?', (rid,)
        ).fetchone()
        if not route:
            raise ValueError('路线不存在')
        order = db.execute(
            'SELECT * FROM orders WHERE id = ?', (order_id,)
        ).fetchone()
        if not order:
            raise ValueError('订单不存在')

        with BaseService.transaction() as txn:
            existing_work = txn.execute(
                'SELECT COUNT(*) as cnt FROM work_records WHERE order_id = ?',
                (order_id,)
            ).fetchone()
            if existing_work['cnt'] > 0:
                raise ValueError(
                    f'该订单已有 {existing_work["cnt"]} 条报工记录，无法重新应用路线'
                )

            txn.execute(
                'UPDATE orders SET route_id = ? WHERE id = ?', (rid, order_id)
            )
            txn.execute('DELETE FROM order_processes WHERE order_id = ?', (order_id,))
            items = txn.execute(
                'SELECT * FROM process_route_items WHERE route_id = ? ORDER BY seq_order',
                (rid,)
            ).fetchall()
            for item in items:
                txn.execute(
                    'INSERT INTO order_processes '
                    '(order_id, process_id, seq_order, required_audit) '
                    'VALUES (?, ?, ?, ?)',
                    (order_id, item['process_id'], item['seq_order'],
                     item['required_audit'])
                )
            return len(items)
