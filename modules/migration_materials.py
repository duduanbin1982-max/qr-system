"""Material planning and stock-ledger migrations."""

from modules.migration_helpers import add_column_if_missing


def ensure_material_planning_tables(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS product_bom ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "product_id INTEGER NOT NULL, "
        "material_id INTEGER NOT NULL, "
        "quantity_per_unit REAL DEFAULT 1, "
        "process_id INTEGER DEFAULT NULL, "
        "created_at TEXT DEFAULT (datetime('now','localtime')), "
        "FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE, "
        "FOREIGN KEY (material_id) REFERENCES materials(id), "
        "FOREIGN KEY (process_id) REFERENCES processes(id), "
        "UNIQUE(product_id, material_id, process_id)"
        ")"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS order_materials ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "order_id INTEGER NOT NULL, "
        "material_id INTEGER NOT NULL, "
        "quantity_per_unit REAL DEFAULT 1, "
        "process_id INTEGER DEFAULT NULL, "
        "source TEXT DEFAULT 'auto', "
        "created_at TEXT DEFAULT (datetime('now','localtime')), "
        "FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE, "
        "FOREIGN KEY (material_id) REFERENCES materials(id), "
        "FOREIGN KEY (process_id) REFERENCES processes(id)"
        ")"
    )
    db.execute("CREATE INDEX IF NOT EXISTS idx_product_bom_product ON product_bom(product_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_order_materials_order ON order_materials(order_id)")


def m042_material_stock_ledger(db):
    """Establish an immutable ledger baseline for all future stock changes."""
    add_column_if_missing(db, "material_logs", "balance_before", "REAL")
    add_column_if_missing(db, "material_logs", "balance_after", "REAL")
    add_column_if_missing(db, "material_logs", "source_type", "TEXT DEFAULT 'legacy'")
    add_column_if_missing(db, "material_logs", "source_id", "INTEGER")
    add_column_if_missing(db, "material_logs", "reversal_of_log_id", "INTEGER")

    add_column_if_missing(db, "material_consumptions", "status", "TEXT DEFAULT 'active'")
    add_column_if_missing(db, "material_consumptions", "reversed_at", "TEXT DEFAULT ''")
    add_column_if_missing(db, "material_consumptions", "reversed_by", "INTEGER")
    add_column_if_missing(db, "material_consumptions", "reversal_reason", "TEXT DEFAULT ''")
    add_column_if_missing(db, "material_consumptions", "reversal_log_id", "INTEGER")

    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_material_logs_source "
        "ON material_logs(source_type, source_id)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_material_consumptions_status "
        "ON material_consumptions(status, created_at)"
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_material_legacy_baseline "
        "ON material_logs(material_id, source_type) "
        "WHERE source_type = 'legacy_baseline'"
    )
    db.execute(
        "INSERT OR IGNORE INTO material_logs ("
        "material_id, type, quantity, remark, operator_name, "
        "balance_before, balance_after, source_type"
        ") SELECT id, 'baseline', COALESCE(quantity, 0), "
        "'历史库存余额基线', '系统迁移', COALESCE(quantity, 0), "
        "COALESCE(quantity, 0), 'legacy_baseline' FROM materials"
    )


MIGRATIONS = [
    (42, "Establish material stock ledger baseline", m042_material_stock_ledger),
]
