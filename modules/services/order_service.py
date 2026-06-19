from modules.constants import DEFAULT_PAGE_SIZE, MAX_PAGE_LIMIT
"""
qr-system — 订单管理 Service 层

从 routes/orders.py 提取全部业务逻辑。
"""
import json
from datetime import datetime, timedelta
from modules.services import BaseService
from modules.services.query_utils import paginate, build_sort_clause
from modules.repositories.order_repository import OrderRepository
from modules.repositories.product_bom_repository import ProductBomRepository
from modules.repositories.order_material_repository import OrderMaterialRepository

# Extracted constants — Brooks R4 fix



# ============================================================
# 订单号生成（模块级工具函数，含事务锁防竞态）
# ============================================================

def _generate_order_no(db):
    """自动生成订单号：前缀 + 2位顺序号。
    
    前缀从 system_settings.auto_order_no 读取，支持占位符 YYYY/YY/MM/DD。
    如果未配置，默认使用 YYMMDD 格式。
    调用方必须在外层管理事务。
    """
    from modules.db import get_setting
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
        """为订单分配工序（从路线或全局工序或指定ID列表）"""
        if route_id and not process_ids:
            route_items = db.execute(
                "SELECT pri.process_id, pri.seq_order, pri.required_audit "
                "FROM process_route_items pri WHERE pri.route_id = ? ORDER BY pri.seq_order",
                (route_id,)
            ).fetchall()
            for item in route_items:
                db.execute(
                    "INSERT INTO order_processes (order_id, process_id, seq_order, required_audit) "
                    "VALUES (?,?,?,?)",
                    (order_id, item['process_id'], item['seq_order'], item['required_audit'])
                )
        else:
            if not process_ids:
                procs = db.execute(
                    "SELECT id, seq_order FROM processes WHERE status = 'active' ORDER BY seq_order"
                ).fetchall()
                process_ids = [p['id'] for p in procs]
            for pid in process_ids:
                proc = db.execute("SELECT seq_order FROM processes WHERE id = ?", (pid,)).fetchone()
                if proc:
                    db.execute(
                        "INSERT INTO order_processes (order_id, process_id, seq_order) VALUES (?,?,?)",
                        (order_id, pid, proc['seq_order'])
                    )

    # ============================================================
    # 查询
    # ============================================================

    @staticmethod
    def list_orders(page=1, limit=DEFAULT_PAGE_SIZE, status='', keyword='', customer='',
                    data_scope_pids=None):
        """分页查询订单列表（含数据权限过滤）。"""
        db = BaseService.db()
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

        # 数据权限
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

        total = db.execute(
            f"SELECT COUNT(*) FROM orders o WHERE {where_sql}", params
        ).fetchone()[0]

        base_sql = f'''
            SELECT o.*, pr.name as route_name, c.name as customer_name
            FROM orders o
            LEFT JOIN process_routes pr ON o.route_id = pr.id
            LEFT JOIN customers c ON o.customer_id = c.id
            WHERE {where_sql}
            ORDER BY o.order_no DESC
        '''
        paginated_sql, all_params, size, offset = paginate(base_sql, params, page=page, page_size=limit)
        rows = db.execute(paginated_sql, all_params).fetchall()

        order_ids = [row['id'] for row in rows]
        all_procs = {}
        if order_ids:
            placeholders = ','.join('?' for _ in order_ids)
            procs = db.execute(f'''
                SELECT op.*, p.name as process_name
                FROM order_processes op JOIN processes p ON op.process_id = p.id
                WHERE op.order_id IN ({placeholders})
                ORDER BY op.order_id, op.seq_order
            ''', order_ids).fetchall()
            for p in procs:
                oid = p['order_id']
                all_procs.setdefault(oid, []).append(dict(p))

        result = []
        for row in rows:
            o = dict(row)
            try:
                o['extra_fields'] = json.loads(o.get('extra_fields') or '{}')
            except Exception:
                o['extra_fields'] = {}
            if not (o.get('product_code') or '').strip():
                o['product_code'] = o['extra_fields'].get('product_code', '') \
                    if isinstance(o['extra_fields'], dict) else ''
            o['processes'] = all_procs.get(o['id'], [])
            result.append(o)

        # 状态统计
        status_counts = db.execute(
            f"SELECT o.status, COUNT(*) as cnt FROM orders o WHERE {where_sql} GROUP BY o.status",
            params
        ).fetchall()
        counts = {r['status']: r['cnt'] for r in status_counts}

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
            db = BaseService.db()
            cust_row = db.execute('SELECT name FROM customers WHERE id = ?', (customer_id,)).fetchone()
            if cust_row:
                customer = cust_row['name']

        extra = {k: v for k, v in data.items()
                 if k not in ('order_no', 'customer', 'customer_id', 'product_name',
                              'quantity', 'plan_start', 'plan_end', 'deadline', 'remark',
                              'process_ids', 'route_id', 'production_line_id')}

        process_ids = data.get('process_ids', [])

        with BaseService.transaction() as txn:
            # 冲突检查 + 自动重试
            existing = txn.execute('SELECT id FROM orders WHERE order_no = ?', (order_no,)).fetchone()
            if existing:
                order_no = _generate_order_no(txn)
                existing2 = txn.execute('SELECT id FROM orders WHERE order_no = ?', (order_no,)).fetchone()
                if existing2:
                    raise ValueError('订单号冲突，请重试')

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

            # Auto-copy product BOM to order materials (inside transaction)
            # Resolve product_id from product_code if not already present
            product_id = data.get('product_id')
            if not product_id:
                pc = data.get('product_code', '')
                if pc:
                    prod_row = txn.execute('SELECT id FROM products WHERE product_code = ? AND deleted_at IS NULL', (pc,)).fetchone()
                    if prod_row:
                        product_id = prod_row['id']
            # BOM debug log removed for production
            if product_id:
                bom_rows = list(ProductBomRepository.list_by_product(product_id, db=txn))
            else:
                bom_rows = []
            # BOM debug log removed for production
            for bom in bom_rows:
                try:
                    OrderMaterialRepository.insert(
                        order_id,
                        bom['material_id'],
                        bom['quantity_per_unit'],
                        (bom['process_id'] if bom['process_id'] else None),
                        'auto',
                        db=txn
                    )
                except Exception as _e:
                    pass  # INSERT FAILED (ignored)

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
    def update_order(oid, data):
        """
        更新订单（含状态机校验）。

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
                cust = db.execute('SELECT name FROM customers WHERE id = ?',
                                  (data['customer_id'],)).fetchone()
                if cust:
                    data['customer'] = cust['name']

        sets = []
        params = []
        for field in ['order_no', 'customer', 'customer_id', 'product_name', 'product_code',
                       'quantity', 'plan_start', 'plan_end', 'deadline', 'remark', 'status', 'route_id', 'production_line_id']:
            if field in data:
                sets.append(f'{field} = ?')
                params.append(data[field] if data[field] is not None else None)

        with BaseService.transaction() as txn:
            if sets:
                sets.append('updated_at = datetime("now","localtime")')
                params.append(oid)
                txn.execute(f'UPDATE orders SET {", ".join(sets)} WHERE id = ?', params)

            if 'process_ids' in data:
                new_pids = [int(pid) for pid in data["process_ids"]]
                existing_procs = txn.execute(
                    'SELECT process_id FROM order_processes WHERE order_id = ?', (oid,)
                ).fetchall()
                existing_map = {r['process_id'] for r in existing_procs}
                remove_ids = [pid for pid in existing_map if pid not in new_pids]
                if remove_ids:
                    placeholders = ','.join('?' for _ in remove_ids)
                    txn.execute(
                        f'DELETE FROM order_processes WHERE order_id = ? AND process_id IN ({placeholders})',
                        [oid] + remove_ids
                    )
                for pid in new_pids:
                    if pid in existing_map:
                        continue
                    proc = txn.execute('SELECT seq_order FROM processes WHERE id = ?', (pid,)).fetchone()
                    if proc:
                        txn.execute(
                            'INSERT INTO order_processes (order_id, process_id, seq_order) VALUES (?,?,?)',
                            (oid, pid, proc['seq_order'])
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

        with BaseService.transaction() as txn:
            txn.execute(
                "UPDATE orders SET deleted_at = datetime('now','localtime'), deleted_by = ?, pre_delete_status = status, status = 'cancelled' WHERE id = ?",
                (deleted_by, oid)
            )

        return existing['order_no']

    # ============================================================
    # 工单记录查询
    # ============================================================

    @staticmethod
    def get_work_records(oid):
        """获取订单关联的报工/返工/报废记录。"""
        db = BaseService.db()
        order = OrderRepository.find_by_id(oid)
        if not order:
            raise ValueError('订单不存在')

        def _fetch(table, rec_type):
            return db.execute(f'''
                SELECT r.*, u.name as worker_name, p.name as process_name, ? as record_type
                FROM {table} r
                JOIN users u ON r.user_id = u.id
                JOIN processes p ON r.process_id = p.id
                WHERE r.order_id = ?
                ORDER BY r.created_at DESC
            ''', (rec_type, oid)).fetchall()

        normal = _fetch('work_records', 'normal')
        scrap = _fetch('scrap_records', 'scrap')
        rework = _fetch('rework_records', 'rework')

        all_records = [dict(r) for r in list(normal) + list(scrap) + list(rework)]
        all_records.sort(key=lambda x: x.get('created_at', ''), reverse=True)

        return {
            'order_id': oid,
            'order_no': order['order_no'],
            'records': all_records,
            'summary': {
                'normal_count': len(normal),
                'scrap_count': len(scrap),
                'rework_count': len(rework),
                'total_quantity': sum(r.get('quantity', 0) for r in normal)
            }
        }

    # ============================================================
    # 发货记录查询
    # ============================================================

    @staticmethod
    def get_shipments(oid):
        """获取订单关联产品的发货记录。"""
        db = BaseService.db()
        order = OrderRepository.find_by_id(oid)
        if not order:
            raise ValueError('订单不存在')

        shipments = db.execute('''
            SELECT DISTINCT s.*,
                   (SELECT COUNT(*) FROM shipment_items WHERE shipment_id = s.id) as item_count
            FROM shipments s
            JOIN shipment_items si ON si.shipment_id = s.id
            JOIN inventory i ON si.inventory_id = i.id
            WHERE i.product_model = ?
            ORDER BY s.created_at DESC
        ''', (order['product_code'],)).fetchall()

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
    def log_remark_history(oid, old_remark, new_remark, user_id, user_name):
        """记录备注变更历史"""
        db = BaseService.db()
        db.execute(
            "INSERT INTO order_remark_history (order_id, old_remark, new_remark, user_id, user_name) "
            "VALUES (?,?,?,?,?)",
            (oid, old_remark, new_remark, user_id, user_name)
        )
        db.commit()

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
        db = BaseService.db()
        order = OrderRepository.find_by_id(order_id)
        if not order:
            raise ValueError("订单不存在")
        items = db.execute(
            "SELECT * FROM product_items WHERE order_id = ? ORDER BY position_no", (order_id,)
        ).fetchall()
        processes = db.execute(
            "SELECT op.*, p.name as process_name FROM order_processes op "
            "JOIN processes p ON p.id = op.process_id WHERE op.order_id = ? ORDER BY op.seq_order",
            (order_id,)
        ).fetchall()
        work_records = db.execute(
            "SELECT wr.serial_no, wr.process_id, wr.status, wr.created_at "
            "FROM work_records wr WHERE wr.order_id = ? AND wr.serial_no IS NOT NULL AND wr.serial_no != ''",
            (order_id,)
        ).fetchall()
        record_map = {}
        for r in work_records:
            sn = r["serial_no"]
            if sn not in record_map:
                record_map[sn] = {}
            record_map[sn][r["process_id"]] = {"status": r["status"], "completed_at": r["created_at"]}
        return {
            "order": dict(order),
            "items": [dict(i) for i in items],
            "processes": [dict(p) for p in processes],
            "record_map": record_map,
        }

    @staticmethod
    def trash_orders(page=1, limit=DEFAULT_PAGE_SIZE):
        """分页查询回收站订单。"""
        db = BaseService.db()
        page = max(page, 1)
        limit = min(max(limit, 1), 200)

        total = db.execute(
            'SELECT COUNT(*) FROM orders WHERE deleted_at IS NOT NULL'
        ).fetchone()[0]

        rows = db.execute('''
            SELECT o.*, u.name as deleted_by_name
            FROM orders o
            LEFT JOIN users u ON o.deleted_by = u.id
            WHERE o.deleted_at IS NOT NULL
            ORDER BY o.deleted_at DESC
            LIMIT ? OFFSET ?
        ''', (limit, (page - 1) * limit)).fetchall()

        return {
            'orders': [dict(r) for r in rows],
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
            txn.execute(
                "UPDATE orders SET deleted_at = NULL, deleted_by = NULL, status = ? WHERE id = ?",
                (old_status, oid)
            )
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
        with BaseService.transaction() as txn:
            for tbl in ["order_attachments", "order_remark_history",
                        "order_materials", "order_processes", "product_items",
                        "work_records", "scrap_records", "rework_records",
                        "quality_inspections"]:
                txn.execute(f"DELETE FROM {tbl} WHERE order_id = ?", (oid,))
            txn.execute("DELETE FROM orders WHERE id = ?", (oid,))
        return existing['order_no'] or ""
