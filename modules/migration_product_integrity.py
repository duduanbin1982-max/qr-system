"""Product-management integrity and stable route-root migration."""

from modules.migration_helpers import (
    MigrationInvariantError,
    add_column_if_missing,
    table_exists,
)


def _collect_product_bom_issues(db):
    issues = []
    invalid = db.execute(
        "SELECT id, quantity_per_unit FROM product_bom "
        "WHERE quantity_per_unit IS NULL OR quantity_per_unit <= 0 "
        "OR quantity_per_unit > 1e308 ORDER BY id LIMIT 20"
    ).fetchall()
    issues.extend(
        f"invalid_quantity:{row[0]}:{row[1]}" for row in invalid
    )

    duplicates = db.execute(
        "SELECT product_id, material_id, COALESCE(process_id, -1), COUNT(*) "
        "FROM product_bom GROUP BY product_id, material_id, COALESCE(process_id, -1) "
        "HAVING COUNT(*) > 1 ORDER BY product_id, material_id LIMIT 20"
    ).fetchall()
    issues.extend(
        f"duplicate:{row[0]}:{row[1]}:{row[2]}:{row[3]}" for row in duplicates
    )

    orphan = db.execute(
        "SELECT pb.id FROM product_bom pb "
        "LEFT JOIN products p ON p.id=pb.product_id "
        "LEFT JOIN materials m ON m.id=pb.material_id "
        "LEFT JOIN processes process ON process.id=pb.process_id "
        "WHERE p.id IS NULL OR m.id IS NULL "
        "OR (pb.process_id IS NOT NULL AND process.id IS NULL) "
        "ORDER BY pb.id LIMIT 20"
    ).fetchall()
    issues.extend(f"orphan_reference:{row[0]}" for row in orphan)
    return issues


def _rebuild_product_bom(db):
    issues = _collect_product_bom_issues(db)
    if issues:
        raise MigrationInvariantError(
            "Migration v64 blocked by product BOM issue(s): " + ", ".join(issues)
        )

    db.execute("DROP TABLE IF EXISTS product_bom_v064_new")
    db.execute(
        "CREATE TABLE product_bom_v064_new ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "product_id INTEGER NOT NULL, "
        "material_id INTEGER NOT NULL, "
        "quantity_per_unit REAL NOT NULL DEFAULT 1 "
        "CHECK (quantity_per_unit > 0 AND quantity_per_unit <= 1e308), "
        "process_id INTEGER DEFAULT NULL, "
        "created_at TEXT DEFAULT (datetime('now','localtime')), "
        "FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE, "
        "FOREIGN KEY (material_id) REFERENCES materials(id), "
        "FOREIGN KEY (process_id) REFERENCES processes(id)"
        ")"
    )
    db.execute(
        "INSERT INTO product_bom_v064_new "
        "(id, product_id, material_id, quantity_per_unit, process_id, created_at) "
        "SELECT id, product_id, material_id, quantity_per_unit, process_id, created_at "
        "FROM product_bom ORDER BY id"
    )
    db.execute("DROP TABLE product_bom")
    db.execute("ALTER TABLE product_bom_v064_new RENAME TO product_bom")
    db.execute(
        "CREATE INDEX idx_product_bom_product ON product_bom(product_id)"
    )
    db.execute(
        "CREATE UNIQUE INDEX uq_product_bom_identity "
        "ON product_bom(product_id, material_id, COALESCE(process_id, -1))"
    )


def _add_stable_product_route_root(db):
    add_column_if_missing(
        db,
        "products",
        "process_route_id",
        "INTEGER REFERENCES process_routes(id)",
    )
    invalid = db.execute(
        "SELECT p.id, p.route_id FROM products p "
        "LEFT JOIN process_routes route ON route.id=p.route_id "
        "WHERE p.route_id IS NOT NULL AND route.id IS NULL ORDER BY p.id LIMIT 20"
    ).fetchall()
    if invalid:
        sample = ", ".join(f"{row[0]}:{row[1]}" for row in invalid)
        raise MigrationInvariantError(
            "Migration v64 blocked by invalid product route root(s): " + sample
        )
    db.execute(
        "UPDATE products SET process_route_id=route_id "
        "WHERE process_route_id IS NULL AND route_id IS NOT NULL"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_products_process_route "
        "ON products(process_route_id)"
    )


def m064_harden_product_integrity(db):
    """Protect BOM invariants and name the product's stable route-root binding."""
    if table_exists(db, "product_bom"):
        issues = _collect_product_bom_issues(db)
        if issues:
            raise MigrationInvariantError(
                "Migration v64 blocked by product BOM issue(s): " + ", ".join(issues)
            )
    for trigger in (
        "prevent_referenced_process_delete",
        "prevent_referenced_route_delete",
        "prevent_referenced_process_version_delete",
        "prevent_referenced_route_version_delete",
    ):
        db.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    if table_exists(db, "product_bom"):
        _rebuild_product_bom(db)
    if table_exists(db, "products"):
        _add_stable_product_route_root(db)

    from modules.migration_process_management import (
        rebuild_master_data_reference_guards,
    )

    rebuild_master_data_reference_guards(db)


MIGRATIONS = [
    (64, "Harden product BOM and stable route-root integrity", m064_harden_product_integrity),
]
