from modules.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_LIMIT
"""
qr-system — 订单管理 Service 层

从 routes/orders.py 提取全部业务逻辑。
"""
import json
import logging
from datetime import datetime, timedelta
from modules.services import BaseService
from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.services.query_utils import paginate, build_sort_clause
from modules.repositories.order_repository import OrderRepository
from modules.repositories.order_material_repository import OrderMaterialRepository
from modules.services.order_material_snapshot_service import OrderMaterialSnapshotService
from modules.services.order_process_sync_service import OrderProcessSyncService
from modules.services.order_completion_service import OrderCompletionService
from modules.setting_reader import get_setting

# Extracted constants — Brooks R4 fix
_logger = logging.getLogger(__name__)



# ============================================================
# 订单号生成（模块级工具函数，含事务锁防竞态）
# ============================================================

def _order_no_prefix(today):
    prefix_template = get_setting("auto_order_no", "").strip()
    if not prefix_template:
        return today.strftime('%y%m%d')
    return (prefix_template.replace("YYYY", today.strftime("%Y"))
                           .replace("YY", today.strftime("%y"))
                           .replace("MM", today.strftime("%m"))
                           .replace("DD", today.strftime("%d")))


def _next_order_sequence(prefix, db):
    row = OrderRepository.find_latest_order_no_with_prefix(prefix, db=db)
    if not row:
        return 1
    try:
        return int(row['order_no'][len(prefix):]) + 1
    except (ValueError, IndexError):
        return 1


def _generate_order_no(db):
    """自动生成订单号：前缀 + 2位顺序号。调用方必须在外层管理事务。"""
    prefix = _order_no_prefix(datetime.now())
    seq = _next_order_sequence(prefix, db)
    for _ in range(100):
        order_no = prefix + str(seq).zfill(2)
        if not OrderRepository.exists_by_order_no(order_no, db=db):
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

    @staticmethod
    def _resolve_customer_name(customer_id, customer):
        customer = (customer or '').strip()
        if customer or not customer_id:
            return customer
        return OrderRepository.find_customer_name(customer_id) or customer

    @staticmethod
    def _create_order_extra(data):
        core_fields = {
            'order_no', 'customer', 'customer_id', 'product_name', 'quantity',
            'plan_start', 'plan_end', 'deadline', 'remark', 'process_ids',
            'route_id', 'production_line_id', 'status'
        }
        return {key: value for key, value in data.items() if key not in core_fields}

    @staticmethod
    def _build_create_payload(data, order_no, customer, customer_id, route_id, extra):
        return {
            "order_no": order_no,
            "customer": customer,
            "customer_id": customer_id if customer_id else None,
            "product_name": data.get('product_name', ''),
            "quantity": data.get('quantity', 0),
            "plan_start": data.get('plan_start', '') or datetime.now().strftime('%Y-%m-%d'),
            "plan_end": data.get('plan_end', '') or (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d'),
            "deadline": data.get('deadline', ''),
            "extra_fields": json.dumps(extra, ensure_ascii=False),
            "remark": data.get('remark', ''),
            "route_id": route_id if route_id else None,
            "product_code": data.get('product_code', ''),
            "production_line_id": data.get('production_line_id'),
        }

    # ============================================================
    # 查询
    # ============================================================

    @staticmethod
    def list_orders(page=1, limit=DEFAULT_PAGE_SIZE, status='', keyword='', customer='',
                    data_scope_pids=None, archive='active'):
        """分页查询订单列表（含数据权限过滤）。"""
        size = min(max(limit, 1), MAX_PAGE_LIMIT)
        rows, total, counts, archive = OrderRepository.list_filtered(
            keyword=keyword,
            customer=customer,
            status=status,
            data_scope_pids=data_scope_pids,
            archive=archive,
            page=page,
            limit=size,
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

        return {
            'orders': result, 'total': total, 'page': page, 'limit': size,
            'pending': counts.get('pending', 0),
            'producing': counts.get('producing', 0),
            'completed': counts.get('completed', 0),
            'archive': archive
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
        customer = OrderService._resolve_customer_name(customer_id, data.get('customer'))
        extra = OrderService._create_order_extra(data)
        process_ids = data.get('process_ids', [])

        with BaseService.transaction() as txn:
            # 冲突检查 + 自动重试（最多5次）
            for _ in range(5):
                existing = OrderRepository.exists_by_order_no(order_no, db=txn)
                if not existing:
                    break
                order_no = _generate_order_no(txn)
            else:
                raise ValueError('订单号冲突，请重试（已重试5次）')

            payload = OrderService._build_create_payload(
                data, order_no, customer, customer_id, route_id, extra
            )
            order_id = OrderRepository.insert_from_order_form(payload, db=txn)
            OrderService._assign_processes(txn, order_id, route_id, process_ids)

            product_id = OrderMaterialSnapshotService.resolve_product_id(data, txn)
            OrderMaterialSnapshotService.copy_product_bom(order_id, product_id, txn)

        return order_id, order_no

    # ============================================================
    # 更新（含状态机）
    # ============================================================

    VALID_TRANSITIONS = {
        'pending':   ['producing', 'cancelled', 'paused'],
        'producing': ['cancelled', 'paused'],
        'completed': [],
        'cancelled': ['pending'],
        'paused':    ['producing', 'pending', 'cancelled'],
    }
    COMPLETED_READONLY_MESSAGE = '已完成订单已归档，只读，请先重新打开订单'
    REOPEN_STATUSES = {'pending', 'producing'}

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
        existing = OrderRepository.find_status_by_id(oid)
        if not existing:
            raise ValueError('订单不存在')
        if existing['deleted_at']:
            raise ValueError('订单已在回收站中')
        if existing['status'] == 'completed':
            raise ValueError(OrderService.COMPLETED_READONLY_MESSAGE)

        if data.get('status') == 'completed':
            raise ValueError('订单完成状态只能由系统根据实际完工事实自动生成')

        # customer_id → name lookup
        if 'customer_id' in data and data['customer_id']:
            if not (data.get('customer') or '').strip():
                customer_name = OrderRepository.find_customer_name(data['customer_id'])
                if customer_name:
                    data['customer'] = customer_name

        # Detect remark change before entering transaction; the old value is fetched again
        # inside the transaction to avoid relying on the lightweight status query.
        remark_changed = 'remark' in data

        with BaseService.transaction() as txn:
            # Re-check the lifecycle state after acquiring the write transaction.
            # The initial read above is only for fast feedback and is not a lock.
            current = OrderRepository.find_status_by_id(oid, db=txn)
            if not current:
                raise ValueError('订单不存在')
            if current['deleted_at']:
                raise ValueError('订单已在回收站中')
            if current['status'] == 'completed':
                raise ValueError(OrderService.COMPLETED_READONLY_MESSAGE)

            if 'status' in data and data['status'] != current['status']:
                allowed = OrderService.VALID_TRANSITIONS.get(current['status'], [])
                if data['status'] not in allowed:
                    raise ValueError(f"不允许从「{current['status']}」切换到「{data['status']}」")

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

            OrderRepository.update_form_fields(oid, data, db=txn)

            if 'process_ids' in data:
                OrderProcessSyncService.sync_processes(txn, oid, data["process_ids"])
            elif 'route_id' in data and data['route_id']:
                OrderProcessSyncService.sync_route(txn, oid, data['route_id'])

            if {'process_ids', 'route_id', 'quantity'} & set(data):
                OrderCompletionService.reconcile(
                    oid,
                    trigger='order_structure_updated',
                    actor_id=user_id,
                    db=txn,
                )

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
        if existing['status'] == 'completed':
            raise ValueError(OrderService.COMPLETED_READONLY_MESSAGE)

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
            OrderRepository.insert_remark_history(oid, old_remark, new_remark, user_id, user_name, db=db)
        else:
            with BaseService.transaction() as txn:
                OrderRepository.insert_remark_history(oid, old_remark, new_remark, user_id, user_name, db=txn)

    @staticmethod
    def soft_delete_order(oid, user_id):
        """软删除订单（适配器）"""
        return OrderService.delete_order(oid, deleted_by=user_id)

    @staticmethod
    def reopen_order(oid, reason, status='producing'):
        """重新打开已完成归档订单。"""
        reason = (reason or '').strip()
        if not reason:
            raise ValueError('请填写重新打开原因')
        status = (status or 'producing').strip().lower()
        if status not in OrderService.REOPEN_STATUSES:
            raise ValueError('重新打开后的状态只能是 pending 或 producing')

        existing = OrderRepository.find_status_by_id(oid)
        if not existing:
            raise ValueError('订单不存在')
        if existing['deleted_at']:
            raise ValueError('订单已在回收站中')
        if existing['status'] != 'completed':
            raise ValueError('只有已完成订单可以重新打开')

        with BaseService.transaction() as txn:
            OrderRepository.reopen_completed(oid, status, db=txn)

        return {'id': oid, 'status': status, 'reason': reason}

    @staticmethod
    def list_trash(page=1, limit=20, data_scope_pids=None):
        """回收站列表（适配器）"""
        return OrderService.trash_orders(page, limit, data_scope_pids=data_scope_pids)

    @staticmethod
    def get_workpiece_progress(order_id):
        """Return order workpiece progress and risk analysis."""
        from modules.services.order_progress_analyzer import OrderProgressAnalyzer

        return OrderProgressAnalyzer.analyze(order_id)

    @staticmethod
    def trash_orders(page=1, limit=DEFAULT_PAGE_SIZE, data_scope_pids=None):
        """分页查询回收站订单。"""
        page = max(page, 1)
        limit = min(max(limit, 1), 200)
        rows, total = OrderRepository.list_trash(
            page,
            limit,
            data_scope_pids=data_scope_pids,
        )
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
            OrderRepository.purge_with_children(oid, _PURGE_CHILD_TABLES, db=txn)
        return existing['order_no'] or ""

    # ============================================================
    # Order Materials
    # ============================================================
    @staticmethod
    def list_order_materials(order_id):
        if not OrderService.get_order(order_id):
            raise NotFoundError('订单不存在')
        return [dict(row) for row in OrderMaterialRepository.list_by_order(order_id)]

    @staticmethod
    def add_order_material(order_id, data):
        order = OrderService.get_order(order_id)
        if not order:
            raise NotFoundError('订单不存在')
        if order['status'] == 'completed':
            raise ValueError(OrderService.COMPLETED_READONLY_MESSAGE)
        material_id = data.get('material_id')
        quantity = data.get('quantity') or data.get('quantity_per_unit', 1)
        process_id = data.get('process_id') or None
        if not material_id:
            raise ValidationError('物料 ID 不能为空')
        with BaseService.transaction() as txn:
            if OrderMaterialRepository.find_duplicate(order_id, material_id, process_id, db=txn):
                raise ConflictError('该物料已存在于订单物料配方中')
            new_id = OrderMaterialRepository.insert(
                order_id, material_id, quantity, process_id, 'manual', db=txn
            )
            row = OrderMaterialRepository.find_by_id(new_id, db=txn)
            return dict(row)

    @staticmethod
    def delete_order_material(order_id, item_id):
        with BaseService.transaction() as txn:
            order = OrderRepository.find_by_id(order_id, db=txn)
            if order and order['status'] == 'completed':
                raise ValueError(OrderService.COMPLETED_READONLY_MESSAGE)
            if not OrderMaterialRepository.find_by_id_and_order(item_id, order_id, db=txn):
                raise NotFoundError('订单物料记录不存在')
            OrderMaterialRepository.delete(item_id, db=txn)
