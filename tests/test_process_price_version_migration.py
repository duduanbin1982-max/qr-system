import sqlite3
import uuid

import pytest

from factories import (
    WORKER_HASH,
    bind_order_process_versions,
    create_order,
    create_process_route,
    ensure_process,
    ensure_user,
)
from modules.db import get_db
from modules.migration_helpers import MigrationInvariantError
from modules.services.payroll_service import PayrollWorkflowService
from modules.services.price_version_service import PriceVersionService
from modules.repositories.payroll_repository import PayrollRepository
from tests.test_process_version_migrations import _legacy_db


def _v061_price_db():
    from modules.migration_process_versioning import m060_process_master_versioning

    db = _legacy_db()
    m060_process_master_versioning(db)
    db.executescript(
        """
        ALTER TABLE route_price_versions ADD COLUMN normal_unit_price_micros INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE route_price_versions ADD COLUMN rework_rate_basis_points INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE route_price_versions ADD COLUMN rework_rate_configured INTEGER NOT NULL DEFAULT 0;
        ALTER TABLE route_price_versions ADD COLUMN valid_from TEXT NOT NULL DEFAULT '';
        ALTER TABLE route_price_versions ADD COLUMN valid_to TEXT;
        ALTER TABLE route_price_versions ADD COLUMN status TEXT NOT NULL DEFAULT 'draft';
        ALTER TABLE route_price_versions ADD COLUMN row_version INTEGER NOT NULL DEFAULT 0;
        CREATE TABLE payroll_detail_lines (
            id INTEGER PRIMARY KEY,
            price_version_id INTEGER,
            amount_cents INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO route_price_versions(
            id,route_id,process_id,normal_unit_price_micros,valid_from,status
        ) VALUES (401,3,1,12500,'2026-01-01 07:00:00','approved');
        INSERT INTO payroll_detail_lines(id,price_version_id,amount_cents)
        VALUES (501,401,375);
        CREATE TRIGGER protect_approved_price_version
        BEFORE UPDATE ON route_price_versions
        WHEN OLD.status='approved'
        BEGIN SELECT RAISE(ABORT,'approved price versions are immutable'); END;
        PRAGMA user_version=61;
        """
    )
    db.commit()
    return db


def _columns(db, table):
    return {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}


def test_v062_binds_legacy_prices_to_v1_and_preserves_payroll_amounts():
    from modules.migration_process_versioning import m062_bind_price_versions

    db = _v061_price_db()
    try:
        before = tuple(
            db.execute(
                "SELECT COUNT(*),COALESCE(SUM(amount_cents),0) FROM payroll_detail_lines"
            ).fetchone()
        )
        m062_bind_price_versions(db)

        assert {"route_version_id", "process_version_id"} <= _columns(
            db, "route_price_versions"
        )
        assert {"route_version_id", "process_version_id"} <= _columns(
            db, "payroll_detail_lines"
        )
        price = db.execute(
            "SELECT price.route_id,price.process_id,price.route_version_id,"
            "price.process_version_id,route_version.version AS route_version,"
            "process_version.version AS process_version "
            "FROM route_price_versions price "
            "JOIN process_route_versions route_version "
            "ON route_version.id=price.route_version_id "
            "JOIN process_versions process_version "
            "ON process_version.id=price.process_version_id WHERE price.id=401"
        ).fetchone()
        assert price["route_id"] == 3
        assert price["process_id"] == 1
        assert price["route_version"] == 1
        assert price["process_version"] == 1
        assert tuple(
            db.execute(
                "SELECT COUNT(*),COALESCE(SUM(amount_cents),0) FROM payroll_detail_lines"
            ).fetchone()
        ) == before

        first = tuple(
            db.execute(
                "SELECT route_version_id,process_version_id FROM route_price_versions "
                "WHERE id=401"
            ).fetchone()
        )
        route_v2_id = db.execute(
            "INSERT INTO process_route_versions "
            "(process_route_id,version,route_code_snapshot,name,category,description,status) "
            "SELECT process_route_id,2,route_code_snapshot,name,category,description,'draft' "
            "FROM process_route_versions WHERE process_route_id=3 AND version=1"
        ).lastrowid
        packaging_version_id = db.execute(
            "SELECT id FROM process_versions WHERE process_id=27 AND version=1"
        ).fetchone()["id"]
        db.execute(
            "INSERT INTO process_route_version_items "
            "(route_version_id,process_id,process_version_id,seq_order) "
            "VALUES (?,?,?,1)",
            (route_v2_id, 27, packaging_version_id),
        )
        v2_price_id = db.execute(
            "INSERT INTO route_price_versions "
            "(route_id,route_version_id,process_id,process_version_id,"
            "normal_unit_price_micros,valid_from,status) "
            "VALUES (3,?,27,?,15000,'2026-09-01 07:00:00','draft')",
            (route_v2_id, packaging_version_id),
        ).lastrowid
        m062_bind_price_versions(db)
        assert tuple(
            db.execute(
                "SELECT route_version_id,process_version_id FROM route_price_versions "
                "WHERE id=401"
            ).fetchone()
        ) == first
        assert tuple(
            db.execute(
                "SELECT route_version_id,process_version_id FROM route_price_versions "
                "WHERE id=?",
                (v2_price_id,),
            ).fetchone()
        ) == (route_v2_id, packaging_version_id)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        db.close()


def test_v062_restores_price_guards_and_rejects_naked_root_bindings():
    from modules.migration_process_versioning import m062_bind_price_versions

    db = _v061_price_db()
    try:
        m062_bind_price_versions(db)
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "UPDATE route_price_versions SET normal_unit_price_micros=13000 WHERE id=401"
            )
        db.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="version binding"):
            db.execute(
                "INSERT INTO route_price_versions "
                "(route_id,process_id,normal_unit_price_micros,valid_from,status) "
                "VALUES (3,1,13000,'2026-09-01 07:00:00','draft')"
            )
    finally:
        db.close()


def _add_historical_price_candidate(db, version_number, order_id):
    route_version_id = db.execute(
        "INSERT INTO process_route_versions "
        "(process_route_id,version,route_code_snapshot,name,category,description,status) "
        "SELECT process_route_id,?,route_code_snapshot,name,category,description,'draft' "
        "FROM process_route_versions WHERE process_route_id=3 AND version=1",
        (version_number,),
    ).lastrowid
    process_version_id = db.execute(
        "SELECT id FROM process_versions WHERE process_id=27 AND version=1"
    ).fetchone()[0]
    db.execute(
        "INSERT INTO process_route_version_items "
        "(route_version_id,process_id,process_version_id,seq_order) VALUES (?,?,?,1)",
        (route_version_id, 27, process_version_id),
    )
    db.execute(
        "UPDATE process_route_versions SET status='superseded' WHERE id=?",
        (route_version_id,),
    )
    db.execute(
        "INSERT INTO orders(id,route_id,route_version_id) VALUES (?,?,?)",
        (order_id, 3, route_version_id),
    )
    return route_version_id, process_version_id


def test_v062_binds_removed_process_price_to_unique_order_route_revision():
    from modules.migration_process_versioning import m062_bind_price_versions

    db = _v061_price_db()
    try:
        db.executescript(
            """
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                route_id INTEGER,
                route_version_id INTEGER
            );
            INSERT INTO route_price_versions(
                id,route_id,process_id,normal_unit_price_micros,valid_from,status
            ) VALUES (402,3,27,15000,'2026-01-01 07:00:00','approved');
            """
        )
        route_version_id, process_version_id = _add_historical_price_candidate(db, 2, 601)

        m062_bind_price_versions(db)

        assert tuple(
            db.execute(
                "SELECT route_version_id,process_version_id FROM route_price_versions "
                "WHERE id=402"
            ).fetchone()
        ) == (route_version_id, process_version_id)
    finally:
        db.close()


def test_v062_blocks_removed_process_price_with_multiple_order_route_revisions():
    from modules.migration_process_versioning import m062_bind_price_versions

    db = _v061_price_db()
    try:
        db.executescript(
            """
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                route_id INTEGER,
                route_version_id INTEGER
            );
            INSERT INTO route_price_versions(
                id,route_id,process_id,normal_unit_price_micros,valid_from,status
            ) VALUES (402,3,27,15000,'2026-01-01 07:00:00','approved');
            """
        )
        _add_historical_price_candidate(db, 2, 601)
        _add_historical_price_candidate(db, 3, 602)

        with pytest.raises(MigrationInvariantError, match="1 price binding exception"):
            m062_bind_price_versions(db)

        issue = db.execute(
            "SELECT reason_code FROM process_version_migration_exceptions "
            "WHERE migration_key='v062:price-version-bindings' AND legacy_id=402"
        ).fetchone()
        assert issue[0] == "multiple_historical_route_candidates"
    finally:
        db.close()


def test_new_price_and_payroll_detail_use_exact_master_data_versions(client):
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, f"精确工价工序-{uuid.uuid4().hex[:6]}")
        route_id = create_process_route(db, [process_id], f"精确工价路线-{uuid.uuid4().hex[:6]}")
        worker_id = ensure_user(
            db,
            f"exact-price-worker-{uuid.uuid4().hex[:6]}",
            WORKER_HASH,
            "精确工价员工",
            "worker",
            f"EXACT-{uuid.uuid4().hex[:6]}",
        )
        order_id = create_order(db, [process_id], product_code="EXACT-PRICE")
        db.execute("UPDATE orders SET route_id=? WHERE id=?", (route_id, order_id))
        bind_order_process_versions(db, order_id)
        binding = db.execute(
            "SELECT order_row.route_version_id,op.process_version_id,"
            "order_row.route_name_snapshot,op.process_name_snapshot "
            "FROM orders order_row JOIN order_processes op ON op.order_id=order_row.id "
            "WHERE order_row.id=? AND op.process_id=?",
            (order_id, process_id),
        ).fetchone()
        db.execute(
            "INSERT INTO work_records "
            "(order_id,process_id,process_version_id,process_name_snapshot,user_id,type,"
            "quantity,status,route_id,route_version_id,route_name_snapshot,created_at) "
            "VALUES (?,?,?,?,?,'normal',3,'approved',?,?,?,'2026-08-13 08:00:00')",
            (
                order_id,
                process_id,
                binding["process_version_id"],
                binding["process_name_snapshot"],
                worker_id,
                route_id,
                binding["route_version_id"],
                binding["route_name_snapshot"],
            ),
        )
        db.commit()
        preparer = {"id": 1, "name": "工价制单人"}
        approver = {"id": 2, "name": "工价批准人"}

        with pytest.raises(ValueError, match="路线版本和工序版本"):
            PriceVersionService.create(
                {
                    "route_id": route_id,
                    "process_id": process_id,
                    "normal_unit_price": "1.25",
                    "valid_from": "2026-08-01 07:00:00",
                },
                preparer,
            )

        price = PriceVersionService.create(
            {
                "route_id": route_id,
                "route_version_id": binding["route_version_id"],
                "process_id": process_id,
                "process_version_id": binding["process_version_id"],
                "expected_route_content_digest": PayrollRepository.exact_price_binding(
                    binding["route_version_id"], binding["process_version_id"], db
                )["route_content_digest"],
                "expected_process_content_digest": PayrollRepository.exact_price_binding(
                    binding["route_version_id"], binding["process_version_id"], db
                )["process_content_digest"],
                "normal_unit_price": "1.25",
                "valid_from": "2026-08-01 07:00:00",
                "idempotency_key": f"exact-price-create-{uuid.uuid4().hex}",
            },
            preparer,
        )
        listed = PriceVersionService.list_versions(
            route_version_id=binding["route_version_id"],
            process_version_id=binding["process_version_id"],
        )
        assert [item["id"] for item in listed] == [price["id"]]
        PriceVersionService.approve(price["id"], approver, price["row_version"])
        batch = PayrollWorkflowService.create_batch(
            "2026-08", preparer, f"exact-price-payroll-{uuid.uuid4().hex}"
        )
        detail = db.execute(
            "SELECT route_version_id,process_version_id,route_name_snapshot,"
            "process_name_snapshot,price_version_id,amount_cents "
            "FROM payroll_detail_lines WHERE batch_id=? AND work_record_id IS NOT NULL",
            (batch["id"],),
        ).fetchone()

        assert detail["route_version_id"] == binding["route_version_id"]
        assert detail["process_version_id"] == binding["process_version_id"]
        assert detail["route_name_snapshot"] == binding["route_name_snapshot"]
        assert detail["process_name_snapshot"] == binding["process_name_snapshot"]
        assert detail["price_version_id"] == price["id"]
        assert detail["amount_cents"] == 375


def test_process_fact_migration_is_v063():
    from modules.migrations import MIGRATIONS

    assert next(
        version
        for version, _, migration in MIGRATIONS
        if migration.__name__ == "m063_version_process_facts"
    ) == 63
