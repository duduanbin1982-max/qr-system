from modules.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_LIMIT
"""
qr-system — 订单管理 Service 层

从 routes/orders.py 提取全部业务逻辑。
"""
import json
import logging
from datetime import datetime, timedelta
from modules.services import BaseService
from modules.services.query_utils import paginate, build_sort_clause
from modules.repositories.order_repository import OrderRepository
from modules.repositories.order_material_repository import OrderMaterialRepository
from modules.services.order_material_snapshot_service import OrderMaterialSnapshotService
from modules.services.order_process_sync_service import OrderProcessSyncService
from modules.setting_reader import get_setting

# Extracted constants — Brooks R4 fix
_logger = logging.getLogger(__name__)



# ============================================================
# 订单号生成（模块级工具函数，含事务锁防竞态）
# ============================================================

def _generate_order_no(db):
    """自动生成订单号：前缀 + 2位顺序号。
    
    前缀从 system_settings.auto_order_no 读取，支持占位符 YYYY/YY/MM/DD。
    如果未配置，默认使用 YYMMDD 格式。
    调用方必须在外层管理事务。
    """
    today = datetime.now()
    
    prefix_template = get_setting("auto_order_no", "").strip()
    if prefix_template:
        prefix = prefix_template.replace("YYYY", today.strftime("%Y")) \
                                .replace("YY", today.strftime("%y")) \
                                .replace("MM", today.strftime("%m")) \
                                .replace("DD", today.strftime("%d"))
    else:
        prefix = today.strftime('%y%m%d')
    
    row = db.execute(
        "SELECT order_no FROM orders WHERE order_no LIKE ? ORDER BY id DESC LIMIT 1",
        (prefix + '%',)
    ).fetchone()
    if row:
        try:
            suffix = row['order_no'][len(prefix):]
            seq = int(suffix) + 1
        except (ValueError, IndexError):
            seq = 1
    else:
        seq = 1
    for _ in range(100):
        order_no = prefix + str(seq).zfill(2)
        existing = db.execute('SELECT id FROM orders WHERE order_no = ?', (order_no,)).fetchone()
        if not existing:
            return order_no
        seq += 1
    raise RuntimeError(f'订单号生成失败：前缀{prefix}下所有序号已用尽')


class OrderService:
    """订单管理业务逻辑。"""

    # ============================================================
    # 辅助 — 根据 route_id 或 process_ids 分配工序
    # ============================================================

    @staticmethod
    def _assign_processes(db, order_id, route_id=None, process_ids=None):
        """Backward-compatible wrapper for order process assignment."""
        OrderProcessSyncService.assign_processes(db, order_id, route_id, process_ids)

    # ============================================================
    # 查询
    # ============================================================

    @staticmethod
    def list_orders(page=1, limit=DEFAULT_PAGE_SIZE, status='', keyword='', customer='',
                    data_scope_pids=None):
        """分页查询订单列表（含数据权限过滤）。"""
        where = ['o.deleted_at IS NULL']
        params = []
        if status:
            where.append('o.status = ?')
            params.append(status)
        if keyword:
            where.append('(o.order_no LIKE ? OR o.product_name LIKE ? OR o.product_code LIKE ? OR o.customer LIKE ?)')
            params.extend([f'%{keyword}%'] * 4)
        if customer:
            where.append('o.customer LIKE ?')
            params.append(f'%{customer}%')

        if data_scope_pids is not None:
            if not data_scope_pids:
                return {'orders': [], 'total': 0, 'page': page, 'limit': limit,
                        'pending': 0, 'producing': 0, 'completed': 0}
            placeholders = ','.join('?' for _ in data_scope_pids)
            where.append(
                f"o.id IN (SELECT order_id FROM order_processes WHERE process_id IN ({placeholders}))"
            )
            params.extend(data_scope_pids)

        where_sql = ' AND '.join(where)
        size = min(max(limit, 1), MAX_PAGE_LIMIT)
        rows, total = OrderRepository.list_all(
            where_sql, params, page, size, order_by='o.order_no DESC'
        )
        all_procs = {}
        for process in OrderRepository.list_processes_for_orders([row['id'] for row in rows]):
            all_procs.setdefault(process['order_id'], []).append(dict(process))

        result = []
        for row in rows:
            order = dict(row)
            try:
                order['extra_fields'] = json.loads(order.get('extra_fields') or '{}')
            except (TypeError, json.JSONDecodeError):
                _logger.warning("invalid order extra_fields: order_id=%s", order.get("id"))
                order['extra_fields'] = {}
            if not (order.get('product_code') or '').strip():
                order['product_code'] = (
                    order['extra_fields'].get('product_code', '')
                    if isinstance(order['extra_fields'], dict) else ''
                )
            order['processes'] = all_procs.get(order['id'], [])
            result.append(order)

        counts = {row['status']: row['cnt'] for row in OrderRepository.count_by_status(where_sql, params)}
        return {
            'orders': result, 'total': total, 'page': page, 'limit': size,
            'pending': counts.get('pending', 0),
            'producing': counts.get('producing', 0),
            'completed': counts.get('completed', 0)
        }

    # ============================================================
    # 单号
    # ============================================================

    @staticmethod
    def next_order_no():
        """生成下一个可用订单号。"""
        with BaseService.transaction() as txn:
            return _generate_order_no(txn)

    # ============================================================
    # 创建
    # ============================================================

    @staticmethod
    def create_order(data):
        """
        创建订单。

        Args:
            data: dict with order_no, customer_id, product_name, route_id, process_ids, etc.

        Returns:
            int: 新订单 ID

        Raises:
            ValueError: 订单号冲突
            RuntimeError: 数据库错误
        """
        order_no = data.get('order_no', '').strip()
        if not order_no:
            db = BaseService.db()
            order_no = _generate_order_no(db)

        route_id = data.get('route_id')
        customer_id = data.get('customer_id')
        customer = (data.get('customer') or '').strip()
        if not customer and customer_id:
            customer_name = OrderRepository.find_customer_name(customer_id)
            if customer_name:
                customer = customer_name

        extra = {k: v for k, v in data.items()
                 if k not in ('order_no', 'customer', 'customer_id', 'product_name',
                              'quantity', 'plan_start', 'plan_end', 'deadline', 'remark',
                              'process_ids', 'route_id', 'production_line_id')}

        process_ids = data.get('process_ids', [])

        with BaseService.transaction() as txn:
            # 冲突检查 + 自动重试（最多5次）
            for _ in range(5):
                existing = txn.execute('SELECT id FROM orders WHERE order_no = ?', (order_no,)).fetchone()
                if not existing:
                    break
                order_no = _generate_order_no(txn)
            else:
                raise ValueError('订单号冲突，请重试（已重试5次）')

            cur = txn.execute('''
                INSERT INTO orders (order_no, customer, customer_id, product_name, quantity,
                    plan_start, plan_end, deadline, extra_fields, remark, route_id, status, product_code, production_line_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,'pending', ?, ?)
            ''', (
                order_no, customer, customer_id if customer_id else None,
                data.get('product_name', ''), data.get('quantity', 0),
                data.get('plan_start', '') or datetime.now().strftime('%Y-%m-%d'), data.get('plan_end', '') or (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d'),
                data.get('deadline', ''), json.dumps(extra, ensure_ascii=False),
                data.get('remark', ''), route_id if route_id else None,
                data.get('product_code', ''),
                data.get('production_line_id')
            ))
            order_id = cur.lastrowid
            OrderService._assign_processes(txn, order_id, route_id, process_ids)

            product_id = OrderMaterialSnapshotService.resolve_product_id(data, txn)
            OrderMaterialSnapshotService.copy_product_bom(order_id, product_id, txn)

        return order_id, order_no

    # ============================================================
    # 更新（含状态机）
    # ============================================================

    VALID_TRANSITIONS = {
        'pending':   ['producing', 'cancelled', 'paused'],
        'producing': ['completed', 'cancelled', 'paused'],
        'completed': [],
        'cancelled': ['pending'],
        'paused':    ['producing', 'pending', 'cancelled'],
    }

    @staticmethod
    def update_order(oid, data, user_id=None, user_name=None):
        """
        更新订单（含状态机校验 + 备注历史记录）。

        Args:
            oid: 订单ID
            data: 更新字段
            user_id: 操作用户ID（用于备注历史）
            user_name: 操作用户名（用于备注历史）

        Raises:
            ValueError: 订单不存在 / 状态转换非法
            RuntimeError: 数据库错误
        """
        db = BaseService.db()
        existing = OrderRepository.find_status_by_id(oid)
        if not existing:
            raise ValueError('订单不存在')

        # 状态转换校验
        if 'status' in data:
            new_status = data['status']
            old_status = existing['status']
            if new_status != old_status:
                allowed = OrderService.VALID_TRANSITIONS.get(old_status, [])
                if new_status not in allowed:
                    raise ValueError(f"不允许从「{old_status}」切换到「{new_status}」")

        # customer_id → name lookup
        if 'customer_id' in data and data['customer_id']:
            if not (data.get('customer') or '').strip():
                customer_name = OrderRepository.find_customer_name(data['customer_id'])
                if customer_name:
                    data['customer'] = customer_name

        # Detect remark change before entering transaction; the old value is fetched again
        # inside the transaction to avoid relying on the lightweight status query.
        remark_changed = 'remark' in data

        sets = []
        params = []
        for field in ['order_no', 'customer', 'customer_id', 'product_name', 'product_code',
                       'quantity', 'plan_start', 'plan_end', 'deadline', 'remark', 'status', 'route_id', 'production_line_id']:
            if field in data:
                sets.append(f'{field} = ?')
                params.append(data[field] if data[field] is not None else None)

        with BaseService.transaction() as txn:
            # TOCTOU-safe remark history: re-read inside transaction
            if remark_changed and user_id:
                current = OrderRepository.find_order_remark(oid, db=txn)
                if current and data['remark'] != (current['remark'] or ''):
                    OrderService.log_remark_history(
                        oid,
                        current['remark'] or '',
                        data['remark'],
                        user_id,
                        user_name or '',
                        db=txn
                    )

            if sets:
                sets.append("updated_at = datetime('now','localtime')")
                OrderRepository.update_fields(oid, sets, params, db=txn)

            if 'process_ids' in data:
                OrderProcessSyncService.sync_processes(txn, oid, data["process_ids"])

        return True

    # ============================================================
    # 删除（级联清理子表）
    # ============================================================

    @staticmethod
    def delete_order(oid, deleted_by=None):
        """
        软删除订单（移入回收站）。

        Raises:
            ValueError: 订单不存在
            RuntimeError: 数据库错误
        """
        db = BaseService.db()
        existing = OrderRepository.find_including_deleted(oid)
        if not existing:
            raise ValueError('订单不存在')
        deleted = existing['deleted_at'] if existing else None
        if deleted:
            raise ValueError('订单已在回收站中')

        with BaseService.transaction() as txn:
            OrderRepository.mark_deleted(oid, deleted_by=deleted_by, db=txn)

        return existing['order_no']

    # ============================================================
    # 工单记录查询
    # ============================================================

    @staticmethod
    def get_work_records(oid):
        """获取订单关联的报工/返工/报废记录。"""
        order = OrderRepository.find_by_id(oid)
        if not order:
            raise ValueError('订单不存在')

        grouped_records = OrderRepository.get_work_records(oid)
        normal = grouped_records['work']
        scrap = grouped_records['scrap']
        rework = grouped_records['rework']
        all_records = normal + scrap + rework
        all_records.sort(key=lambda record: record.get('created_at', ''), reverse=True)

        return {
            'order_id': oid,
            'order_no': order['order_no'],
            'records': all_records,
            'summary': {
                'normal_count': len(normal),
                'scrap_count': len(scrap),
                'rework_count': len(rework),
                'total_quantity': sum(record.get('quantity', 0) for record in normal)
            }
        }

    # ============================================================
    # 发货记录查询
    # ============================================================

    @staticmethod
    def get_shipments(oid):
        """获取订单关联产品的发货记录。"""
        order = OrderRepository.find_by_id(oid)
        if not order:
            raise ValueError('订单不存在')
        shipments = OrderRepository.get_shipments_by_product_code(order['product_code'])
        return {
            'order_id': oid,
            'order_no': order['order_no'],
            'product_name': order['product_name'],
            'product_code': order['product_code'],
            'shipments': [dict(s) for s in shipments]
        }

    # ============================================================
    # ============================================================
    # 回收站
    # ============================================================

    @staticmethod
    def get_order(oid):
        """获取单个订单"""
        return OrderRepository.find_by_id(oid)

    @staticmethod
    def log_remark_history(oid, old_remark, new_remark, user_id, user_name, db=None):
        """记录备注变更历史。当 db 参数传入时复用已有事务连接。"""
        if db is not None:
            db.execute(
                "INSERT INTO order_remark_history (order_id, old_remark, new_remark, user_id, user_name) "
                "VALUES (?,?,?,?,?)",
                (oid, old_remark, new_remark, user_id, user_name)
            )
        else:
            with BaseService.transaction() as txn:
                txn.execute(
                    "INSERT INTO order_remark_history (order_id, old_remark, new_remark, user_id, user_name) "
                    "VALUES (?,?,?,?,?)",
                    (oid, old_remark, new_remark, user_id, user_name)
                )

    @staticmethod
    def soft_delete_order(oid, user_id):
        """软删除订单（适配器）"""
        return OrderService.delete_order(oid, deleted_by=user_id)

    @staticmethod
    def list_trash(page=1, limit=20):
        """回收站列表（适配器）"""
        return OrderService.trash_orders(page, limit)

    @staticmethod
    def get_workpiece_progress(order_id):
        """获取工件报工进度"""
        order = OrderRepository.find_by_id(order_id)
        if not order:
            raise ValueError("订单不存在")
        items, processes, work_records = OrderRepository.get_workpiece_progress_rows(order_id)
        record_map = {}
        for record in work_records:
            serial_no = record["serial_no"]
            record_map.setdefault(serial_no, {})[record["process_id"]] = {
                "status": record["status"],
                "completed_at": record["created_at"],
            }
        return {
            "order": dict(order),
            "items": [dict(item) for item in items],
            "processes": [dict(process) for process in processes],
            "record_map": record_map,
        }

    @staticmethod
    def trash_orders(page=1, limit=DEFAULT_PAGE_SIZE):
        """分页查询回收站订单。"""
        page = max(page, 1)
        limit = min(max(limit, 1), 200)
        rows, total = OrderRepository.list_trash(page, limit)
        return {
            'orders': [dict(row) for row in rows],
            'total': total,
            'page': page,
            'limit': limit
        }

    @staticmethod
    def restore_order(oid):
        """从回收站恢复订单。"""
        db = BaseService.db()
        existing = OrderRepository.find_including_deleted(oid)
        if not existing:
            raise ValueError('订单不存在')
        if not existing['deleted_at']:
            raise ValueError('订单不在回收站中')

        old_status = existing['pre_delete_status'] or 'pending'
        with BaseService.transaction() as txn:
            OrderRepository.restore(oid, old_status, db=txn)
        return existing['order_no']

    @staticmethod
    def batch_create(orders_data):
        """批量创建订单。返回 (created_count, errors_list)。"""
        created = 0
        errors = []
        for item in orders_data:
            try:
                OrderService.create_order(item)
                created += 1
            except Exception as e:
                errors.append(str(e))
        return created, errors

    @staticmethod
    def purge_order(oid):
        db = BaseService.db()
        existing = OrderRepository.find_including_deleted(oid)
        if not existing:
            raise ValueError('订单不存在')
        if not existing['deleted_at']:
            raise ValueError('只能彻底删除回收站中的订单')
        # Whitelist of child tables for cascading delete (verified safe)
        _PURGE_CHILD_TABLES = [
            "order_attachments", "order_remark_history",
            "order_materials", "order_processes", "product_items",
            "work_records", "scrap_records", "rework_records",
            "quality_inspections"
        ]
        with BaseService.transaction() as txn:
            for tbl in _PURGE_CHILD_TABLES:
                # Table names are from hardcoded whitelist, safe from SQL injection
                txn.execute(f"DELETE FROM {tbl} WHERE order_id = ?", (oid,))
            txn.execute("DELETE FROM orders WHERE id = ?", (oid,))
        return existing['order_no'] or ""

    # ============================================================
    # Order Materials
    # ============================================================
    @staticmethod
    def list_order_materials(order_id):
        if not OrderService.get_order(order_id):
            raise ValueError('?????')
        return [dict(row) for row in OrderMaterialRepository.list_by_order(order_id)]

    @staticmethod
    def add_order_material(order_id, data):
        if not OrderService.get_order(order_id):
            raise ValueError('?????')
        material_id = data.get('material_id')
        quantity = data.get('quantity') or data.get('quantity_per_unit', 1)
        process_id = data.get('process_id') or None
        if not material_id:
            raise ValueError('?????')
        with BaseService.transaction() as txn:
            if OrderMaterialRepository.find_duplicate(order_id, material_id, process_id, db=txn):
                raise LookupError('???+???????')
            new_id = OrderMaterialRepository.insert(
                order_id, material_id, quantity, process_id, 'manual', db=txn
            )
            row = OrderMaterialRepository.find_by_id(new_id, db=txn)
            return dict(row)

    @staticmethod
    def delete_order_material(order_id, item_id):
        with BaseService.transaction() as txn:
            if not OrderMaterialRepository.find_by_id_and_order(item_id, order_id, db=txn):
                raise ValueError('??????')
            OrderMaterialRepository.delete(item_id, db=txn)
