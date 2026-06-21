"""qr-system — 工价管理 Service 层 (Repository pattern)"""
from datetime import datetime
from modules.services import BaseService
from modules.repositories.price_repository import PriceRepository
from modules.services.query_utils import paginate, build_sort_clause


class RoutePriceService:
    """路线级工价管理。"""

    @staticmethod
    def list_all(category=''):
        """所有路线的工价一览。"""
        route_rows = PriceRepository.find_route_items(category=category)
        routes = {}
        for pri_row in route_rows:
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

        price_rows = PriceRepository.find_active_route_prices()
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
        route = PriceRepository.find_process_route_by_id(route_id)
        if not route:
            raise ValueError('路线不存在')
        steps = PriceRepository.find_route_steps(route_id)
        return {'route': dict(route), 'steps': [dict(s) for s in steps]}

    @staticmethod
    def save_prices(route_id, prices, effective_date=None, remark=None):
        """批量保存路线工序工价。prices: {process_id: unit_price}"""
        route = PriceRepository.find_process_route_by_id(route_id)
        if not route:
            raise ValueError('路线不存在')
        if not isinstance(prices, dict):
            raise ValueError('prices必须为对象格式')
        valid_pids = PriceRepository.find_valid_route_processes(route_id)
        validated = []
        for process_id_str, unit_price in list(prices.items()):
            if unit_price is None or str(unit_price).strip() == '':
                continue
            try:
                process_id = int(process_id_str)
                price_val = float(unit_price)
            except (ValueError, TypeError):
                raise ValueError('工序ID或单价格式无效: ' + str(process_id_str) + '=' + str(unit_price))
            if price_val < 0:
                raise ValueError('单价不能为负数: ' + str(price_val))
            if process_id not in valid_pids:
                raise ValueError('工序 ' + str(process_id) + ' 不属于路线 ' + str(route_id))
            validated.append((process_id, price_val))
        with BaseService.transaction() as txn:
            updated = 0
            created = 0
            for process_id, price_val in validated:
                existing = PriceRepository.find_route_price(route_id, process_id, db=txn)
                if existing:
                    old_price = existing['unit_price'] if 'unit_price' in existing.keys() else None
                    e_date = effective_date if effective_date is not None else (existing.get('effective_date') or '')
                    e_remark = remark if remark is not None else (existing.get('remark') or '')
                    if old_price is not None and abs(old_price - price_val) > 0.001:
                        PriceRepository.insert_route_price_history(
                            route_id, process_id, old_price, price_val, e_date, e_remark, db=txn)
                    PriceRepository.update_route_price(existing['id'], price_val, e_date, e_remark, db=txn)
                    updated += 1
                else:
                    PriceRepository.insert_route_price(
                        route_id, process_id, price_val, effective_date or '', remark or '', db=txn)
                    created += 1
        return updated, created

    @staticmethod
    def get_route_price_history(route_id):
        """获取某路线的工价变更历史"""
        rows = PriceRepository.get_route_price_history(route_id)
        return {"history": [dict(r) for r in rows]}

    @staticmethod
    def active_price_join():
        """统一的 route_prices 生效条件 JOIN 子句"""
        return ("LEFT JOIN route_prices rp ON o.route_id = rp.route_id "
                "AND wr.process_id = rp.process_id AND rp.status = 'active' "
                "AND rp.effective_date <= date('now','localtime')")
