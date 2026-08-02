"""Persistence for completion-focus board, exceptions, and scan events."""

from modules.repositories.context import resolve_db


class CompletionFocusRepository:
    @staticmethod
    def list_orders(limit=80, data_scope_pids=None, db=None):
        db = resolve_db(db)
        where = [
            "o.deleted_at IS NULL",
            "COALESCE(o.status, '') IN ('pending', 'producing', 'paused')",
            "COALESCE(o.quantity, 0) > 0",
        ]
        params = []
        if data_scope_pids is not None:
            if not data_scope_pids:
                return []
            placeholders = ",".join("?" for _ in data_scope_pids)
            where.append(
                "EXISTS (SELECT 1 FROM order_processes scope_op "
                f"WHERE scope_op.order_id = o.id AND scope_op.process_id IN ({placeholders}))"
            )
            params.extend(data_scope_pids)
        return db.execute(
            """
            SELECT o.*, pr.name AS route_name, c.name AS customer_name
            FROM orders o
            LEFT JOIN process_routes pr ON o.route_id = pr.id
            LEFT JOIN customers c ON o.customer_id = c.id
            WHERE """ + " AND ".join(where) + """
            ORDER BY o.created_at ASC, o.id ASC
            LIMIT ?
            """,
            params + [limit],
        ).fetchall()

    @staticmethod
    def find_earlier_order(order_id, process_id, route_id=None, product_code="", db=None):
        db = resolve_db(db)
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
            scope_sql = (
                "AND (COALESCE(o.product_code, '') = ? OR COALESCE(o.product_id, "
                "(SELECT a.product_id FROM product_code_aliases a "
                "WHERE a.product_code = o.product_code)) = "
                "(SELECT a.product_id FROM product_code_aliases a WHERE a.product_code = ?))"
            )
            params.extend([product_code, product_code])
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
    def list_active_exceptions(order_ids=None, db=None):
        db = resolve_db(db)
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
    def find_active_exception(order_id, db=None):
        db = resolve_db(db)
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
    def insert_exception(order_id, reason, detail, expires_at, user_id, user_name, db=None):
        db = resolve_db(db)
        cursor = db.execute(
            """
            INSERT INTO order_completion_focus_exceptions
                (order_id, reason, detail, expires_at, created_by, created_by_name)
            VALUES (?,?,?,?,?,?)
            """,
            (order_id, reason, detail, expires_at, user_id, user_name),
        )
        return cursor.lastrowid

    @staticmethod
    def cancel_exception(exception_id, user_id, cancel_reason="", db=None):
        db = resolve_db(db)
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
    def find_exception_by_id(exception_id, db=None):
        db = resolve_db(db)
        return db.execute(
            "SELECT * FROM order_completion_focus_exceptions WHERE id = ?",
            (exception_id,),
        ).fetchone()

    @staticmethod
    def insert_event(
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
