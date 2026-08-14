import json
import sqlite3

import pytest

from modules.migration_helpers import MigrationInvariantError
from tests.test_process_version_migrations import _legacy_db


def _order_db():
    from modules.migration_process_versioning import m060_process_master_versioning

    db = _legacy_db()
    db.executescript(
        """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            order_no TEXT NOT NULL UNIQUE,
            route_id INTEGER,
            quantity INTEGER NOT NULL DEFAULT 0,
            completed INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE order_processes (
            id INTEGER PRIMARY KEY,
            order_id INTEGER NOT NULL,
            process_id INTEGER NOT NULL,
            seq_order INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            required_audit INTEGER NOT NULL DEFAULT 0,
            completed INTEGER NOT NULL DEFAULT 0,
            scrapped INTEGER NOT NULL DEFAULT 0,
            rework INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(order_id) REFERENCES orders(id),
            FOREIGN KEY(process_id) REFERENCES processes(id)
        );
        CREATE UNIQUE INDEX idx_order_processes_order_id_process_id
            ON order_processes(order_id,process_id);
        CREATE TABLE work_records (
            id INTEGER PRIMARY KEY,
            order_id INTEGER NOT NULL,
            process_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO orders(id,order_no,route_id,quantity,completed) VALUES
            (100,'ROUTE-ORDER',3,20,7),
            (101,'CUSTOM-ORDER',NULL,10,2);
        INSERT INTO order_processes(
            id,order_id,process_id,seq_order,status,required_audit,
            completed,scrapped,rework
        ) VALUES
            (1001,100,1,1,'in_progress',1,7,1,0),
            (1002,101,27,1,'completed',0,2,0,1);
        INSERT INTO work_records(id,order_id,process_id,quantity) VALUES
            (2001,100,1,7),
            (2002,101,27,2);
        """
    )
    m060_process_master_versioning(db)
    db.execute("UPDATE process_routes SET name='Legacy 根已改名' WHERE id=3")
    db.execute("UPDATE processes SET name='Legacy 根已改名' WHERE id=1")
    db.execute("PRAGMA user_version=60")
    db.commit()
    return db


def _business_totals(db):
    return {
        "orders": db.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
        "route_nodes": db.execute(
            "SELECT COUNT(*) FROM process_route_items"
        ).fetchone()[0],
        "order_processes": db.execute(
            "SELECT COUNT(*) FROM order_processes"
        ).fetchone()[0],
        "order_completed": db.execute(
            "SELECT COALESCE(SUM(completed),0) FROM orders"
        ).fetchone()[0],
        "process_completed": db.execute(
            "SELECT COALESCE(SUM(completed),0) FROM order_processes"
        ).fetchone()[0],
        "work_records": db.execute(
            "SELECT COUNT(*) FROM work_records"
        ).fetchone()[0],
        "reported_quantity": db.execute(
            "SELECT COALESCE(SUM(quantity),0) FROM work_records"
        ).fetchone()[0],
    }


def _column_names(db, table):
    return {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}


def test_v061_binds_route_and_custom_orders_to_v1_without_changing_business_totals():
    from modules.migration_process_versioning import m061_bind_order_versions

    db = _order_db()
    try:
        before = _business_totals(db)
        m061_bind_order_versions(db)

        assert {"route_version_id", "route_name_snapshot"} <= _column_names(
            db, "orders"
        )
        assert {
            "process_version_id",
            "process_code_snapshot",
            "process_name_snapshot",
            "process_category_snapshot",
        } <= _column_names(db, "order_processes")
        assert {
            "process_version_id",
            "process_code_snapshot",
            "process_name_snapshot",
            "process_category_snapshot",
            "route_id",
            "route_version_id",
            "route_name_snapshot",
        } <= _column_names(db, "work_records")

        route_order = db.execute(
            "SELECT order_row.route_id,order_row.route_version_id,"
            "order_row.route_name_snapshot,version.process_route_id,version.version,"
            "version.legacy_baseline "
            "FROM orders order_row JOIN process_route_versions version "
            "ON version.id=order_row.route_version_id WHERE order_row.id=100"
        ).fetchone()
        assert dict(route_order) == {
            "route_id": 3,
            "route_version_id": route_order["route_version_id"],
            "route_name_snapshot": "机加工路线",
            "process_route_id": 3,
            "version": 1,
            "legacy_baseline": 1,
        }

        route_process = db.execute(
            "SELECT op.process_id,op.process_version_id,op.process_code_snapshot,"
            "op.process_name_snapshot,op.process_category_snapshot,pv.process_id AS root_id,"
            "pv.version,pv.legacy_baseline,item.id AS route_node_id "
            "FROM order_processes op JOIN process_versions pv "
            "ON pv.id=op.process_version_id JOIN orders order_row ON order_row.id=op.order_id "
            "JOIN process_route_version_items item "
            "ON item.route_version_id=order_row.route_version_id "
            "AND item.process_id=op.process_id "
            "AND item.process_version_id=op.process_version_id WHERE op.id=1001"
        ).fetchone()
        assert route_process["process_id"] == route_process["root_id"] == 1
        assert route_process["version"] == 1
        assert route_process["legacy_baseline"] == 1
        assert route_process["route_node_id"] is not None
        assert route_process["process_code_snapshot"] == "PROC-0001"
        assert route_process["process_name_snapshot"] == "车削"
        assert route_process["process_category_snapshot"] == "机加工"

        custom_process = db.execute(
            "SELECT op.process_id,op.process_version_id,op.process_code_snapshot,"
            "op.process_name_snapshot,op.process_category_snapshot,pv.process_id AS root_id,"
            "pv.version,pv.legacy_baseline "
            "FROM order_processes op JOIN process_versions pv "
            "ON pv.id=op.process_version_id WHERE op.id=1002"
        ).fetchone()
        assert dict(custom_process) == {
            "process_id": 27,
            "process_version_id": custom_process["process_version_id"],
            "process_code_snapshot": "PROC-0027",
            "process_name_snapshot": "包装",
            "process_category_snapshot": "包装",
            "root_id": 27,
            "version": 1,
            "legacy_baseline": 1,
        }
        custom_order = db.execute(
            "SELECT route_version_id,route_name_snapshot FROM orders WHERE id=101"
        ).fetchone()
        assert tuple(custom_order) == (None, "")
        historical_work = db.execute(
            "SELECT process_version_id,process_code_snapshot,process_name_snapshot,"
            "process_category_snapshot,route_id,route_version_id,route_name_snapshot "
            "FROM work_records WHERE id=2001"
        ).fetchone()
        assert tuple(historical_work) == (None, "", "", "", None, None, "")
        assert _business_totals(db) == before
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        db.close()


def test_v061_adds_indexes_reference_guards_and_is_idempotent():
    from modules.migration_process_versioning import m061_bind_order_versions

    db = _order_db()
    try:
        m061_bind_order_versions(db)
        rows_before = [
            tuple(row)
            for row in db.execute(
                "SELECT id,process_version_id,process_code_snapshot,"
                "process_name_snapshot,process_category_snapshot "
                "FROM order_processes ORDER BY id"
            ).fetchall()
        ]
        m061_bind_order_versions(db)
        rows_after = [
            tuple(row)
            for row in db.execute(
                "SELECT id,process_version_id,process_code_snapshot,"
                "process_name_snapshot,process_category_snapshot "
                "FROM order_processes ORDER BY id"
            ).fetchall()
        ]
        assert rows_after == rows_before

        indexes = {
            row["name"]: row["sql"]
            for row in db.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_order_processes_order_id_process_id" in indexes
        assert "idx_order_processes_order_process_version" in indexes
        assert "UNIQUE" in indexes["idx_order_processes_order_process_version"].upper()
        assert "idx_order_processes_process_version" in indexes
        assert "idx_orders_route_version" in indexes

        process_guard = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='prevent_referenced_process_version_delete'"
        ).fetchone()[0]
        route_guard = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='trigger' "
            "AND name='prevent_referenced_route_version_delete'"
        ).fetchone()[0]
        assert '"order_processes"' in process_guard
        assert '"process_version_id"' in process_guard
        assert '"orders"' in route_guard
        assert '"route_version_id"' in route_guard
    finally:
        db.close()


def test_v061_records_unmapped_orders_and_blocks_the_registered_migration():
    from modules import migrations

    db = _order_db()
    try:
        db.execute(
            "INSERT INTO orders(id,order_no,route_id,quantity,completed) "
            "VALUES (102,'MISSING-ROUTE',9999,1,0)"
        )
        db.execute(
            "INSERT INTO orders(id,order_no,route_id,quantity,completed) "
            "VALUES (103,'ROUTE-NODE-MISMATCH',3,1,0)"
        )
        db.execute(
            "INSERT INTO order_processes(id,order_id,process_id,seq_order) "
            "VALUES (1003,103,27,1)"
        )
        db.commit()

        with pytest.raises(MigrationInvariantError, match="Migration v61 blocked"):
            migrations.run_migrations(db)

        issues = db.execute(
            "SELECT entity_type,legacy_id,reason_code,source_summary_json "
            "FROM process_version_migration_exceptions "
            "WHERE migration_key='v061:order-version-bindings' ORDER BY legacy_id,reason_code"
        ).fetchall()
        assert [(row["entity_type"], row["legacy_id"], row["reason_code"]) for row in issues] == [
            ("order", 102, "missing_route_v1"),
            ("order_process", 1003, "missing_route_v1_node"),
        ]
        assert json.loads(issues[0]["source_summary_json"])["route_id"] == 9999
        assert db.execute("PRAGMA user_version").fetchone()[0] == 60
        assert "route_version_id" not in _column_names(db, "orders")
        assert "process_version_id" not in _column_names(db, "order_processes")
    finally:
        db.close()


def test_process_fact_version_binding_is_database_version_63():
    from modules import migrations

    assert migrations.LATEST_VERSION == 63
