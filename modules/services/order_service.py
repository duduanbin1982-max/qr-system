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
from modules.domain.order_lifecycle import (
    COMPLETED_READONLY_MESSAGE,
    REOPEN_STATUSES,
    VALID_TRANSITIONS,
    OrderLifecycle,
)
from modules.services.query_utils import paginate, build_sort_clause
from modules.repositories.order_repository import OrderRepository
from modules.repositories.order_material_repository import OrderMaterialRepository
from modules.services.order_material_snapshot_service import OrderMaterialSnapshotService
from modules.services.order_process_sync_service import OrderProcessSyncService
from modules.services.order_completion_service import OrderCompletionService
from modules.services.order_product_identity_service import OrderProductIdentityService
from modules.setting_reader import get_setting

# Extracted constants — Brooks R4 fix
_logger = logging.getLogger(__name__)



# ============================================================
# 订单号生成（模块级工具函数，含事务锁防竞态）
# ============================================================

def _order_no_prefix(today, setting_reader=None):
    reader = setting_reader or get_setting
    prefix_template = reader("auto_order_no", "").strip()
    if not prefix_template:
        return today.strftime('%y%m%d')
    return (prefix_template.replace("YYYY", today.strftime("%Y"))
                           .replace("YY", today.strftime("%y"))
                           .replace("MM", today.strftime("%m"))
                           .replace("DD", today.strftime("%d")))


def _next_order_sequence(prefix, db, repository=None):
    repository = repository or OrderRepository
    row = repository.find_latest_order_no_with_prefix(prefix, db=db)
    if not row:
        return 1
    try:
        return int(row['order_no'][len(prefix):]) + 1
    except (ValueError, IndexError):
        return 1


def _generate_order_no(db, repository=None, setting_reader=None):
    """自动生成订单号：前缀 + 2位顺序号。调用方必须在外层管理事务。"""
    repository = repository or OrderRepository
    prefix = _order_no_prefix(datetime.now(), setting_reader)
    seq = _next_order_sequence(prefix, db, repository)
    for _ in range(100):
        order_no = prefix + str(seq).zfill(2)
        if not repository.exists_by_order_no(order_no, db=db):
            return order_no
        seq += 1
    raise RuntimeError(f'订单号生成失败：前缀{prefix}下所有序号已用尽')

class OrderService:
    """订单管理业务逻辑。"""

    repository = None
    material_repository = None
    material_snapshot_service = None
    process_sync_service = None
    completion_service = None
    product_identity_service = None
    unit_of_work = None
    setting_reader = None

    @classmethod
    def _repository(cls):
        return cls.repository or OrderRepository

    @classmethod
    def _material_repository(cls):
        return cls.material_repository or OrderMaterialRepository

    @classmethod
    def _material_snapshot_service(cls):
        return cls.material_snapshot_service or OrderMaterialSnapshotService

    @classmethod
    def _process_sync_service(cls):
        return cls.process_sync_service or OrderProcessSyncService

    @classmethod
    def _completion_service(cls):
        return cls.completion_service or OrderCompletionService

    @classmethod
    def _product_identity_service(cls):
        return cls.product_identity_service or OrderProductIdentityService

    @classmethod
    def _unit_of_work(cls):
        return cls.unit_of_work or BaseService

    @classmethod
    def _setting_reader(cls):
        return vars(cls).get("setting_reader") or get_setting

    @classmethod
    def _generate_order_no(cls, db):
        return _generate_order_no(
            db,
            repository=cls._repository(),
            setting_reader=cls._setting_reader(),
        )

    # ============================================================
    # 辅助 — 根据 route_id 或 process_ids 分配工序
    # ============================================================

    @staticmethod
    def _assign_processes(
        db, order_id, route_id=None, process_ids=None, assignment=None
    ):
        """Backward-compatible wrapper for order process assignment."""
        OrderService._process_sync_service().assign_processes(
            db, order_id, route_id, process_ids, assignment=assignment
        )

    @staticmethod
    def _resolve_customer_name(customer_id, customer):
        customer = (customer or '').strip()
        if customer or not customer_id:
            return customer
        return OrderService._repository().find_customer_name(customer_id) or customer

    @staticmethod
    def _create_order_extra(data):
        core_fields = {
            'order_no', 'customer', 'customer_id', 'product_name', 'quantity',
            'plan_start', 'plan_end', 'deadline', 'remark', 'process_ids',
            'route_id', 'production_line_id', 'status', 'product_id'
        }
        return {key: value for key, value in data.items() if key not in core_fields}

    @staticmethod
    def _build_create_payload(data, order_no, customer, customer_id, route_id, extra):
        return {
            "order_no": order_no,
            "customer": customer,
            "customer_id": customer_id if customer_id else None,
            "product_name": data.get('product_name', ''),
            "product_id": data.get('product_id'),
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

    @classmethod
    def _prepare_create_context(cls, data):
        """Resolve request-level values before opening the create transaction."""
        order_no = data.get('order_no', '').strip()
        if not order_no:
            order_no = cls._generate_order_no(cls._unit_of_work().db())
        customer_id = data.get('customer_id')
        customer = cls._resolve_customer_name(customer_id, data.get('customer'))
        process_ids = data.get('process_ids', [])
        return order_no, customer_id, customer, process_ids

    @classmethod
    def _allocate_create_order_no(cls, order_no, txn, repository):
        """Keep a requested order number when free, otherwise allocate a fresh one."""
        for _ in range(5):
            if not repository.exists_by_order_no(order_no, db=txn):
                return order_no
            order_no = cls._generate_order_no(txn)
        raise ValueError('订单号冲突，请重试（已重试5次）')

    @classmethod
    def _persist_created_order(
        cls,
        txn,
        normalized_data,
        order_no,
        customer_id,
        customer,
        process_ids,
        repository,
    ):
        """Persist the order aggregate and snapshots atomically."""
        route_id = normalized_data.get('route_id')
        assignment = cls._process_sync_service().prepare_assignment(
            txn, route_id=route_id, process_ids=process_ids
        )
        extra = cls._create_order_extra(normalized_data)
        payload = cls._build_create_payload(
            normalized_data, order_no, customer, customer_id, route_id, extra
        )
        payload.update(
            {
                "route_version_id": assignment["route_version_id"],
                "route_name_snapshot": assignment["route_name_snapshot"],
            }
        )
        order_id = repository.insert_from_order_form(payload, db=txn)
        cls._assign_processes(
            txn,
            order_id,
            route_id,
            process_ids,
            assignment=assignment,
        )
        cls._material_snapshot_service().copy_product_bom(
            order_id,
            normalized_data.get('product_id'),
            txn,
        )
        return order_id

    # ============================================================
    # 查询
    # ============================================================

    @staticmethod
    def list_orders(page=1, limit=DEFAULT_PAGE_SIZE, status='', keyword='', customer='',
                    data_scope_pids=None, archive='active'):
        """分页查询订单列表（含数据权限过滤）。"""
        repository = OrderService._repository()
        size = min(max(limit, 1), MAX_PAGE_LIMIT)
        rows, total, counts, archive = repository.list_filtered(
            keyword=keyword,
            customer=customer,
            status=status,
            data_scope_pids=data_scope_pids,
            archive=archive,
            page=page,
            limit=size,
        )
        all_procs = {}
        for process in repository.list_processes_for_orders([row['id'] for row in rows]):
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
        with OrderService._unit_of_work().transaction() as txn:
            return OrderService._generate_order_no(txn)

    @staticmethod
    def record_qr_print(oid, data, user):
        """Persist one QR-code print action for an order."""
        mode = (data.get('mode') or '').strip().lower()
        if mode not in {'order', 'serial'}:
            raise ValidationError('二维码模式必须是订单模式或序列号模式')
        try:
            copies = int(data.get('copies', 1))
            label_count = int(data.get('label_count', 0))
        except (TypeError, ValueError):
            raise ValidationError('打印份数和标签数量必须是整数')
        if copies < 1 or copies > 10:
            raise ValidationError('打印份数必须在 1 到 10 之间')
        if label_count < 1 or label_count > 999999:
            raise ValidationError('打印标签数量无效')

        repository = OrderService._repository()
        with OrderService._unit_of_work().transaction() as txn:
            order = repository.find_by_id(oid, db=txn)
            if not order:
                raise NotFoundError('订单不存在或已删除')
            existing_mode = (order['qr_mode'] or '').strip()
            if existing_mode and existing_mode != mode:
                raise ConflictError('打印模式与订单已锁定的二维码模式不一致')
            user_name = user.get('name') or user.get('username') or ''
            updated = repository.record_qr_print(
                oid,
                user.get('id'),
                user_name,
                db=txn,
            )
            if updated != 1:
                raise ConflictError('订单打印状态已变化，请刷新后重试')
            status = repository.get_qr_print_status(oid, db=txn)

        result = dict(status)
        result.update({
            'order_no': order['order_no'],
            'mode': mode,
            'copies': copies,
            'label_count': label_count,
        })
        return result

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
        order_no, customer_id, customer, process_ids = OrderService._prepare_create_context(data)
        repository = OrderService._repository()
        with OrderService._unit_of_work().transaction() as txn:
            normalized_data = OrderService._product_identity_service().normalize_create(
                data,
                txn,
            )
            order_no = OrderService._allocate_create_order_no(
                order_no,
                txn,
                repository,
            )
            order_id = OrderService._persist_created_order(
                txn,
                normalized_data,
                order_no,
                customer_id,
                customer,
                process_ids,
                repository,
            )

        return order_id, order_no

    # ============================================================
    # 更新（含状态机）
    # ============================================================

    VALID_TRANSITIONS = VALID_TRANSITIONS
    COMPLETED_READONLY_MESSAGE = COMPLETED_READONLY_MESSAGE
    REOPEN_STATUSES = REOPEN_STATUSES

    @staticmethod
    def _resolve_update_customer(data):
        if 'customer_id' not in data or not data['customer_id']:
            return
        if (data.get('customer') or '').strip():
            return
        customer_name = OrderService._repository().find_customer_name(data['customer_id'])
        if customer_name:
            data['customer'] = customer_name

    @staticmethod
    def _record_update_remark(oid, data, user_id, user_name, txn):
        if 'remark' not in data or not user_id:
            return
        current_remark = OrderService._repository().find_order_remark(oid, db=txn)
        if current_remark and data['remark'] != (current_remark['remark'] or ''):
            OrderService.log_remark_history(
                oid,
                current_remark['remark'] or '',
                data['remark'],
                user_id,
                user_name or '',
                db=txn,
            )

    @staticmethod
    def _sync_updated_processes(txn, oid, data, route_changed, process_ids_changed):
        process_sync_service = OrderService._process_sync_service()
        if process_ids_changed:
            process_sync_service.sync_processes(txn, oid, data['process_ids'])
        elif route_changed:
            if data['route_id']:
                process_sync_service.sync_route(
                    txn,
                    oid,
                    data['route_id'],
                    route_version_id=data.get('route_version_id'),
                )
            else:
                process_sync_service.clear_processes(txn, oid)

    @staticmethod
    def _validate_quantity_against_serial_items(oid, current_order, data, txn):
        if 'quantity' not in data or data['quantity'] == current_order['quantity']:
            return
        active_items = OrderService._repository().count_active_product_items(
            oid, db=txn
        )
        if active_items and int(data['quantity']) != active_items:
            raise ValidationError(
                f'该订单已有 {active_items} 个有效序列件，订单数量必须与其一致；'
                '请先通过受控流程作废或补建序列件'
            )

    @staticmethod
    def _update_order_transaction(oid, data, user_id, user_name, txn):
        repository = OrderService._repository()
        current_order = repository.find_by_id(oid, db=txn)
        if not current_order:
            raise ValueError('订单不存在')
        OrderLifecycle.validate_update(current_order, data)
        data = OrderService._product_identity_service().normalize_update(
            current_order,
            data,
            txn,
        )
        OrderService._validate_quantity_against_serial_items(
            oid, current_order, data, txn
        )

        route_changed, process_ids_changed = OrderService._process_sync_service().prepare_update(
            txn, oid, current_order['route_id'], data
        )
        structure_changed = route_changed or process_ids_changed
        quantity_changed = (
            'quantity' in data and data['quantity'] != current_order['quantity']
        )
        OrderService._record_update_remark(oid, data, user_id, user_name, txn)
        repository.update_form_fields(oid, data, db=txn)
        actual_order_no = repository.find_by_id(oid, db=txn)['order_no']
        OrderService._sync_updated_processes(
            txn, oid, data, route_changed, process_ids_changed
        )
        if structure_changed or quantity_changed or 'process_ids' in data:
            OrderService._completion_service().reconcile(
                oid,
                trigger='order_structure_updated',
                actor_id=user_id,
                db=txn,
            )
        return actual_order_no

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
        existing = OrderService._repository().find_status_by_id(oid)
        if not existing:
            raise ValueError('订单不存在')
        OrderLifecycle.validate_update(existing, data)
        OrderService._resolve_update_customer(data)

        with OrderService._unit_of_work().transaction() as txn:
            return OrderService._update_order_transaction(
                oid, data, user_id, user_name, txn
            )

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
        repository = OrderService._repository()
        existing = repository.find_including_deleted(oid)
        if not existing:
            raise ValueError('订单不存在')
        deleted = existing['deleted_at'] if existing else None
        if deleted:
            raise ValueError('订单已在回收站中')
        OrderLifecycle.validate_editable(existing)

        with OrderService._unit_of_work().transaction() as txn:
            repository.mark_deleted(oid, deleted_by=deleted_by, db=txn)

        return existing['order_no']

    # ============================================================
    # 工单记录查询
    # ============================================================

    @staticmethod
    def get_work_records(oid):
        """获取订单关联的报工/返工/报废记录。"""
        repository = OrderService._repository()
        order = repository.find_by_id(oid)
        if not order:
            raise ValueError('订单不存在')

        grouped_records = repository.get_work_records(oid)
        normal = grouped_records['work']
        scrap = grouped_records['scrap']
        rework = grouped_records['rework']
        all_records = normal + scrap + rework
        all_records.sort(key=lambda record: record.get('created_at', ''), reverse=True)

        return {
            'order_id': oid,
            'order_no': order['order_no'],
            'work_records': normal,
            'scrap_records': scrap,
            'rework_records': rework,
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
        """获取明确关联到订单的发货记录。"""
        repository = OrderService._repository()
        order = repository.find_by_id(oid)
        if not order:
            raise ValueError('订单不存在')
        shipments = repository.get_shipments(oid)
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
        return OrderService._repository().find_by_id(oid)

    @staticmethod
    def log_remark_history(oid, old_remark, new_remark, user_id, user_name, db=None):
        """记录备注变更历史。当 db 参数传入时复用已有事务连接。"""
        repository = OrderService._repository()
        if db is not None:
            repository.insert_remark_history(
                oid, old_remark, new_remark, user_id, user_name, db=db
            )
        else:
            with OrderService._unit_of_work().transaction() as txn:
                repository.insert_remark_history(
                    oid, old_remark, new_remark, user_id, user_name, db=txn
                )

    @staticmethod
    def soft_delete_order(oid, user_id):
        """软删除订单（适配器）"""
        return OrderService.delete_order(oid, deleted_by=user_id)

    @staticmethod
    def reopen_order(oid, reason, status='producing'):
        """重新打开已完成归档订单。"""
        repository = OrderService._repository()
        existing = repository.find_status_by_id(oid)
        if not existing:
            raise ValueError('订单不存在')
        reason, status = OrderLifecycle.normalize_reopen(existing, reason, status)

        with OrderService._unit_of_work().transaction() as txn:
            repository.reopen_completed(oid, status, db=txn)

        return {
            'id': oid,
            'order_no': existing['order_no'],
            'status': status,
            'reason': reason,
        }

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
        rows, total = OrderService._repository().list_trash(
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
        repository = OrderService._repository()
        existing = repository.find_including_deleted(oid)
        if not existing:
            raise ValueError('订单不存在')
        if not existing['deleted_at']:
            raise ValueError('订单不在回收站中')

        old_status = existing['pre_delete_status'] or 'pending'
        with OrderService._unit_of_work().transaction() as txn:
            repository.restore(oid, old_status, db=txn)
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
        repository = OrderService._repository()
        existing = repository.find_including_deleted(oid)
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
        with OrderService._unit_of_work().transaction() as txn:
            repository.detach_preserved_order_references(
                oid,
                existing['order_no'] or '',
                db=txn,
            )
            repository.purge_with_children(oid, _PURGE_CHILD_TABLES, db=txn)
        return existing['order_no'] or ""

    # ============================================================
    # Order Materials
    # ============================================================
    @staticmethod
    def list_order_materials(order_id):
        if not OrderService.get_order(order_id):
            raise NotFoundError('订单不存在')
        return [
            dict(row)
            for row in OrderService._material_repository().list_by_order(order_id)
        ]

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
        repository = OrderService._material_repository()
        with OrderService._unit_of_work().transaction() as txn:
            if repository.find_duplicate(order_id, material_id, process_id, db=txn):
                raise ConflictError('该物料已存在于订单物料配方中')
            new_id = repository.insert(
                order_id, material_id, quantity, process_id, 'manual', db=txn
            )
            row = repository.find_by_id(new_id, db=txn)
            return dict(row)

    @staticmethod
    def delete_order_material(order_id, item_id):
        material_repository = OrderService._material_repository()
        with OrderService._unit_of_work().transaction() as txn:
            order = OrderService._repository().find_by_id(order_id, db=txn)
            if order and order['status'] == 'completed':
                raise ValueError(OrderService.COMPLETED_READONLY_MESSAGE)
            if not material_repository.find_by_id_and_order(
                item_id, order_id, db=txn
            ):
                raise NotFoundError('订单物料记录不存在')
            material_repository.delete(item_id, db=txn)
