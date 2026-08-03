"""Inventory ledger, reservation, batch, and stock-count migrations."""

from modules.migration_helpers import add_column_if_missing


def m051_inventory_ledger(db):
    # Dropping first also makes a manually retried migration idempotent.
    db.execute("DROP TRIGGER IF EXISTS prevent_inventory_delete")
    db.execute("DROP TRIGGER IF EXISTS prevent_inventory_log_update")
    db.execute("DROP TRIGGER IF EXISTS prevent_inventory_log_delete")

    add_column_if_missing(db, "inventory", "deleted_at", "TEXT DEFAULT NULL")

    log_columns = {
        "movement_no": "TEXT DEFAULT ''",
        "qty_delta": "REAL DEFAULT 0",
        "balance_before": "REAL",
        "balance_after": "REAL",
        "lot_no": "TEXT DEFAULT ''",
        "serial_no": "TEXT DEFAULT ''",
        "source_type": "TEXT DEFAULT ''",
        "source_id": "INTEGER",
        "idempotency_key": "TEXT DEFAULT ''",
        "reversal_of_id": "INTEGER REFERENCES inventory_logs(id) ON DELETE RESTRICT",
    }
    for column, definition in log_columns.items():
        add_column_if_missing(db, "inventory_logs", column, definition)

    db.execute(
        "UPDATE inventory_logs SET movement_no = 'LEGACY-' || printf('%010d', id) "
        "WHERE COALESCE(movement_no, '') = ''"
    )
    db.execute(
        """
        UPDATE inventory_logs
        SET qty_delta = CASE
            WHEN type IN ('in', 'return', 'opening_balance', 'count_gain') THEN ABS(quantity)
            WHEN type IN ('out', 'issue', 'count_loss') THEN -ABS(quantity)
            WHEN type = 'adjust' AND remark LIKE '%差额-%' THEN -ABS(quantity)
            WHEN type = 'adjust' THEN quantity
            ELSE 0
        END,
        source_type = CASE
            WHEN COALESCE(source_type, '') = '' THEN 'legacy'
            ELSE source_type
        END
        WHERE COALESCE(qty_delta, 0) = 0
        """
    )
    db.execute(
        """
        WITH running AS (
            SELECT id, qty_delta,
                   SUM(qty_delta) OVER (
                       PARTITION BY inventory_id
                       ORDER BY created_at, id
                       ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                   ) AS balance_after_calc
            FROM inventory_logs
        )
        UPDATE inventory_logs
        SET balance_after = (
                SELECT balance_after_calc FROM running WHERE running.id = inventory_logs.id
            ),
            balance_before = (
                SELECT balance_after_calc - qty_delta
                FROM running WHERE running.id = inventory_logs.id
            )
        WHERE balance_before IS NULL OR balance_after IS NULL
        """
    )
    db.execute(
        """
        INSERT INTO inventory_logs (
            inventory_id, type, quantity, movement_no, qty_delta,
            balance_before, balance_after, source_type, remark
        )
        SELECT i.id,
               CASE WHEN i.quantity - COALESCE(l.ledger_qty, 0) > 0
                    THEN 'count_gain' ELSE 'count_loss' END,
               ABS(i.quantity - COALESCE(l.ledger_qty, 0)),
               'MIGRATION-RECON-' || printf('%010d', i.id),
               i.quantity - COALESCE(l.ledger_qty, 0),
               COALESCE(l.ledger_qty, 0), i.quantity,
               'migration', 'Inventory ledger cutover reconciliation'
        FROM inventory i
        LEFT JOIN (
            SELECT inventory_id, SUM(qty_delta) AS ledger_qty
            FROM inventory_logs GROUP BY inventory_id
        ) l ON l.inventory_id = i.id
        WHERE ABS(i.quantity - COALESCE(l.ledger_qty, 0)) > 0.0000001
        """
    )
    # Empty movement numbers remain possible for legacy integrations during the
    # rollout, so uniqueness only applies once a real movement number exists.
    db.execute("DROP INDEX IF EXISTS idx_inventory_logs_movement_no")
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_inventory_logs_movement_no "
        "ON inventory_logs(movement_no) WHERE COALESCE(movement_no, '') != ''"
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_inventory_logs_idempotency "
        "ON inventory_logs(idempotency_key) WHERE COALESCE(idempotency_key, '') != ''"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_inventory_logs_lot "
        "ON inventory_logs(inventory_id, lot_no, created_at)"
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_inventory_logs_serial_inbound "
        "ON inventory_logs(serial_no) "
        "WHERE COALESCE(serial_no, '') != '' AND qty_delta > 0"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_inventory_active "
        "ON inventory(deleted_at, updated_at)"
    )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_count_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_no TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'counting',
            created_by INTEGER,
            created_by_name TEXT DEFAULT '',
            approved_by INTEGER,
            approved_by_name TEXT DEFAULT '',
            snapshot_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            submitted_at TEXT DEFAULT '',
            approved_at TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (approved_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_count_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            inventory_id INTEGER NOT NULL,
            product_model TEXT DEFAULT '',
            product_name TEXT DEFAULT '',
            book_quantity REAL NOT NULL DEFAULT 0,
            actual_quantity REAL,
            difference REAL,
            status TEXT NOT NULL DEFAULT 'pending',
            remark TEXT DEFAULT '',
            counted_by INTEGER,
            counted_by_name TEXT DEFAULT '',
            counted_at TEXT DEFAULT '',
            posted_movement_id INTEGER,
            FOREIGN KEY (task_id) REFERENCES inventory_count_tasks(id) ON DELETE CASCADE,
            FOREIGN KEY (inventory_id) REFERENCES inventory(id) ON DELETE RESTRICT,
            FOREIGN KEY (counted_by) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY (posted_movement_id) REFERENCES inventory_logs(id) ON DELETE RESTRICT,
            UNIQUE(task_id, inventory_id)
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_inventory_count_tasks_status "
        "ON inventory_count_tasks(status, created_at)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_inventory_count_items_task "
        "ON inventory_count_items(task_id, status)"
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_inventory_count_one_open "
        "ON inventory_count_tasks((1)) WHERE status IN ('counting', 'submitted')"
    )

    db.execute(
        """
        CREATE TRIGGER prevent_inventory_delete
        BEFORE DELETE ON inventory
        BEGIN
            SELECT RAISE(ABORT, 'inventory is auditable; archive it instead');
        END
        """
    )
    db.execute(
        """
        CREATE TRIGGER prevent_inventory_log_update
        BEFORE UPDATE ON inventory_logs
        BEGIN
            SELECT RAISE(ABORT, 'inventory ledger entries are immutable');
        END
        """
    )
    db.execute(
        """
        CREATE TRIGGER prevent_inventory_log_delete
        BEFORE DELETE ON inventory_logs
        BEGIN
            SELECT RAISE(ABORT, 'inventory ledger entries are immutable');
        END
        """
    )


MIGRATIONS = [
    (51, "Add auditable inventory ledger and stock-count workflow", m051_inventory_ledger),
]
