"""Material planning migration helpers."""


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
