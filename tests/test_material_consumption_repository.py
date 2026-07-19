import sqlite3

from modules.repositories.material_consumption_repository import MaterialConsumptionRepository


def _database():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE system_settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, product_code TEXT);
        CREATE TABLE products (id INTEGER PRIMARY KEY, product_code TEXT);
        CREATE TABLE materials (
            id INTEGER PRIMARY KEY,
            quantity REAL,
            updated_at TEXT
        );
        CREATE TABLE order_materials (
            order_id INTEGER,
            material_id INTEGER,
            quantity_per_unit REAL,
            process_id INTEGER
        );
        CREATE TABLE product_bom (
            product_id INTEGER,
            material_id INTEGER,
            quantity_per_unit REAL,
            process_id INTEGER
        );
        CREATE TABLE material_consumptions (
            material_id INTEGER,
            order_id INTEGER,
            process_id INTEGER,
            quantity REAL,
            operator_id INTEGER,
            operator_name TEXT,
            notes TEXT
        );
        CREATE TABLE material_logs (
            material_id INTEGER,
            type TEXT,
            quantity REAL,
            remark TEXT,
            operator_id INTEGER,
            operator_name TEXT
        );
        """
    )
    return db


def test_deduct_for_process_prefers_order_material_snapshot():
    db = _database()
    db.execute("INSERT INTO system_settings VALUES ('auto_deduct_material', '1')")
    db.execute("INSERT INTO orders VALUES (10, 'PRODUCT-1')")
    db.execute("INSERT INTO products VALUES (20, 'PRODUCT-1')")
    db.execute("INSERT INTO materials VALUES (30, 20, NULL)")
    db.execute("INSERT INTO materials VALUES (31, 20, NULL)")
    db.execute("INSERT INTO order_materials VALUES (10, 30, 2, 40)")
    db.execute("INSERT INTO product_bom VALUES (20, 31, 5, 40)")

    MaterialConsumptionRepository.deduct_for_process(10, 40, 3, 50, "Worker", db=db)

    assert db.execute("SELECT quantity FROM materials WHERE id = 30").fetchone()[0] == 14
    assert db.execute("SELECT quantity FROM materials WHERE id = 31").fetchone()[0] == 20
    consumption = db.execute("SELECT * FROM material_consumptions").fetchone()
    assert dict(consumption) == {
        "material_id": 30,
        "order_id": 10,
        "process_id": 40,
        "quantity": 6.0,
        "operator_id": 50,
        "operator_name": "Worker",
        "notes": "auto-deduct from order BOM",
    }


def test_deduct_for_process_falls_back_to_matching_product_bom():
    db = _database()
    db.execute("INSERT INTO system_settings VALUES ('auto_deduct_material', '1')")
    db.execute("INSERT INTO orders VALUES (10, 'PRODUCT-1')")
    db.execute("INSERT INTO products VALUES (20, 'PRODUCT-1')")
    db.execute("INSERT INTO materials VALUES (30, 10, NULL)")
    db.execute("INSERT INTO materials VALUES (31, 10, NULL)")
    db.execute("INSERT INTO product_bom VALUES (20, 30, 1.5, NULL)")
    db.execute("INSERT INTO product_bom VALUES (20, 31, 2, 99)")

    MaterialConsumptionRepository.deduct_for_process(10, 40, 2, 50, "Worker", db=db)

    assert db.execute("SELECT quantity FROM materials WHERE id = 30").fetchone()[0] == 7
    assert db.execute("SELECT quantity FROM materials WHERE id = 31").fetchone()[0] == 10
    log = db.execute("SELECT * FROM material_logs").fetchone()
    assert dict(log) == {
        "material_id": 30,
        "type": "out",
        "quantity": 3.0,
        "remark": "auto-deduct",
        "operator_id": 50,
        "operator_name": "Worker",
    }
