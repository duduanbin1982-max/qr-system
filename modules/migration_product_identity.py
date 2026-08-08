"""Stable order-to-product identity migration."""

from modules.migration_helpers import add_column_if_missing


def m050_stable_order_product_identity(db):
    """Link orders to products by ID and retain every known product code."""
    add_column_if_missing(
        db,
        "orders",
        "product_id",
        "INTEGER REFERENCES products(id) ON DELETE RESTRICT",
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS product_code_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            product_code TEXT NOT NULL UNIQUE,
            source TEXT NOT NULL DEFAULT 'current',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_product_code_aliases_product "
        "ON product_code_aliases(product_id)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_product_id ON orders(product_id)"
    )

    conflicts = db.execute(
        """
        SELECT a.product_code, a.product_id AS alias_product_id, p.id AS current_product_id
        FROM product_code_aliases a
        JOIN products p ON p.product_code = a.product_code
        WHERE a.product_id != p.id
        LIMIT 1
        """
    ).fetchone()
    if conflicts:
        raise RuntimeError(
            "product code alias conflict: "
            f"{conflicts['product_code']} belongs to product "
            f"{conflicts['alias_product_id']}, not {conflicts['current_product_id']}"
        )

    db.execute(
        """
        INSERT INTO product_code_aliases (product_id, product_code, source)
        SELECT id, product_code, 'current'
        FROM products
        WHERE TRIM(COALESCE(product_code, '')) != ''
        ON CONFLICT(product_code) DO NOTHING
        """
    )
    db.execute(
        """
        UPDATE orders
        SET product_id = (
            SELECT a.product_id
            FROM product_code_aliases a
            WHERE a.product_code = orders.product_code
        )
        WHERE product_id IS NULL
          AND TRIM(COALESCE(product_code, '')) != ''
          AND EXISTS (
              SELECT 1 FROM product_code_aliases a
              WHERE a.product_code = orders.product_code
          )
        """
    )
    db.execute(
        """
        UPDATE orders
        SET product_name = (
            SELECT p.product_name FROM products p WHERE p.id = orders.product_id
        )
        WHERE product_id IS NOT NULL
          AND TRIM(COALESCE(product_name, '')) = ''
        """
    )

    db.execute("DROP VIEW IF EXISTS order_product_links")
    db.execute(
        """
        CREATE VIEW order_product_links AS
        SELECT
            o.id AS order_id,
            COALESCE(o.product_id, a.product_id, current_product.id) AS product_id
        FROM orders o
        LEFT JOIN product_code_aliases a
          ON o.product_id IS NULL
         AND a.product_code = o.product_code
        LEFT JOIN products current_product
          ON o.product_id IS NULL
         AND current_product.product_code = o.product_code
        """
    )

    db.execute("DROP TRIGGER IF EXISTS product_code_alias_before_insert")
    db.execute(
        """
        CREATE TRIGGER product_code_alias_before_insert
        BEFORE INSERT ON products
        WHEN TRIM(COALESCE(NEW.product_code, '')) != ''
        BEGIN
            SELECT CASE WHEN EXISTS (
                SELECT 1 FROM product_code_aliases a
                WHERE a.product_code = NEW.product_code
            ) THEN RAISE(ABORT, 'product code is a historical alias') END;
        END
        """
    )
    db.execute("DROP TRIGGER IF EXISTS product_code_alias_after_insert")
    db.execute(
        """
        CREATE TRIGGER product_code_alias_after_insert
        AFTER INSERT ON products
        WHEN TRIM(COALESCE(NEW.product_code, '')) != ''
        BEGIN
            INSERT INTO product_code_aliases (product_id, product_code, source)
            VALUES (NEW.id, NEW.product_code, 'current')
            ON CONFLICT(product_code) DO NOTHING;
        END
        """
    )
    db.execute("DROP TRIGGER IF EXISTS product_code_alias_before_update")
    db.execute(
        """
        CREATE TRIGGER product_code_alias_before_update
        BEFORE UPDATE OF product_code ON products
        WHEN COALESCE(OLD.product_code, '') != COALESCE(NEW.product_code, '')
        BEGIN
            SELECT CASE WHEN EXISTS (
                SELECT 1 FROM product_code_aliases a
                WHERE a.product_code = NEW.product_code
                  AND a.product_id != OLD.id
            ) THEN RAISE(ABORT, 'product code belongs to another product') END;
            INSERT INTO product_code_aliases (product_id, product_code, source)
            SELECT OLD.id, OLD.product_code, 'product_update'
            WHERE TRIM(COALESCE(OLD.product_code, '')) != ''
            ON CONFLICT(product_code) DO NOTHING;
        END
        """
    )
    db.execute("DROP TRIGGER IF EXISTS product_code_alias_after_update")
    db.execute(
        """
        CREATE TRIGGER product_code_alias_after_update
        AFTER UPDATE OF product_code ON products
        WHEN COALESCE(OLD.product_code, '') != COALESCE(NEW.product_code, '')
        BEGIN
            INSERT INTO product_code_aliases (product_id, product_code, source)
            SELECT NEW.id, NEW.product_code, 'current'
            WHERE TRIM(COALESCE(NEW.product_code, '')) != ''
            ON CONFLICT(product_code) DO NOTHING;
            UPDATE orders
            SET product_id = NEW.id
            WHERE product_id IS NULL
              AND product_code IN (
                  SELECT product_code FROM product_code_aliases
                  WHERE product_id = NEW.id
              );
        END
        """
    )


MIGRATIONS = [
    (50, "Add stable order product identity and product code aliases", m050_stable_order_product_identity),
]
