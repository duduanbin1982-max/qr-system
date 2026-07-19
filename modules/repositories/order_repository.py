"""
qr-system — OrderRepository（数据访问层）

Brooks R6 fix: 将所有 orders 表 SQL 集中到此文件。
Service 层只保留业务逻辑，不再直接写 SQL。
"""
from modules.repositories.context import resolve_db


class OrderRepository:
    """订单数据访问 — 所有 orders 表 CRUD 集中管理。"""

    # ============================================================
    # 查询
    # ============================================================

    @staticmethod
    def find_by_id(order_id, db=None, include_deleted=False):
        """按 ID 查询订单（含关联的客户名、路线名）。"""
        db = resolve_db(db)
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
        db = resolve_db(db)
        return db.execute(
            "SELECT id, status, deleted_at FROM orders WHERE id = ?", (order_id,)
        ).fetchone()

    @staticmethod
    def update_delivery_status(order_id, status, db=None):
        db = resolve_db(db)
        db.execute(
            "UPDATE orders SET delivery_status = ?, "
            "updated_at = datetime('now','localtime') WHERE id = ?",
            (status, order_id),
        )


    @staticmethod
    def find_by_order_no(order_no, db=None):
        db = resolve_db(db)
        return db.execute(
            'SELECT * FROM orders WHERE order_no = ? AND deleted_at IS NULL',
            (order_no,)
        ).fetchone()

    @staticmethod
    def exists_by_order_no(order_no, db=None):
        db = resolve_db(db)
        return db.execute(
            'SELECT id FROM orders WHERE order_no = ?', (order_no,)
        ).fetchone() is not None

    @staticmethod
    def find_latest_order_no_with_prefix(prefix, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT order_no FROM orders WHERE order_no LIKE ? ORDER BY id DESC LIMIT 1",
            (prefix + '%',)
        ).fetchone()

    @staticmethod
    def list_all(where_sql, params, page, limit, db=None, order_by='o.created_at DESC, o.id DESC'):
        """分页列表（where_sql 不含 WHERE 关键字，调用方负责拼接）。"""
        db = resolve_db(db)
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
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
        ''', params + [limit, offset]).fetchall()
        return rows, total

    @staticmethod
    def list_filtered(keyword="", customer="", status="", data_scope_pids=None,
                      archive="active", page=1, limit=20, db=None):
        base_where = ["o.deleted_at IS NULL"]
        base_params = []
        if keyword:
            base_where.append(
                "(o.order_no LIKE ? OR o.product_name LIKE ? OR "
                "o.product_code LIKE ? OR o.customer LIKE ?)"
            )
            base_params.extend([f"%{keyword}%"] * 4)
        if customer:
            base_where.append("o.customer LIKE ?")
            base_params.append(f"%{customer}%")
        if data_scope_pids is not None:
            if not data_scope_pids:
                return [], 0, {}, archive or "active"
            placeholders = ",".join("?" for _ in data_scope_pids)
            base_where.append(
                f"o.id IN (SELECT order_id FROM order_processes "
                f"WHERE process_id IN ({placeholders}))"
            )
            base_params.extend(data_scope_pids)

        where = list(base_where)
        params = list(base_params)
        archive = (archive or "active").strip().lower()
        if status:
            where.append("o.status = ?")
            params.append(status)
        elif archive == "completed":
            where.append("o.status = ?")
            params.append("completed")
        elif archive != "all":
            archive = "active"
            where.append("o.status != ?")
            params.append("completed")

        rows, total = OrderRepository.list_all(
            " AND ".join(where), params, page, limit, db=db, order_by="o.order_no DESC"
        )
        counts = {
            row["status"]: row["cnt"]
            for row in OrderRepository.count_by_status(
                " AND ".join(base_where), base_params, db=db
            )
        }
        return rows, total, counts, archive

    @staticmethod
    def list_completion_focus_orders(limit=80, db=None):
        db = resolve_db(db)
        return db.execute(
            """
            SELECT o.*, pr.name AS route_name, c.name AS customer_name
            FROM orders o
            LEFT JOIN process_routes pr ON o.route_id = pr.id
            LEFT JOIN customers c ON o.customer_id = c.id
            WHERE o.deleted_at IS NULL
              AND COALESCE(o.status, '') IN ('pending', 'producing', 'paused')
              AND COALESCE(o.quantity, 0) > 0
            ORDER BY o.created_at ASC, o.id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    @staticmethod
    def find_earlier_completion_focus_order(order_id, process_id, route_id=None, product_code="", db=None):
        db = resolve_db(db)
        OrderRepository.ensure_completion_focus_schema(db=db)
        current = db.execute(
            "SELECT id, created_at, route_id, product_code FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if not current:
            return None
        params = [process_id, order_id, current["created_at"] or "", current["created_at"] or "", order_id]
        scope_sql = ""
        if route_id:
            scope_sql = "AND o.route_id = ?"
            params.append(route_id)
        elif product_code:
            scope_sql = "AND COALESCE(o.product_code, '') = ?"
            params.append(product_code)
        return db.execute(
            f"""
            SELECT o.id, o.order_no, o.product_name, o.product_code, o.quantity,
                   o.completed, o.created_at, o.deadline, o.plan_end,
                   pr.name AS route_name, p.name AS process_name,
                   op.process_id, op.seq_order, COALESCE(op.completed, 0) AS process_completed,
                   MAX(COALESCE(o.quantity, 0) - COALESCE(op.completed, 0), 0) AS backlog
            FROM orders o
            JOIN order_processes op ON op.order_id = o.id AND op.process_id = ?
            JOIN processes p ON p.id = op.process_id
            LEFT JOIN process_routes pr ON pr.id = o.route_id
            WHERE o.deleted_at IS NULL
              AND COALESCE(o.status, '') IN ('pending', 'producing')
              AND o.id != ?
              AND (datetime(COALESCE(o.created_at, '1970-01-01 00:00:00')) < datetime(?)
                   OR (COALESCE(o.created_at, '') = ? AND o.id < ?))
              AND COALESCE(o.quantity, 0) > COALESCE(op.completed, 0)
              AND NOT EXISTS (
                  SELECT 1 FROM order_completion_focus_exceptions ex
                  WHERE ex.order_id = o.id
                    AND ex.status = 'active'
                    AND (COALESCE(ex.expires_at, '') = '' OR datetime(ex.expires_at) >= datetime('now','localtime'))
              )
              {scope_sql}
            ORDER BY o.created_at ASC, o.id ASC
            LIMIT 1
            """,
            params,
        ).fetchone()

    @staticmethod
    def ensure_completion_focus_schema(db=None):
        db = resolve_db(db)
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS order_completion_focus_exceptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                detail TEXT DEFAULT '',
                expires_at TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                created_by INTEGER,
                created_by_name TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now','localtime')),
                cancelled_by INTEGER,
                cancelled_at TEXT DEFAULT '',
                cancel_reason TEXT DEFAULT ''
            )
            """
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_focus_ex_order_status "
            "ON order_completion_focus_exceptions(order_id, status, expires_at)"
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS order_completion_focus_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                order_id INTEGER,
                process_id INTEGER,
                recommended_order_id INTEGER,
                recommended_order_no TEXT DEFAULT '',
                mode TEXT DEFAULT '',
                blocking INTEGER DEFAULT 0,
                bypass_allowed INTEGER DEFAULT 0,
                reason TEXT DEFAULT '',
                detail TEXT DEFAULT '',
                user_id INTEGER,
                user_name TEXT DEFAULT '',
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
            """
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_focus_events_order_created "
            "ON order_completion_focus_events(order_id, created_at DESC)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_focus_events_type_created "
            "ON order_completion_focus_events(event_type, created_at DESC)"
        )

    @staticmethod
    def list_active_completion_focus_exceptions(order_ids=None, db=None):
        db = resolve_db(db)
        OrderRepository.ensure_completion_focus_schema(db=db)
        params = []
        where = [
            "ex.status = 'active'",
            "(COALESCE(ex.expires_at, '') = '' OR datetime(ex.expires_at) >= datetime('now','localtime'))",
        ]
        if order_ids:
            placeholders = ",".join("?" for _ in order_ids)
            where.append(f"ex.order_id IN ({placeholders})")
            params.extend(order_ids)
        return db.execute(
            "SELECT ex.*, o.order_no, o.product_name "
            "FROM order_completion_focus_exceptions ex "
            "LEFT JOIN orders o ON o.id = ex.order_id "
            "WHERE " + " AND ".join(where) + " "
            "ORDER BY ex.created_at DESC, ex.id DESC",
            params,
        ).fetchall()

    @staticmethod
    def find_active_completion_focus_exception(order_id, db=None):
        db = resolve_db(db)
        OrderRepository.ensure_completion_focus_schema(db=db)
        return db.execute(
            """
            SELECT ex.*, o.order_no, o.product_name
            FROM order_completion_focus_exceptions ex
            LEFT JOIN orders o ON o.id = ex.order_id
            WHERE ex.order_id = ?
              AND ex.status = 'active'
              AND (COALESCE(ex.expires_at, '') = '' OR datetime(ex.expires_at) >= datetime('now','localtime'))
            ORDER BY ex.created_at DESC, ex.id DESC
            LIMIT 1
            """,
            (order_id,),
        ).fetchone()

    @staticmethod
    def insert_completion_focus_exception(order_id, reason, detail, expires_at, user_id, user_name, db=None):
        db = resolve_db(db)
        OrderRepository.ensure_completion_focus_schema(db=db)
        cur = db.execute(
            """
            INSERT INTO order_completion_focus_exceptions
                (order_id, reason, detail, expires_at, created_by, created_by_name)
            VALUES (?,?,?,?,?,?)
            """,
            (order_id, reason, detail, expires_at, user_id, user_name),
        )
        return cur.lastrowid

    @staticmethod
    def cancel_completion_focus_exception(exception_id, user_id, cancel_reason="", db=None):
        db = resolve_db(db)
        OrderRepository.ensure_completion_focus_schema(db=db)
        db.execute(
            """
            UPDATE order_completion_focus_exceptions
            SET status = 'cancelled',
                cancelled_by = ?,
                cancelled_at = datetime('now','localtime'),
                cancel_reason = ?
            WHERE id = ? AND status = 'active'
            """,
            (user_id, cancel_reason, exception_id),
        )

    @staticmethod
    def find_completion_focus_exception_by_id(exception_id, db=None):
        db = resolve_db(db)
        OrderRepository.ensure_completion_focus_schema(db=db)
        return db.execute(
            "SELECT * FROM order_completion_focus_exceptions WHERE id = ?",
            (exception_id,),
        ).fetchone()

    @staticmethod
    def insert_completion_focus_event(
        event_type,
        order_id=None,
        process_id=None,
        recommended_order_id=None,
        recommended_order_no="",
        mode="",
        blocking=False,
        bypass_allowed=False,
        reason="",
        detail="",
        user_id=None,
        user_name="",
        db=None,
    ):
        should_commit = db is None
        db = resolve_db(db)
        OrderRepository.ensure_completion_focus_schema(db=db)
        cursor = db.execute(
            """
            INSERT INTO order_completion_focus_events
                (event_type, order_id, process_id, recommended_order_id, recommended_order_no,
                 mode, blocking, bypass_allowed, reason, detail, user_id, user_name)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event_type,
                order_id,
                process_id,
                recommended_order_id,
                recommended_order_no or "",
                mode or "",
                1 if blocking else 0,
                1 if bypass_allowed else 0,
                reason or "",
                detail or "",
                user_id,
                user_name or "",
            ),
        )
        if should_commit:
            db.commit()
        return cursor.lastrowid

    @staticmethod
    def list_processes_for_orders(order_ids, db=None):
        db = resolve_db(db)
        if not order_ids:
            return []
        placeholders = ','.join('?' for _ in order_ids)
        sql = """
            SELECT op.*, p.name as process_name
            FROM order_processes op JOIN processes p ON op.process_id = p.id
            WHERE op.order_id IN ({})
            ORDER BY op.order_id, op.seq_order
        """.format(placeholders)
        return db.execute(sql, list(order_ids)).fetchall()

    @staticmethod
    def find_customer_name(customer_id, db=None):
        db = resolve_db(db)
        row = db.execute('SELECT name FROM customers WHERE id = ?', (customer_id,)).fetchone()
        return row['name'] if row else None

    @staticmethod
    def find_order_remark(order_id, db=None):
        db = resolve_db(db)
        return db.execute('SELECT remark FROM orders WHERE id = ?', (order_id,)).fetchone()

    @staticmethod
    def insert_remark_history(order_id, old_remark, new_remark, user_id, user_name, db=None):
        db = resolve_db(db)
        db.execute(
            "INSERT INTO order_remark_history (order_id, old_remark, new_remark, user_id, user_name) "
            "VALUES (?,?,?,?,?)",
            (order_id, old_remark, new_remark, user_id, user_name)
        )

    @staticmethod
    def update_fields(order_id, set_clauses, params, db=None):
        db = resolve_db(db)
        db.execute('UPDATE orders SET ' + ', '.join(set_clauses) + ' WHERE id = ?', list(params) + [order_id])

    @staticmethod
    def update_form_fields(order_id, changes, db=None):
        db = resolve_db(db)
        allowed = (
            "order_no", "customer", "customer_id", "product_name", "product_code",
            "quantity", "plan_start", "plan_end", "deadline", "remark", "status",
            "route_id", "production_line_id",
        )
        fields = [field for field in allowed if field in changes]
        if not fields:
            return 0
        params = [changes[field] if changes[field] is not None else None for field in fields]
        cursor = db.execute(
            "UPDATE orders SET "
            + ", ".join(f"{field} = ?" for field in fields)
            + ", updated_at = datetime('now','localtime') WHERE id = ?",
            params + [order_id],
        )
        return cursor.rowcount

    @staticmethod
    def mark_deleted(order_id, deleted_by=None, db=None):
        db = resolve_db(db)
        db.execute(
            "UPDATE orders SET deleted_at = datetime('now','localtime'), deleted_by = ?, "
            "pre_delete_status = status, status = 'cancelled' WHERE id = ?",
            (deleted_by, order_id)
        )

    @staticmethod
    def count_by_status(where_sql, params, db=None):
        """按状态统计订单数。"""
        db = resolve_db(db)
        return db.execute(
            f'SELECT o.status, COUNT(*) as cnt FROM orders o WHERE {where_sql} GROUP BY o.status',
            params
        ).fetchall()

    @staticmethod
    def list_trash(page, limit, db=None):
        db = resolve_db(db)
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
    def insert_from_order_form(data, db=None):
        db = resolve_db(db)
        cur = db.execute("""
            INSERT INTO orders (order_no, customer, customer_id, product_name, quantity,
                plan_start, plan_end, deadline, extra_fields, remark, route_id, status, product_code, production_line_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,'pending', ?, ?)
        """, (
            data["order_no"], data.get("customer", ""), data.get("customer_id"),
            data.get("product_name", ""), data.get("quantity", 0),
            data.get("plan_start", ""), data.get("plan_end", ""), data.get("deadline", ""),
            data.get("extra_fields", "{}"), data.get("remark", ""), data.get("route_id"),
            data.get("product_code", ""), data.get("production_line_id")
        ))
        return cur.lastrowid

    @staticmethod
    def insert(data, db=None):
        """插入新订单，返回 order_id。需要外层事务管理。"""
        db = resolve_db(db)
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
        db = resolve_db(db)
        params.append(order_id)
        db.execute(
            f'UPDATE orders SET {", ".join(set_clauses)} WHERE id = ?', params
        )

    @staticmethod
    def soft_delete(order_id, deleted_by, db=None):
        db = resolve_db(db)
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
        db = resolve_db(db)
        db.execute("UPDATE work_records SET status='approved' WHERE order_id=? AND status='deleted'", (order_id,))
        db.execute("UPDATE product_items SET status='active' WHERE order_id=? AND status='deleted'", (order_id,))

    @staticmethod
    def restore(order_id, prev_status, db=None):
        db = resolve_db(db)
        db.execute(
            'UPDATE orders SET deleted_at = NULL, deleted_by = NULL, status = ? WHERE id = ?',
            (prev_status, order_id)
        )

    @staticmethod
    def reopen_completed(order_id, status, db=None):
        db = resolve_db(db)
        db.execute(
            "UPDATE orders SET status = ?, updated_at = datetime('now','localtime') "
            "WHERE id = ? AND status = 'completed' AND deleted_at IS NULL",
            (status, order_id)
        )

    @staticmethod
    def purge(order_id, db=None):
        """硬删除订单及其所有关联数据。返回 order_no。"""
        db = resolve_db(db)
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

    @staticmethod
    def purge_with_children(order_id, child_tables, db=None):
        db = resolve_db(db)
        for table in child_tables:
            db.execute(f"DELETE FROM {table} WHERE order_id = ?", (order_id,))
        db.execute("DELETE FROM orders WHERE id = ?", (order_id,))

    # ============================================================
    # 关联数据
    # ============================================================

    @staticmethod
    def get_processes(order_id, db=None):
        db = resolve_db(db)
        return db.execute('''
            SELECT op.*, p.name as process_name
            FROM order_processes op
            JOIN processes p ON op.process_id = p.id
            WHERE op.order_id = ?
            ORDER BY op.seq_order
        ''', (order_id,)).fetchall()

    @staticmethod
    def assign_processes_from_route(order_id, route_id, db=None):
        db = resolve_db(db)
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
        db = resolve_db(db)
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
    def list_order_process_ids(order_id, db=None):
        db = resolve_db(db)
        return db.execute(
            'SELECT process_id FROM order_processes WHERE order_id = ?',
            (order_id,)
        ).fetchall()

    @staticmethod
    def delete_order_processes(order_id, process_ids, db=None):
        db = resolve_db(db)
        if not process_ids:
            return
        placeholders = ','.join('?' for _ in process_ids)
        db.execute(
            f'DELETE FROM order_processes WHERE order_id = ? AND process_id IN ({placeholders})',
            [order_id] + list(process_ids)
        )

    @staticmethod
    def find_process_seq_order(process_id, db=None):
        db = resolve_db(db)
        return db.execute(
            'SELECT seq_order FROM processes WHERE id = ?',
            (process_id,)
        ).fetchone()

    @staticmethod
    def insert_order_process(order_id, process_id, seq_order, required_audit=None, db=None):
        db = resolve_db(db)
        if required_audit is None:
            db.execute(
                'INSERT INTO order_processes (order_id, process_id, seq_order) VALUES (?,?,?)',
                (order_id, process_id, seq_order)
            )
            return
        db.execute(
            'INSERT INTO order_processes (order_id, process_id, seq_order, required_audit) VALUES (?,?,?,?)',
            (order_id, process_id, seq_order, required_audit)
        )

    @staticmethod
    def assign_all_active_processes(order_id, db=None):
        db = resolve_db(db)
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
        db = resolve_db(db)
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
        db = resolve_db(db)
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
        db = resolve_db(db)
        return db.execute('''
            SELECT DISTINCT s.*,
                   (SELECT COUNT(*) FROM shipment_items WHERE shipment_id = s.id) as item_count
            FROM shipments s
            WHERE s.order_id = ?
            ORDER BY s.created_at DESC
        ''', (order_id,)).fetchall()

    @staticmethod
    def get_shipments_by_product_code(product_code, db=None):
        db = resolve_db(db)
        return db.execute("""
            SELECT DISTINCT s.*,
                   (SELECT COUNT(*) FROM shipment_items WHERE shipment_id = s.id) as item_count
            FROM shipments s
            JOIN shipment_items si ON si.shipment_id = s.id
            JOIN inventory i ON si.inventory_id = i.id
            WHERE i.product_model = ?
            ORDER BY s.created_at DESC
        """, (product_code,)).fetchall()

    @staticmethod
    def get_workpiece_progress_rows(order_id, db=None):
        db = resolve_db(db)
        items = db.execute(
            "SELECT * FROM product_items WHERE order_id = ? ORDER BY position_no", (order_id,)
        ).fetchall()
        processes = db.execute(
            "SELECT op.*, p.name as process_name FROM order_processes op "
            "JOIN processes p ON p.id = op.process_id WHERE op.order_id = ? ORDER BY op.seq_order",
            (order_id,)
        ).fetchall()
        work_records = db.execute(
            "SELECT wr.serial_no, wr.process_id, wr.status, wr.created_at, u.name as worker_name "
            "FROM work_records wr "
            "LEFT JOIN users u ON u.id = wr.user_id "
            "WHERE wr.order_id = ? AND wr.serial_no IS NOT NULL AND wr.serial_no != '' "
            "AND COALESCE(wr.status, '') != 'deleted' "
            "ORDER BY wr.created_at ASC, wr.id ASC",
            (order_id,)
        ).fetchall()
        return items, processes, work_records

    @staticmethod
    def get_route_work_time_standards(route_id, db=None):
        db = resolve_db(db)
        if not route_id:
            return []
        return db.execute(
            "SELECT process_id, standard_minutes_per_unit, setup_minutes, difficulty_factor "
            "FROM work_time_standards "
            "WHERE route_id = ? AND status = 'active'",
            (route_id,)
        ).fetchall()

    # ============================================================
    # 订单号生成
    # ============================================================

    @staticmethod
    def generate_order_no(db=None):
        """生成 YYMMDD + 2位顺序号。需要外层事务管理。"""
        from datetime import datetime
        db = resolve_db(db)
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
