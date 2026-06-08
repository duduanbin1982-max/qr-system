"""qr-system — 工价管理 Service 层"""
from datetime import datetime
from modules.services import BaseService


class ProcessPriceService:
    """工序级别工价管理（按产品+工序）。"""

    @staticmethod
    def list_prices(product_id='', category='', page=1, limit=100):
        """工序单价列表（含产品/工序信息 + 分页）。"""
        db = BaseService.db()
        where = []
        params = []
        if product_id:
            where.append('pp.product_id = ?'); params.append(int(product_id))
        if category:
            where.append('p.category = ?'); params.append(category)
        where_clause = ('WHERE ' + ' AND '.join(where)) if where else ''
        # Safe: where_clause built from hardcoded column names, params parameterized
        count_sql = ('SELECT COUNT(*) FROM process_prices pp'
                     ' LEFT JOIN processes p ON pp.process_id = p.id'
                     ' LEFT JOIN products pr ON pp.product_id = pr.id'
                     f' {where_clause}')
        total = db.execute(count_sql, params).fetchone()[0]
        offset = (page - 1) * limit
        query = ('SELECT pp.*, p.name as process_name, p.seq_order,'
                 ' pr.product_name as product_name, pr.model as product_model,'
                 ' pr.product_code as product_code'
                 ' FROM process_prices pp'
                 ' LEFT JOIN processes p ON pp.process_id = p.id'
                 ' LEFT JOIN products pr ON pp.product_id = pr.id'
                 f' {where_clause}'
                 ' ORDER BY pr.product_name, p.seq_order, pp.effective_date DESC'
                 ' LIMIT ? OFFSET ?')
        rows = db.execute(query, params + [limit, offset]).fetchall()
        return {'process_prices': [dict(r) for r in rows], 'total': total, 'page': page, 'limit': limit}

    @staticmethod
    def create_price(data):
        """创建工序单价。"""
        if not data.get('process_id') or not data.get('unit_price'):
            raise ValueError('缺少必要参数')
        with BaseService.transaction() as txn:
            cur = txn.execute('''
                INSERT INTO process_prices (product_id, process_id, unit_price,
                    effective_date, status, remark)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (data.get('product_id') or None, data['process_id'], data['unit_price'],
                  data.get('effective_date', ''), data.get('status', 'active'),
                  data.get('remark', '')))
            return cur.lastrowid

    @staticmethod
    def update_price(pid, data):
        """更新工序单价。"""
        db = BaseService.db()
        existing = db.execute(
            'SELECT id FROM process_prices WHERE id = ?', (pid,)).fetchone()
        if not existing:
            raise ValueError('工价记录不存在')
        field_map = {'product_id': 'product_id', 'process_id': 'process_id',
                     'unit_price': 'unit_price', 'effective_date': 'effective_date',
                     'status': 'status', 'remark': 'remark'}
        sets = []; params = []
        for field in ['product_id', 'process_id', 'unit_price', 'effective_date', 'status', 'remark']:
            if field in data:
                sets.append(f'{field_map[field]} = ?')
                params.append(data[field] if data[field] is not None else None)
        if not sets:
            raise ValueError('无更新内容')
        sets.append('updated_at = datetime("now","localtime")')
        with BaseService.transaction() as txn:
            txn.execute(f'UPDATE process_prices SET {", ".join(sets)} WHERE id = ?', params + [pid])

    @staticmethod
    def delete_price(pid):
        """删除工序单价。"""
        db = BaseService.db()
        existing = db.execute(
            'SELECT id FROM process_prices WHERE id = ?', (pid,)).fetchone()
        if not existing:
            raise ValueError('工价记录不存在')
        with BaseService.transaction() as txn:
            txn.execute('DELETE FROM process_prices WHERE id = ?', (pid,))

    @staticmethod
    def copy_prices(from_id, to_id, overwrite=True):
        """从源产品复制工价到目标产品。"""
        if from_id == to_id:
            raise ValueError('源/目标不能相同')
        db = BaseService.db()
        for pid in [from_id, to_id]:
            if not db.execute('SELECT id FROM products WHERE id = ?', (pid,)).fetchone():
                raise ValueError(f'产品ID {pid} 不存在')
        with BaseService.transaction() as txn:
            if overwrite:
                txn.execute('DELETE FROM process_prices WHERE product_id = ?', (to_id,))
            copied = 0; skipped = 0
            for row in txn.execute(
                'SELECT process_id, unit_price, effective_date, remark '
                'FROM process_prices WHERE product_id = ? AND status = "active"', (from_id,)
            ).fetchall():
                try:
                    txn.execute('''INSERT INTO process_prices (product_id, process_id, unit_price,
                        effective_date, status, remark) VALUES (?, ?, ?, ?, 'active', ?)''',
                        (to_id, row['process_id'], row['unit_price'],
                         row['effective_date'], row['remark']))
                    copied += 1
                except Exception as e:
                    if 'UNIQUE' in str(e) or 'integrity' in str(e).lower():
                        skipped += 1
                    else:
                        raise
        return copied, skipped

    @staticmethod
    def get_defaults(category=''):
        """获取分类默认工价（product_id IS NULL）。"""
        db = BaseService.db()
        query = '''SELECT pp.*, p.name as process_name, p.category
            FROM process_prices pp JOIN processes p ON pp.process_id = p.id
            WHERE pp.product_id IS NULL'''
        params = []
        if category:
            query += ' AND p.category = ?'; params.append(category)
        query += ' ORDER BY p.category, p.seq_order'
        rows = db.execute(query, params).fetchall()
        return {'defaults': [dict(r) for r in rows]}

    @staticmethod
    def save_defaults(prices):
        """批量保存分类默认工价。{process_id: unit_price}"""
        if not prices:
            raise ValueError('请提供工价数据')
        db = BaseService.db()
        # Validate all inputs first
        for process_id_str, unit_price in list(prices.items()):
            if unit_price is None or str(unit_price).strip() == '':
                continue
            try:
                process_id = int(process_id_str)
                float(unit_price)
            except (ValueError, TypeError):
                raise ValueError(f'工序ID或单价格式无效: {process_id_str}={unit_price}')
            if not db.execute('SELECT id FROM processes WHERE id = ?', (process_id,)).fetchone():
                raise ValueError(f'工序ID {process_id} 不存在')
        with BaseService.transaction() as txn:
            updated = 0; created = 0
            for process_id_str, unit_price in prices.items():
                if unit_price is None or str(unit_price).strip() == '':
                    continue
                process_id = int(process_id_str)
                price_val = float(unit_price)
                if price_val < 0:
                    raise ValueError(f'单价不能为负数: {price_val}')
                existing = txn.execute(
                    'SELECT id FROM process_prices WHERE product_id IS NULL AND process_id = ?',
                    (process_id,)).fetchone()
                if existing:
                    txn.execute('''UPDATE process_prices SET unit_price = ?,
                        updated_at = datetime("now","localtime") WHERE id = ?''',
                        (price_val, existing['id']))
                    updated += 1
                else:
                    txn.execute('''INSERT INTO process_prices (product_id, process_id, unit_price, status)
                        VALUES (NULL, ?, ?, 'active')''', (process_id, price_val))
                    created += 1
        return updated, created

    @staticmethod
    def get_product_route_pricing(product_id):
        """获取产品的工序路线及当前工价。"""
        db = BaseService.db()
        product = db.execute('SELECT * FROM products WHERE id = ?', (product_id,)).fetchone()
        if not product:
            raise ValueError('产品不存在')
        route_id = product['route_id']
        if not route_id:
            route_row = db.execute(
                'SELECT route_id FROM orders WHERE product_code = ? AND route_id IS NOT NULL LIMIT 1',
                (product['product_code'],)).fetchone()
            route_id = route_row['route_id'] if route_row else None

        if route_id:
            steps = db.execute('''
                SELECT ri.id, ri.seq_order, ri.process_id, p.name as process_name, p.category,
                       pp.id as price_id, pp.unit_price, pp.effective_date,
                       pp.status as price_status, pp.remark
                FROM process_route_items ri
                JOIN processes p ON ri.process_id = p.id
                LEFT JOIN process_prices pp ON pp.process_id = ri.process_id
                    AND pp.product_id = ? AND pp.status = 'active'
                WHERE ri.route_id = ? ORDER BY ri.seq_order
            ''', (product_id, route_id)).fetchall()
        else:
            steps = db.execute('''
                SELECT NULL as id, p.seq_order, p.id as process_id,
                       p.name as process_name, p.category,
                       pp.id as price_id, pp.unit_price, pp.effective_date,
                       pp.status as price_status, pp.remark
                FROM processes p
                LEFT JOIN process_prices pp ON pp.process_id = p.id
                    AND pp.product_id = ? AND pp.status = 'active'
                WHERE p.category = ? AND p.status = 'active'
                ORDER BY p.seq_order
            ''', (product_id, product['category'] or '结构件')).fetchall()

        route_name = None
        if route_id:
            r = db.execute('SELECT name FROM process_routes WHERE id = ?', (route_id,)).fetchone()
            route_name = r['name'] if r else None

        return {
            'product': dict(product),
            'route_id': route_id,
            'route_name': route_name,
            'steps': [dict(s) for s in steps],
            'all_routes': [dict(r) for r in db.execute(
                'SELECT id, name FROM process_routes WHERE status="active"').fetchall()]
        }

    @staticmethod
    def save_product_route_pricing(product_id, prices, effective_date='', remark='', route_id=None):
        """批量保存产品工序路线工价。prices: {process_id: unit_price}"""
        db = BaseService.db()
        product = db.execute('SELECT id FROM products WHERE id = ?', (product_id,)).fetchone()
        if not product:
            raise ValueError('产品不存在')
        # Validate inputs first
        for process_id_str, unit_price in list(prices.items()):
            if unit_price is None or str(unit_price).strip() == '':
                continue
            try:
                process_id = int(process_id_str)
                price_val = float(unit_price)
            except (ValueError, TypeError):
                raise ValueError(f'工序ID或单价格式无效: {process_id_str}={unit_price}')
            if price_val < 0:
                raise ValueError(f'单价不能为负数: {price_val}')
            if not db.execute('SELECT id FROM processes WHERE id = ?', (process_id,)).fetchone():
                raise ValueError(f'工序ID {process_id} 不存在')
        with BaseService.transaction() as txn:
            if route_id is not None:
                txn.execute(
                    'UPDATE products SET route_id = ?, updated_at = datetime("now","localtime") WHERE id = ?',
                    (route_id or None, product_id))
            updated = 0; created = 0
            for process_id_str, unit_price in prices.items():
                if unit_price is None or str(unit_price).strip() == '':
                    continue
                process_id = int(process_id_str)
                price_val = float(unit_price)
                existing = txn.execute(
                    'SELECT id FROM process_prices WHERE product_id = ? AND process_id = ?',
                    (product_id, process_id)).fetchone()
                if existing:
                    txn.execute('''UPDATE process_prices SET unit_price = ?, effective_date = ?, remark = ?,
                        status = 'active', updated_at = datetime("now","localtime") WHERE id = ?''',
                        (price_val, effective_date, remark, existing['id']))
                    updated += 1
                else:
                    try:
                        txn.execute('''INSERT INTO process_prices (product_id, process_id, unit_price,
                            effective_date, status, remark) VALUES (?, ?, ?, ?, 'active', ?)''',
                            (product_id, process_id, price_val, effective_date, remark))
                        created += 1
                    except Exception as e:
                        if 'UNIQUE' in str(e):
                            raise ValueError(f'工序 {process_id} 的工价已存在，刷新后重试')
                        raise
        return updated, created


class RoutePriceService:
    """路线级工价管理。"""

    @staticmethod
    def list_all(category=''):
        """所有路线的工价一览。"""
        db = BaseService.db()
        cat_clause = ''; cat_params = []
        if category:
            cat_clause = 'AND p.category = ?'; cat_params.append(category)
        routes = {}
        for pri_row in db.execute(f'''
            SELECT pri.route_id, pri.seq_order, pri.process_id,
                   p.name as process_name, p.category,
                   pr.name as route_name, pr.status as route_status
            FROM process_route_items pri
            JOIN processes p ON pri.process_id = p.id
            JOIN process_routes pr ON pri.route_id = pr.id
            WHERE pr.status = 'active' {cat_clause}
            ORDER BY pri.route_id, pri.seq_order
        ''', cat_params).fetchall():
            rid = pri_row['route_id']
            if rid not in routes:
                routes[rid] = {'route_id': rid, 'route_name': pri_row['route_name'], 'processes': []}
            routes[rid]['processes'].append({
                'process_id': pri_row['process_id'],
                'process_name': pri_row['process_name'],
                'seq_order': pri_row['seq_order'],
                'category': pri_row['category'],
                'unit_price': None, 'price_id': None, 'effective_date': '', 'remark': ''
            })

        price_rows = db.execute('''
            SELECT rp.*, p.category FROM route_prices rp
            JOIN processes p ON rp.process_id = p.id WHERE rp.status = 'active'
        ''').fetchall()
        for pr in price_rows:
            rid = pr['route_id']; pid = pr['process_id']
            if rid in routes:
                for proc in routes[rid]['processes']:
                    if proc['process_id'] == pid:
                        proc['unit_price'] = pr['unit_price']
                        proc['price_id'] = pr['id']
                        proc['effective_date'] = pr['effective_date'] or ''
                        proc['remark'] = pr['remark'] or ''
                        break
        return {'routes': list(routes.values())}

    @staticmethod
    def get_by_route(route_id):
        """获取某路线的工序工价（含未定价工序）。"""
        db = BaseService.db()
        route = db.execute('SELECT * FROM process_routes WHERE id = ?', (route_id,)).fetchone()
        if not route:
            raise ValueError('路线不存在')
        steps = db.execute('''
            SELECT pri.seq_order, pri.process_id, p.name as process_name, p.category,
                   rp.id as price_id, rp.unit_price, rp.effective_date, rp.remark
            FROM process_route_items pri
            JOIN processes p ON pri.process_id = p.id
            LEFT JOIN route_prices rp ON rp.route_id = pri.route_id
                AND rp.process_id = pri.process_id AND rp.status = 'active'
            WHERE pri.route_id = ? ORDER BY pri.seq_order
        ''', (route_id,)).fetchall()
        return {'route': dict(route), 'steps': [dict(s) for s in steps]}

    @staticmethod
    def save_prices(route_id, prices, effective_date=None, remark=None):
        """批量保存路线工序工价。prices: {process_id: unit_price}"""
        db = BaseService.db()
        route = db.execute('SELECT * FROM process_routes WHERE id = ?', (route_id,)).fetchone()
        if not route:
            raise ValueError('路线不存在')
        if not isinstance(prices, dict):
            raise ValueError('prices必须为对象格式')
        valid_pids = set(r['process_id'] for r in db.execute(
            'SELECT process_id FROM process_route_items WHERE route_id = ?', (route_id,)).fetchall())
        # Validate all inputs before entering transaction
        for process_id_str, unit_price in list(prices.items()):
            if unit_price is None or str(unit_price).strip() == '':
                continue
            try:
                process_id = int(process_id_str)
                price_val = float(unit_price)
            except (ValueError, TypeError):
                raise ValueError(f'工序ID或单价格式无效: {process_id_str}={unit_price}')
            if price_val < 0:
                raise ValueError(f'单价不能为负数: {price_val}')
            if process_id not in valid_pids:
                raise ValueError(f'工序 {process_id} 不属于路线 {route_id}')
        with BaseService.transaction() as txn:
            updated = 0; created = 0
            for process_id_str, unit_price in prices.items():
                if unit_price is None or str(unit_price).strip() == '':
                    continue
                process_id = int(process_id_str)
                price_val = float(unit_price)
                existing = txn.execute(
                    'SELECT id FROM route_prices WHERE route_id = ? AND process_id = ?',
                    (route_id, process_id)).fetchone()
                if existing:
                    e_date = effective_date if effective_date is not None else existing['effective_date']
                    e_remark = remark if remark is not None else (existing['remark'] or '')
                    txn.execute('''UPDATE route_prices SET unit_price = ?, effective_date = ?, remark = ?,
                        updated_at = datetime("now","localtime") WHERE id = ?''',
                        (price_val, e_date, e_remark, existing['id']))
                    updated += 1
                else:
                    txn.execute('''INSERT INTO route_prices (route_id, process_id, unit_price,
                        effective_date, remark, status) VALUES (?, ?, ?, ?, ?, 'active')''',
                        (route_id, process_id, price_val, effective_date or '', remark or ''))
                    created += 1
        return updated, created


class WageService:
    """计件工资 + 日报 + 生产进度。"""

    @staticmethod
    def calculate_wages(employee_id='', date_from='', date_to='', page=1, limit=200):
        """计件工资统计（仅统计已审批通过的正常报工）。"""
        db = BaseService.db()
        where = "wr.status = 'approved' AND wr.type = 'normal'"
        params = []
        if employee_id:
            where += ' AND wr.user_id = ?'; params.append(employee_id)
        if date_from:
            where += ' AND wr.created_at >= ?'; params.append(date_from)
        if date_to:
            where += ' AND wr.created_at < ?'; params.append(date_to + ' 23:59:59')
        # Count before pagination
        count_sql = ("SELECT COUNT(*) FROM work_records wr"
                     " LEFT JOIN orders o ON wr.order_id = o.id AND o.deleted_at IS NULL"
                     " WHERE " + where)
        total = db.execute(count_sql, params).fetchone()[0]
        offset = (page - 1) * limit
        # process_prices subquery: deduplicate by (product_code, process_id) using latest effective_date
        query = ('''SELECT wr.*, u.name as employee_name, u.employee_no,
                   p.name as process_name,
                   o.order_no, o.product_name, o.product_code as order_product_code,
                   COALESCE(rp.unit_price, pp_dedup.unit_price, 0) as unit_price
            FROM work_records wr
            LEFT JOIN users u ON wr.user_id = u.id
            LEFT JOIN processes p ON wr.process_id = p.id
            LEFT JOIN orders o ON wr.order_id = o.id AND o.deleted_at IS NULL
            LEFT JOIN route_prices rp ON o.route_id = rp.route_id
                AND wr.process_id = rp.process_id AND rp.status = 'active'
            LEFT JOIN (
                SELECT pr.product_code, pp2.process_id, pp2.unit_price
                FROM process_prices pp2
                JOIN products pr ON pp2.product_id = pr.id AND pr.deleted_at IS NULL
                WHERE pp2.status = 'active'
                AND pp2.effective_date = (
                    SELECT MAX(pp3.effective_date) FROM process_prices pp3
                    JOIN products pr3 ON pp3.product_id = pr3.id
                    WHERE pr3.product_code = pr.product_code
                    AND pp3.process_id = pp2.process_id
                    AND pp3.status = 'active' AND pr3.deleted_at IS NULL
                )
                GROUP BY pr.product_code, pp2.process_id
            ) pp_dedup ON o.product_code = pp_dedup.product_code
                AND wr.process_id = pp_dedup.process_id
            WHERE ''' + where + ''' ORDER BY wr.created_at DESC LIMIT ? OFFSET ?''')
        rows = db.execute(query, params + [limit, offset]).fetchall()
        wages = {}
        for row in rows:
            emp_id = row['user_id']
            emp_name = row['employee_name'] or '未知'
            emp_no = row['employee_no'] or ''
            if emp_id not in wages:
                wages[emp_id] = {'employee_name': emp_name, 'employee_no': emp_no,
                                 'total_quantity': 0, 'total_wage': 0, 'details': []}
            qty = row['quantity'] or 0
            up = row['unit_price'] or 0
            wage = qty * up
            wages[emp_id]['total_quantity'] += qty
            wages[emp_id]['total_wage'] += wage
            wages[emp_id]['details'].append({
                'date': row['created_at'],
                'order_no': row['order_no'] or '',
                'product_name': row['product_name'] or '',
                'product_code': row['order_product_code'] or '',
                'process_name': row['process_name'],
                'quantity': qty, 'unit_price': up, 'wage': wage
            })
        return {'wages': list(wages.values()), 'total': total, 'page': page, 'limit': limit}

    @staticmethod
    def daily_report(date):
        """员工生产日报表（仅统计已审批通过的正常报工）。"""
        db = BaseService.db()
        rows = db.execute('''
            SELECT wr.*, u.name as employee_name, u.employee_no, p.name as process_name
            FROM work_records wr
            LEFT JOIN users u ON wr.user_id = u.id
            LEFT JOIN processes p ON wr.process_id = p.id
            WHERE wr.status = 'approved' AND wr.type = 'normal'
            AND wr.created_at >= ? AND wr.created_at < ?
            ORDER BY wr.user_id, wr.process_id
        ''', (date, date + ' 23:59:59')).fetchall()
        report = {}
        for row in rows:
            emp_id = row['user_id']; proc_id = row['process_id']
            emp_name = row['employee_name'] or '未知'
            proc_name = row['process_name'] or '未知'
            if emp_id not in report:
                report[emp_id] = {'employee_name': emp_name, 'employee_no': row['employee_no'],
                                  'processes': {}}
            if proc_id not in report[emp_id]['processes']:
                report[emp_id]['processes'][proc_id] = {'process_name': proc_name, 'quantity': 0}
            report[emp_id]['processes'][proc_id]['quantity'] += row['quantity'] or 0
        return {'date': date, 'report': list(report.values())}

    @staticmethod
    def production_progress():
        """生产进度看板。"""
        db = BaseService.db()
        rows = db.execute('''
            SELECT o.*, COALESCE(o.completed, 0) as done_qty,
                   COALESCE(o.scrapped, 0) as scrap_qty
            FROM orders o
            WHERE o.deleted_at IS NULL
              AND o.status IN ('processing', 'pending', 'in_progress')
            ORDER BY o.plan_end, o.created_at DESC
        ''').fetchall()
        # 批量预取工序，避免 N+1
        order_ids = [r['id'] for r in rows]
        proc_by_order = {}
        if order_ids:
            # placeholders are all '?' chars from trusted integer list — safe for f-string
            placeholders = ",".join("?" for _ in order_ids)
            proc_rows = db.execute(f'''
                SELECT op.order_id, op.process_id, p.name as process_name, op.completed,
                       op.scrapped, op.required_audit
                FROM order_processes op
                LEFT JOIN processes p ON op.process_id = p.id
                WHERE op.order_id IN ({placeholders}) ORDER BY op.seq_order
            ''', order_ids).fetchall()
            for pr in proc_rows:
                proc_by_order.setdefault(pr['order_id'], []).append(pr)

        result = []
        for row in rows:
            o = dict(row)
            total = o['quantity'] or 1
            done = o.get('done_qty', 0); scrap = o.get('scrap_qty', 0)
            progress_pct = min(100, int((done + scrap) / total * 100))
            o['progress'] = progress_pct
            o['remaining'] = total - done - scrap
            proc_rows = proc_by_order.get(row['id'], [])
            processes = []
            for pr in proc_rows:
                pd = pr['completed'] or 0; ps = pr['scrapped'] or 0
                pp = min(100, int((pd + ps) / total * 100))
                processes.append({
                    'process_id': pr['process_id'], 'process_name': pr['process_name'],
                    'completed': pd, 'scrapped': ps, 'progress': pp,
                    'required_audit': pr['required_audit']
                })
            o['processes'] = processes
            result.append(o)
        return {'orders': result}
