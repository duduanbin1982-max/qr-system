import sqlite3

import pytest

from modules.domain.errors import ConflictError
from modules.services.material_service import MaterialService


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
            updated_at TEXT,
            name TEXT DEFAULT '',
            unit TEXT DEFAULT '件'
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material_id INTEGER,
            order_id INTEGER,
            process_id INTEGER,
            quantity REAL,
            operator_id INTEGER,
            operator_name TEXT,
            notes TEXT,
            source_work_record_id INTEGER
        );
        CREATE TABLE material_logs (
            material_id INTEGER,
            type TEXT,
            quantity REAL,
            remark TEXT,
            operator_id INTEGER,
            operator_name TEXT,
            balance_before REAL,
            balance_after REAL,
            source_type TEXT,
            source_id INTEGER,
            reversal_of_log_id INTEGER
        );
        """
    )
    return db


def test_deduct_for_process_prefers_order_material_snapshot():
    db = _database()
    db.execute("INSERT INTO system_settings VALUES ('auto_deduct_material', '1')")
    db.execute("INSERT INTO orders VALUES (10, 'PRODUCT-1')")
    db.execute("INSERT INTO products VALUES (20, 'PRODUCT-1')")
    db.execute("INSERT INTO materials VALUES (30, 20, NULL, 'Steel', 'kg')")
    db.execute("INSERT INTO materials VALUES (31, 20, NULL, 'Wire', 'm')")
    db.execute("INSERT INTO order_materials VALUES (10, 30, 2, 40)")
    db.execute("INSERT INTO product_bom VALUES (20, 31, 5, 40)")

    MaterialService.deduct_for_process(10, 40, 3, 50, "Worker", db=db)

    assert db.execute("SELECT quantity FROM materials WHERE id = 30").fetchone()[0] == 14
    assert db.execute("SELECT quantity FROM materials WHERE id = 31").fetchone()[0] == 20
    consumption = db.execute("SELECT * FROM material_consumptions").fetchone()
    assert dict(consumption) == {
        "id": 1,
        "material_id": 30,
        "order_id": 10,
        "process_id": 40,
        "quantity": 6.0,
        "operator_id": 50,
        "operator_name": "Worker",
        "notes": "auto-deduct from order BOM",
        "source_work_record_id": None,
    }


def test_deduct_for_process_falls_back_to_matching_product_bom():
    db = _database()
    db.execute("INSERT INTO system_settings VALUES ('auto_deduct_material', '1')")
    db.execute("INSERT INTO orders VALUES (10, 'PRODUCT-1')")
    db.execute("INSERT INTO products VALUES (20, 'PRODUCT-1')")
    db.execute("INSERT INTO materials VALUES (30, 10, NULL, 'Steel', 'kg')")
    db.execute("INSERT INTO materials VALUES (31, 10, NULL, 'Wire', 'm')")
    db.execute("INSERT INTO product_bom VALUES (20, 30, 1.5, NULL)")
    db.execute("INSERT INTO product_bom VALUES (20, 31, 2, 99)")

    MaterialService.deduct_for_process(10, 40, 2, 50, "Worker", db=db)

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
        "balance_before": 10.0,
        "balance_after": 7.0,
        "source_type": "auto_consumption",
        "source_id": 1,
        "reversal_of_log_id": None,
    }


def test_deduct_for_process_is_disabled_by_setting_even_with_order_snapshot():
    db = _database()
    db.execute("INSERT INTO system_settings VALUES ('auto_deduct_material', '0')")
    db.execute("INSERT INTO materials VALUES (30, 10, NULL, 'Steel', 'kg')")
    db.execute("INSERT INTO order_materials VALUES (10, 30, 2, 40)")

    MaterialService.deduct_for_process(10, 40, 3, 50, "Worker", db=db)

    assert db.execute("SELECT quantity FROM materials WHERE id = 30").fetchone()[0] == 10
    assert db.execute("SELECT COUNT(*) FROM material_consumptions").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM material_logs").fetchone()[0] == 0


def test_deduct_for_process_blocks_all_materials_when_any_stock_is_short():
    db = _database()
    db.execute("INSERT INTO system_settings VALUES ('auto_deduct_material', '1')")
    db.execute("INSERT INTO materials VALUES (30, 20, NULL, 'Steel', 'kg')")
    db.execute("INSERT INTO materials VALUES (31, 2, NULL, 'Wire', 'm')")
    db.execute("INSERT INTO order_materials VALUES (10, 30, 2, 40)")
    db.execute("INSERT INTO order_materials VALUES (10, 31, 1, 40)")

    with pytest.raises(ConflictError, match='物料库存不足，报工未提交') as error:
        MaterialService.deduct_for_process(10, 40, 3, 50, "Worker", db=db)

    assert error.value.details == {
        'shortages': [{
            'material_id': 31,
            'material_name': 'Wire',
            'unit': 'm',
            'required_quantity': 3.0,
            'available_quantity': 2.0,
        }]
    }
    balances = [
        tuple(row)
        for row in db.execute("SELECT id, quantity FROM materials ORDER BY id").fetchall()
    ]
    assert balances == [
        (30, 20.0),
        (31, 2.0),
    ]
    assert db.execute("SELECT COUNT(*) FROM material_consumptions").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM material_logs").fetchone()[0] == 0


def test_deduct_for_process_rejects_duplicate_work_record_source():
    db = _database()
    db.execute("INSERT INTO system_settings VALUES ('auto_deduct_material', '1')")
    db.execute("INSERT INTO materials VALUES (30, 10, NULL, 'Steel', 'kg')")
    db.execute("INSERT INTO order_materials VALUES (10, 30, 2, 40)")

    MaterialService.deduct_for_process(
        10, 40, 2, 50, "Worker", db=db, work_record_id=77
    )
    with pytest.raises(ConflictError, match='物料已经扣减') as error:
        MaterialService.deduct_for_process(
            10, 40, 2, 50, "Worker", db=db, work_record_id=77
        )

    assert error.value.details == {
        'work_record_id': 77,
        'consumption_ids': [1],
    }
    assert db.execute("SELECT quantity FROM materials WHERE id = 30").fetchone()[0] == 6
    assert db.execute("SELECT COUNT(*) FROM material_consumptions").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM material_logs").fetchone()[0] == 1
