"""qr-system — 工价管理 Service 层"""
from datetime import datetime
from modules.services import BaseService
from modules.services.query_utils import paginate, build_sort_clause

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
        # Hash Map: O(n) lookup
        price_map = {}
        for pr in price_rows:
            price_map[(pr['route_id'], pr['process_id'])] = pr
        for rid in routes:
            for proc in routes[rid]['processes']:
                key = (rid, proc['process_id'])
                if key in price_map:
                    pr = price_map[key]
                    proc['unit_price'] = pr['unit_price']
                    proc['price_id'] = pr['id']
                    proc['effective_date'] = pr['effective_date'] or ''
                    proc['remark'] = pr['remark'] or ''
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
        # Single-pass: validate + collect validated pairs
        validated = []
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
            validated.append((process_id, price_val))
        with BaseService.transaction() as txn:
            updated = 0; created = 0
            for process_id, price_val in validated:
                existing = txn.execute(
                    'SELECT id, unit_price, effective_date, remark FROM route_prices WHERE route_id = ? AND process_id = ?',
                    (route_id, process_id)).fetchone()
                if existing:
                    old_price = existing['unit_price'] if 'unit_price' in existing.keys() else None
                    e_date = effective_date if effective_date is not None else (existing.get('effective_date') or '')
                    e_remark = remark if remark is not None else (existing.get('remark') or '')
                    # Record price history (only if price actually changed)
                    if old_price is not None and abs(old_price - price_val) > 0.001:
                        txn.execute(
                            'INSERT INTO route_price_history (route_id, process_id, old_price, new_price, effective_date, remark) VALUES (?,?,?,?,?,?)',
                            (route_id, process_id, old_price, price_val, e_date, e_remark))
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

    @staticmethod
    def get_route_price_history(route_id):
        """获取某路线的工价变更历史"""
        db = BaseService.db()
        rows = db.execute("""
            SELECT h.*, p.name as process_name
            FROM route_price_history h
            LEFT JOIN processes p ON h.process_id = p.id
            WHERE h.route_id = ?
            ORDER BY h.created_at DESC
            LIMIT 50
        """, (route_id,)).fetchall()
        return {"history": [dict(r) for r in rows]}

    @staticmethod
    def active_price_join():
        """统一的 route_prices 生效条件 JOIN 子句"""
        return ("LEFT JOIN route_prices rp ON o.route_id = rp.route_id "
                "AND wr.process_id = rp.process_id AND rp.status = 'active' "
                "AND rp.effective_date <= date('now','localtime')")
