"""
qr-system — OrderRepository（数据访问层）

Brooks R6 fix: 将所有 orders 表 SQL 集中到此文件。
Service 层只保留业务逻辑，不再直接写 SQL。
"""
from modules.services import BaseService


class OrderRepository:
    """订单数据访问 — 所有 orders 表 CRUD 集中管理。"""

    # ============================================================
    # 查询
    # ============================================================

    @staticmethod
    def find_by_id(order_id, db=None, include_deleted=False):
        """按 ID 查询订单（含关联的客户名、路线名）。"""
        db = db or BaseService.db()
        return db.execute(f'''
            SELECT o.*, pr.name as route_name, c.name as customer_name
            FROM orders o
            LEFT JOIN process_routes pr ON o.route_id = pr.id
            LEFT JOIN customers c ON o.customer_id = c.id
            WHERE o.id = ?{" AND o.deleted_at IS NULL" if not include_deleted else ""}
        ''', (order_id,)).fetchone()
    @staticmethod
    def find_including_deleted(order_id, db=None):
        """查询订单（含软删除）。回收站操作专用。"""
        return OrderRepository.find_by_id(order_id, db=db, include_deleted=True)

    @staticmethod
    def find_status_by_id(order_id, db=None):
        """轻量查询 — 仅返回 id, status, deleted_at，用于状态校验。"""
        db = db or BaseService.db()
        return db.execute(
            "SELECT id, status, deleted_at FROM orders WHERE id = ?", (order_id,)
        ).fetchone()


    @staticmethod
    def find_by_order_no(order_no, db=None):
        db = db or BaseService.db()
        return db.execute(
            'SELECT * FROM orders WHERE order_no = ? AND deleted_at IS NULL',
            (order_no,)
        ).fetchone()

    @staticmethod
    def exists_by_order_no(order_no, db=None):
        db = db or BaseService.db()
        return db.execute(
            'SELECT id FROM orders WHERE order_no = ?', (order_no,)
        ).fetchone() is not None

    @staticmethod
    def list_all(where_sql, params, page, limit, db=None):
        """分页列表（where_sql 不含 WHERE 关键字，调用方负责拼接）。"""
        db = db or BaseService.db()
        total = db.execute(
            f'SELECT COUNT(*) FROM orders o WHERE {where_sql}', params
        ).fetchone()[0]
        offset = (page - 1) * limit
        rows = db.execute(f'''
            SELECT o.*, pr.name as route_name, c.name as customer_name
            FROM orders o
            LEFT JOIN process_routes pr ON o.route_id = pr.id
            LEFT JOIN customers c ON o.customer_id = c.id
            WHERE {where_sql}
            ORDER BY o.created_at DESC, o.id DESC
            LIMIT ? OFFSET ?
        ''', params + [limit, offset]).fetchall()
        return rows, total

    @staticmethod
    def count_by_status(where_sql, params, db=None):
        """按状态统计订单数。"""
        db = db or BaseService.db()
        return db.execute(
            f'SELECT o.status, COUNT(*) as cnt FROM orders o WHERE {where_sql} GROUP BY o.status',
            params
        ).fetchall()

    @staticmethod
    def list_trash(page, limit, db=None):
        db = db or BaseService.db()
        total = db.execute(
            'SELECT COUNT(*) FROM orders WHERE deleted_at IS NOT NULL'
        ).fetchone()[0]
        offset = (page - 1) * limit
        rows = db.execute('''
            SELECT o.*, u.name as deleted_by_name
            FROM orders o
            LEFT JOIN users u ON o.deleted_by = u.id
            WHERE o.deleted_at IS NOT NULL
            ORDER BY o.deleted_at DESC
            LIMIT ? OFFSET ?
        ''', (limit, offset)).fetchall()
        return rows, total

    # ============================================================
    # 写操作
    # ============================================================

    @staticmethod
    def insert(data, db=None):
        """插入新订单，返回 order_id。需要外层事务管理。"""
        db = db or BaseService.db()
        cur = db.execute('''
            INSERT INTO orders (order_no, customer, customer_id, product_name,
                product_code, model, spec, style, upper_opening, plate_thickness,
                category, quantity, plan_start, plan_end, deadline, remark, route_id, status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'pending')
        ''', (
            data['order_no'],
            data.get('customer', ''),
            data.get('customer_id'),
            data.get('product_name', ''),
            data.get('product_code', ''),
            data.get('model', ''),
            data.get('spec', ''),
            data.get('style', ''),
            data.get('upper_opening', ''),
            data.get('plate_thickness', ''),
            data.get('category', ''),
            data.get('quantity', 1),
            data.get('plan_start', ''),
            data.get('plan_end', ''),
            data.get('deadline', ''),
            data.get('remark', ''),
            data.get('route_id'),
        ))
        return cur.lastrowid

    @staticmethod
    def update(order_id, set_clauses, params, db=None):
        """UPDATE orders SET ... WHERE id = ?。调用方自行构建 set_clauses 和 params。"""
        db = db or BaseService.db()
        params.append(order_id)
        db.execute(
            f'UPDATE orders SET {", ".join(set_clauses)} WHERE id = ?', params
        )

    @staticmethod
    def soft_delete(order_id, deleted_by, db=None):
        db = db or BaseService.db()
        now = db.execute("SELECT datetime('now','localtime')").fetchone()[0]
        db.execute(
            "UPDATE orders SET deleted_at = ?, deleted_by = ?, status = 'cancelled' WHERE id = ?",
            (now, deleted_by, order_id)
        )
        # Cascade soft-delete to related records
        db.execute("UPDATE work_records SET status='deleted' WHERE order_id=? AND status!='deleted'", (order_id,))
        db.execute("UPDATE product_items SET status='deleted' WHERE order_id=? AND status!='deleted'", (order_id,))
        db.execute("DELETE FROM order_processes WHERE order_id=?", (order_id,))
        db.execute("UPDATE inventory SET quantity=0, remark='订单已删除' WHERE order_id=?", (order_id,))
        # Also restore cascade
    @staticmethod
    def soft_restore(order_id, db=None):
        db = db or BaseService.db()
        db.execute("UPDATE work_records SET status='approved' WHERE order_id=? AND status='deleted'", (order_id,))
        db.execute("UPDATE product_items SET status='active' WHERE order_id=? AND status='deleted'", (order_id,))

    @staticmethod
    def restore(order_id, prev_status, db=None):
        db = db or BaseService.db()
        db.execute(
            'UPDATE orders SET deleted_at = NULL, deleted_by = NULL, status = ? WHERE id = ?',
            (prev_status, order_id)
        )

    @staticmethod
    def purge(order_id, db=None):
        """硬删除订单及其所有关联数据。返回 order_no。"""
        db = db or BaseService.db()
        order = db.execute(
            'SELECT id, order_no FROM orders WHERE id = ?', (order_id,)
        ).fetchone()
        if not order:
            raise ValueError('订单不存在')
        for tbl in ['order_attachments', 'work_records', 'scrap_records',
                     'rework_records', 'quality_inspections', 'order_processes',
                     'material_consumptions']:
            db.execute(f'DELETE FROM {tbl} WHERE order_id = ?', (order_id,))
        db.execute('DELETE FROM orders WHERE id = ?', (order_id,))
        return order['order_no']

    # ============================================================
    # 关联数据
    # ============================================================

    @staticmethod
    def get_processes(order_id, db=None):
        db = db or BaseService.db()
        return db.execute('''
            SELECT op.*, p.name as process_name
            FROM order_processes op
            JOIN processes p ON op.process_id = p.id
            WHERE op.order_id = ?
            ORDER BY op.seq_order
        ''', (order_id,)).fetchall()

    @staticmethod
    def assign_processes_from_route(order_id, route_id, db=None):
        db = db or BaseService.db()
        route_items = db.execute(
            'SELECT process_id, seq_order, required_audit '
            'FROM process_route_items WHERE route_id = ? ORDER BY seq_order',
            (route_id,)
        ).fetchall()
        for item in route_items:
            db.execute(
                'INSERT INTO order_processes (order_id, process_id, seq_order, required_audit) '
                'VALUES (?,?,?,?)',
                (order_id, item['process_id'], item['seq_order'], item['required_audit'])
            )
        return len(route_items)

    @staticmethod
    def assign_processes_from_list(order_id, process_ids, db=None):
        db = db or BaseService.db()
        count = 0
        for pid in process_ids:
            proc = db.execute(
                'SELECT seq_order FROM processes WHERE id = ?', (pid,)
            ).fetchone()
            if proc:
                db.execute(
                    'INSERT INTO order_processes (order_id, process_id, seq_order) VALUES (?,?,?)',
                    (order_id, pid, proc['seq_order'])
                )
                count += 1
        return count

    @staticmethod
    def assign_all_active_processes(order_id, db=None):
        db = db or BaseService.db()
        procs = db.execute(
            "SELECT id, seq_order FROM processes WHERE status = 'active' ORDER BY seq_order"
        ).fetchall()
        count = 0
        for p in procs:
            db.execute(
                'INSERT INTO order_processes (order_id, process_id, seq_order) VALUES (?,?,?)',
                (order_id, p['id'], p['seq_order'])
            )
            count += 1
        return count

    @staticmethod
    def remove_processes_except(order_id, keep_ids, db=None):
        """删除不在 keep_ids 中的工序关联。"""
        db = db or BaseService.db()
        if not keep_ids:
            db.execute('DELETE FROM order_processes WHERE order_id = ?', (order_id,))
            return
        placeholders = ','.join('?' for _ in keep_ids)
        db.execute(
            f'DELETE FROM order_processes WHERE order_id = ? AND process_id IN ({placeholders})',
            [order_id] + keep_ids
        )

    @staticmethod
    def get_work_records(order_id, db=None):
        """获取订单的所有报工/报废/返工记录。"""
        db = db or BaseService.db()
        result = {'work': [], 'scrap': [], 'rework': []}
        for table, key in [('work_records', 'work'), ('scrap_records', 'scrap'), ('rework_records', 'rework')]:
            result[key] = [dict(r) for r in db.execute(f'''
                SELECT r.*, u.name as worker_name, p.name as process_name, ? as record_type
                FROM {table} r
                LEFT JOIN users u ON r.user_id = u.id
                LEFT JOIN processes p ON r.process_id = p.id
                WHERE r.order_id = ?
                ORDER BY r.created_at DESC
            ''', (key, order_id)).fetchall()]
        return result

    @staticmethod
    def get_shipments(order_id, db=None):
        db = db or BaseService.db()
        return db.execute('''
            SELECT DISTINCT s.*,
                   (SELECT COUNT(*) FROM shipment_items WHERE shipment_id = s.id) as item_count
            FROM shipments s
            WHERE s.order_id = ?
            ORDER BY s.created_at DESC
        ''', (order_id,)).fetchall()

    # ============================================================
    # 订单号生成
    # ============================================================

    @staticmethod
    def generate_order_no(db=None):
        """生成 YYMMDD + 2位顺序号。需要外层事务管理。"""
        from datetime import datetime
        db = db or BaseService.db()
        today = datetime.now()
        prefix = today.strftime('%y%m%d')
        row = db.execute(
            "SELECT order_no FROM orders WHERE order_no LIKE ? AND LENGTH(order_no) >= 8 "
            "ORDER BY id DESC LIMIT 1", (prefix + '%',)
        ).fetchone()
        if row:
            try:
                seq = int(row['order_no'][6:]) + 1
            except ValueError:
                seq = 1
        else:
            seq = 1
        for _ in range(100):
            order_no = prefix + str(seq).zfill(2)
            if not db.execute('SELECT id FROM orders WHERE order_no = ?', (order_no,)).fetchone():
                return order_no
            seq += 1
        raise RuntimeError(f'订单号生成失败：日期{prefix}下所有序号已用尽')
