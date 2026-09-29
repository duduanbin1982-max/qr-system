"""Product-group inventory identity, thresholds, and allocation evidence."""

import json

from modules.migration_helpers import add_column_if_missing


INVENTORY_PRODUCT_PERMISSIONS = (
    "inventory:export",
    "inventory:inbound",
    "inventory:outbound",
    "inventory:allocate",
    "inventory:reserve",
    "inventory:adjust",
    "inventory:audit",
    "inventory:manage_threshold",
)


def _merge_inventory_permissions(db):
    for row in db.execute("SELECT id,permissions FROM roles ORDER BY id").fetchall():
        values = json.loads(row["permissions"] or "[]")
        if not isinstance(values, list) or "*" in values:
            continue
        additions = []
        if "inventory:view" in values:
            additions.extend(("inventory:export", "inventory:audit"))
        if "inventory:edit" in values:
            additions.extend(
                code for code in INVENTORY_PRODUCT_PERMISSIONS if code not in additions
            )
        merged = list(dict.fromkeys([*values, *additions]))
        if merged != values:
            db.execute(
                "UPDATE roles SET permissions=?,updated_at=datetime('now','localtime') "
                "WHERE id=?",
                (json.dumps(merged, ensure_ascii=False), row["id"]),
            )


def m096_inventory_product_views(db):
    add_column_if_missing(
        db,
        "inventory",
        "product_id",
        "INTEGER REFERENCES products(id) ON DELETE RESTRICT",
    )
    add_column_if_missing(
        db, "inventory", "product_code_snapshot", "TEXT NOT NULL DEFAULT ''"
    )
    add_column_if_missing(
        db, "inventory", "product_name_snapshot", "TEXT NOT NULL DEFAULT ''"
    )
    add_column_if_missing(
        db, "inventory", "frozen_quantity", "REAL NOT NULL DEFAULT 0"
    )
    add_column_if_missing(
        db,
        "inventory",
        "route_version_id_snapshot",
        "INTEGER REFERENCES process_route_versions(id) ON DELETE RESTRICT",
    )
    add_column_if_missing(
        db, "inventory", "quality_status", "TEXT NOT NULL DEFAULT 'qualified'"
    )

    db.execute(
        """
        UPDATE inventory
        SET product_id=(SELECT o.product_id FROM orders o WHERE o.id=inventory.order_id),
            product_code_snapshot=COALESCE(
                NULLIF((SELECT o.product_code FROM orders o WHERE o.id=inventory.order_id),''),
                product_model,''
            ),
            product_name_snapshot=COALESCE(NULLIF(product_name,''),'')
        WHERE product_id IS NULL
          AND order_id IS NOT NULL
          AND (SELECT o.product_id FROM orders o WHERE o.id=inventory.order_id) IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM product_code_aliases a
              WHERE a.product_code=inventory.product_model
                AND a.product_id<>(SELECT o.product_id FROM orders o WHERE o.id=inventory.order_id)
          )
        """
    )
    db.execute(
        """
        UPDATE inventory
        SET product_id=(
                SELECT a.product_id FROM product_code_aliases a
                WHERE a.product_code=inventory.product_model
            ),
            product_code_snapshot=COALESCE(NULLIF(product_model,''),''),
            product_name_snapshot=COALESCE(NULLIF(product_name,''),'')
        WHERE product_id IS NULL
          AND order_id IS NULL
          AND (SELECT COUNT(*) FROM product_code_aliases a
               WHERE a.product_code=inventory.product_model)=1
        """
    )

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS product_inventory_thresholds (
            product_id INTEGER PRIMARY KEY,
            safe_stock REAL NOT NULL DEFAULT 0 CHECK(safe_stock >= 0),
            warning_buffer REAL NOT NULL DEFAULT 0 CHECK(warning_buffer >= 0),
            updated_by INTEGER,
            updated_by_name TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT,
            FOREIGN KEY(updated_by) REFERENCES users(id) ON DELETE SET NULL
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_allocation_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            idempotency_key TEXT NOT NULL UNIQUE,
            request_digest TEXT NOT NULL,
            preview_digest TEXT NOT NULL,
            result_digest TEXT NOT NULL,
            product_id INTEGER NOT NULL,
            compatibility_key TEXT NOT NULL,
            mode TEXT NOT NULL CHECK(mode IN ('fifo','manual','reversal')),
            requested_quantity REAL NOT NULL CHECK(requested_quantity > 0),
            reason TEXT NOT NULL DEFAULT '',
            operator_id INTEGER,
            operator_name TEXT NOT NULL DEFAULT '',
            reversal_of_run_id INTEGER,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT,
            FOREIGN KEY(operator_id) REFERENCES users(id) ON DELETE SET NULL,
            FOREIGN KEY(reversal_of_run_id) REFERENCES inventory_allocation_runs(id) ON DELETE RESTRICT
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS inventory_allocation_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            sequence_no INTEGER NOT NULL,
            inventory_id INTEGER NOT NULL,
            source_order_id INTEGER,
            order_no_snapshot TEXT NOT NULL DEFAULT '',
            lot_no TEXT NOT NULL DEFAULT '',
            serial_no TEXT NOT NULL DEFAULT '',
            location_snapshot TEXT NOT NULL DEFAULT '',
            allocated_quantity REAL NOT NULL CHECK(allocated_quantity > 0),
            movement_id INTEGER NOT NULL,
            balance_before REAL NOT NULL,
            balance_after REAL NOT NULL,
            FOREIGN KEY(run_id) REFERENCES inventory_allocation_runs(id) ON DELETE RESTRICT,
            FOREIGN KEY(inventory_id) REFERENCES inventory(id) ON DELETE RESTRICT,
            FOREIGN KEY(source_order_id) REFERENCES orders(id) ON DELETE RESTRICT,
            FOREIGN KEY(movement_id) REFERENCES inventory_logs(id) ON DELETE RESTRICT,
            UNIQUE(run_id, sequence_no),
            UNIQUE(movement_id)
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_inventory_product_active "
        "ON inventory(product_id,deleted_at,quality_status)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_inventory_product_location "
        "ON inventory(product_id,location,deleted_at)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_inventory_allocation_product "
        "ON inventory_allocation_runs(product_id,created_at)"
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_inventory_allocation_one_reversal "
        "ON inventory_allocation_runs(reversal_of_run_id) "
        "WHERE reversal_of_run_id IS NOT NULL"
    )
    for table in ("inventory_allocation_runs", "inventory_allocation_items"):
        db.execute(f"DROP TRIGGER IF EXISTS prevent_{table}_update")
        db.execute(f"DROP TRIGGER IF EXISTS prevent_{table}_delete")
        db.execute(
            f"CREATE TRIGGER prevent_{table}_update BEFORE UPDATE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END"
        )
        db.execute(
            f"CREATE TRIGGER prevent_{table}_delete BEFORE DELETE ON {table} "
            f"BEGIN SELECT RAISE(ABORT, '{table} is immutable'); END"
        )
    _merge_inventory_permissions(db)


MIGRATIONS = [
    (
        96,
        "Add product-group inventory views and allocation evidence",
        m096_inventory_product_views,
    )
]
