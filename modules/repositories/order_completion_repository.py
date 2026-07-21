"""Persistence queries for deriving and updating order completion state."""

from modules.repositories.context import resolve_db


class OrderCompletionRepository:
    """Read completion facts and persist the derived order state."""

    @staticmethod
    def find_snapshot(order_id, db=None):
        db = resolve_db(db)
        return db.execute(
            """
            SELECT o.id, o.order_no, o.status, o.quantity, o.completed,
                   o.qr_mode, o.deleted_at,
                   (SELECT COUNT(*)
                      FROM product_items pi
                     WHERE pi.order_id = o.id
                       AND pi.status != 'deleted') AS item_total,
                   (SELECT COUNT(*)
                      FROM product_items pi
                     WHERE pi.order_id = o.id
                       AND pi.status = 'completed') AS completed_items,
                   (SELECT COUNT(*)
                      FROM product_items pi
                     WHERE pi.order_id = o.id
                       AND pi.status NOT IN ('completed', 'deleted')) AS incomplete_items,
                   (SELECT COUNT(*)
                      FROM order_processes op
                     WHERE op.order_id = o.id) AS process_total,
                   (SELECT COUNT(*)
                      FROM order_processes op
                     WHERE op.order_id = o.id
                       AND COALESCE(op.completed, 0) >= COALESCE(o.quantity, 0)) AS completed_processes,
                   COALESCE((
                       SELECT op.completed
                         FROM order_processes op
                        WHERE op.order_id = o.id
                        ORDER BY op.seq_order DESC, op.id DESC
                        LIMIT 1
                   ), 0) AS final_process_completed,
                   (SELECT COUNT(*)
                      FROM work_records wr
                     WHERE wr.order_id = o.id
                       AND wr.status = 'pending') AS pending_approvals
              FROM orders o
             WHERE o.id = ?
            """,
            (order_id,),
        ).fetchone()

    @staticmethod
    def list_active_order_ids(db=None):
        db = resolve_db(db)
        return [
            row["id"]
            for row in db.execute(
                "SELECT id FROM orders "
                "WHERE deleted_at IS NULL AND status IN ('pending', 'producing') "
                "ORDER BY id"
            ).fetchall()
        ]

    @staticmethod
    def update_derived_state(order_id, completed, status, db=None):
        db = resolve_db(db)
        cursor = db.execute(
            "UPDATE orders SET completed = ?, status = ?, "
            "updated_at = datetime('now','localtime') "
            "WHERE id = ? AND deleted_at IS NULL "
            "AND status IN ('pending', 'producing')",
            (completed, status, order_id),
        )
        return cursor.rowcount
