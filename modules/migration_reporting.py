"""Reporting data-contract migrations."""

from modules.migration_helpers import add_column_if_missing


def m054_order_completed_at(db):
    """Persist the business completion timestamp independently of edits."""
    add_column_if_missing(db, "orders", "completed_at", "TEXT")
    db.execute(
        """
        UPDATE orders
           SET completed_at = COALESCE(
               (SELECT MAX(NULLIF(pi.completed_at, ''))
                  FROM product_items pi
                 WHERE pi.order_id = orders.id
                   AND pi.status = 'completed'),
               NULLIF(updated_at, ''),
               NULLIF(created_at, '')
           )
         WHERE status = 'completed'
           AND NULLIF(completed_at, '') IS NULL
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_status_completed_at "
        "ON orders(status, completed_at)"
    )
    db.execute("DROP TRIGGER IF EXISTS stamp_order_completed_at")
    db.execute(
        """
        CREATE TRIGGER stamp_order_completed_at
        AFTER UPDATE OF status ON orders
        WHEN NEW.status = 'completed'
         AND OLD.status != 'completed'
         AND NULLIF(NEW.completed_at, '') IS NULL
        BEGIN
            UPDATE orders
               SET completed_at = datetime('now','localtime')
             WHERE id = NEW.id;
        END
        """
    )
    db.execute("DROP TRIGGER IF EXISTS stamp_inserted_completed_order")
    db.execute(
        """
        CREATE TRIGGER stamp_inserted_completed_order
        AFTER INSERT ON orders
        WHEN NEW.status = 'completed'
         AND NULLIF(NEW.completed_at, '') IS NULL
        BEGIN
            UPDATE orders
               SET completed_at = datetime('now','localtime')
             WHERE id = NEW.id;
        END
        """
    )
    db.execute("DROP TRIGGER IF EXISTS clear_reopened_order_completed_at")
    db.execute(
        """
        CREATE TRIGGER clear_reopened_order_completed_at
        AFTER UPDATE OF status ON orders
        WHEN OLD.status = 'completed'
         AND NEW.status IN ('pending', 'producing', 'paused')
         AND NULLIF(NEW.completed_at, '') IS NOT NULL
        BEGIN
            UPDATE orders SET completed_at = NULL WHERE id = NEW.id;
        END
        """
    )


MIGRATIONS = [
    (54, "Persist stable order completion timestamps", m054_order_completed_at),
]
