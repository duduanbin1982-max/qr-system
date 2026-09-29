import json
import shutil
import sqlite3

import pytest

from modules import migrations
from modules.migration_inventory_product_views import m096_inventory_product_views


@pytest.fixture(scope="module")
def v095_database(tmp_path_factory):
    database = tmp_path_factory.mktemp("inventory-v096") / "v095.db"
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        for version, _, migrate in migrations.MIGRATIONS:
            if version >= 96:
                break
            migrate(connection)
        connection.execute("PRAGMA user_version=95")
        connection.commit()
    finally:
        connection.close()
    return database


@pytest.fixture
def db(v095_database, tmp_path):
    database = tmp_path / "test.db"
    shutil.copy2(v095_database, database)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def _columns(db, table):
    return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def test_v096_adds_product_identity_and_immutable_allocation_evidence(db):
    m096_inventory_product_views(db)

    assert {
        "product_id",
        "product_code_snapshot",
        "product_name_snapshot",
        "frozen_quantity",
        "route_version_id_snapshot",
        "quality_status",
    }.issubset(_columns(db, "inventory"))
    tables = {
        row[0]
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "product_inventory_thresholds",
        "inventory_allocation_runs",
        "inventory_allocation_items",
    }.issubset(tables)
    triggers = {
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        )
    }
    assert {
        "prevent_inventory_allocation_runs_update",
        "prevent_inventory_allocation_runs_delete",
        "prevent_inventory_allocation_items_update",
        "prevent_inventory_allocation_items_delete",
    }.issubset(triggers)


def test_v096_rejects_allocation_evidence_updates_and_deletes(db):
    m096_inventory_product_views(db)
    product_id = db.execute(
        "INSERT INTO products(product_code,product_name) "
        "VALUES('P-IMMUTABLE','不可变产品')"
    ).lastrowid
    inventory_id = db.execute(
        "INSERT INTO inventory "
        "(product_model,product_name,quantity,product_id,product_code_snapshot,"
        "product_name_snapshot) VALUES('P-IMMUTABLE','不可变产品',5,?,?,?)",
        (product_id, "P-IMMUTABLE", "不可变产品"),
    ).lastrowid
    movement_id = db.execute(
        "INSERT INTO inventory_logs(inventory_id,type,quantity) VALUES(?,'out',1)",
        (inventory_id,),
    ).lastrowid
    run_id = db.execute(
        "INSERT INTO inventory_allocation_runs "
        "(idempotency_key,request_digest,preview_digest,result_digest,product_id,"
        "compatibility_key,mode,requested_quantity) "
        "VALUES('immutable-run','request','preview','result',?,'qualified','fifo',1)",
        (product_id,),
    ).lastrowid
    item_id = db.execute(
        "INSERT INTO inventory_allocation_items "
        "(run_id,sequence_no,inventory_id,allocated_quantity,movement_id,"
        "balance_before,balance_after) VALUES(?,1,?,1,?,5,4)",
        (run_id, inventory_id, movement_id),
    ).lastrowid
    db.commit()

    blocked_operations = (
        (
            "UPDATE inventory_allocation_runs SET reason='changed' WHERE id=?",
            run_id,
            "inventory_allocation_runs is immutable",
        ),
        (
            "DELETE FROM inventory_allocation_runs WHERE id=?",
            run_id,
            "inventory_allocation_runs is immutable",
        ),
        (
            "UPDATE inventory_allocation_items SET order_no_snapshot='changed' "
            "WHERE id=?",
            item_id,
            "inventory_allocation_items is immutable",
        ),
        (
            "DELETE FROM inventory_allocation_items WHERE id=?",
            item_id,
            "inventory_allocation_items is immutable",
        ),
    )
    for statement, row_id, message in blocked_operations:
        with pytest.raises(sqlite3.IntegrityError, match=message):
            db.execute(statement, (row_id,))
        db.rollback()

    assert db.execute(
        "SELECT COUNT(*) FROM inventory_allocation_runs WHERE id=?", (run_id,)
    ).fetchone()[0] == 1
    assert db.execute(
        "SELECT COUNT(*) FROM inventory_allocation_items WHERE id=?", (item_id,)
    ).fetchone()[0] == 1


def test_v096_backfills_only_unambiguous_product_identity(db):
    product_id = db.execute(
        "INSERT INTO products(product_code,product_name) VALUES('P-1001','产品一')"
    ).lastrowid
    order_id = db.execute(
        "INSERT INTO orders(order_no,product_code,product_id,product_name,quantity) "
        "VALUES('O-1','P-1001',?,'产品一',1)",
        (product_id,),
    ).lastrowid
    inventory_id = db.execute(
        "INSERT INTO inventory(product_model,product_name,quantity,order_id) "
        "VALUES('P-1001','产品一',5,?)",
        (order_id,),
    ).lastrowid

    m096_inventory_product_views(db)

    row = db.execute(
        "SELECT product_id,product_code_snapshot,product_name_snapshot "
        "FROM inventory WHERE id=?",
        (inventory_id,),
    ).fetchone()
    assert tuple(row) == (product_id, "P-1001", "产品一")


def test_v096_does_not_hide_order_and_model_identity_conflict(db):
    first = db.execute(
        "INSERT INTO products(product_code,product_name) VALUES('P-A','A')"
    ).lastrowid
    second = db.execute(
        "INSERT INTO products(product_code,product_name) VALUES('P-B','B')"
    ).lastrowid
    db.execute(
        "INSERT OR IGNORE INTO product_code_aliases(product_id,product_code,source) "
        "VALUES(?, 'P-B', 'current')",
        (second,),
    )
    order_id = db.execute(
        "INSERT INTO orders(order_no,product_code,product_id,product_name,quantity) "
        "VALUES('O-X','P-A',?,'A',1)",
        (first,),
    ).lastrowid
    inventory_id = db.execute(
        "INSERT INTO inventory(product_model,product_name,quantity,order_id) "
        "VALUES('P-B','B',5,?)",
        (order_id,),
    ).lastrowid

    m096_inventory_product_views(db)

    assert (
        db.execute(
            "SELECT product_id FROM inventory WHERE id=?", (inventory_id,)
        ).fetchone()[0]
        is None
    )


def test_v096_grants_new_actions_without_removing_existing_permissions(db):
    role_id = db.execute(
        "INSERT INTO roles(name,code,permissions) VALUES('仓库','warehouse_x',?)",
        (json.dumps(["inventory:view", "inventory:edit"]),),
    ).lastrowid

    m096_inventory_product_views(db)

    permissions = json.loads(
        db.execute(
            "SELECT permissions FROM roles WHERE id=?", (role_id,)
        ).fetchone()[0]
    )
    assert {"inventory:view", "inventory:edit"}.issubset(permissions)
    assert {
        "inventory:export",
        "inventory:inbound",
        "inventory:outbound",
        "inventory:allocate",
        "inventory:reserve",
        "inventory:adjust",
        "inventory:audit",
        "inventory:manage_threshold",
    }.issubset(permissions)


def test_v096_can_be_applied_twice_safely(db):
    m096_inventory_product_views(db)
    first_schema = {
        (row[0], row[1])
        for row in db.execute(
            "SELECT type,name FROM sqlite_master "
            "WHERE name LIKE 'inventory_allocation_%' "
            "OR name LIKE 'prevent_inventory_allocation_%'"
        )
    }

    m096_inventory_product_views(db)

    second_schema = {
        (row[0], row[1])
        for row in db.execute(
            "SELECT type,name FROM sqlite_master "
            "WHERE name LIKE 'inventory_allocation_%' "
            "OR name LIKE 'prevent_inventory_allocation_%'"
        )
    }
    assert second_schema == first_schema
