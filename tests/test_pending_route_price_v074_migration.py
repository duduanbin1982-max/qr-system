import sqlite3

import pytest

from modules.migration_catalog import MIGRATIONS
from modules.migration_helpers import MigrationInvariantError
from modules.migration_pending_route_price_v074 import m074_pending_route_price_controls


def migrate_database_through(target):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    for version, _, migration in MIGRATIONS:
        if version > target:
            break
        migration(db)
        db.execute(f"PRAGMA user_version={version}")
        db.commit()
    return db


def price_snapshot(db):
    rows = db.execute(
        "SELECT status,COUNT(*) AS rows,"
        "COALESCE(SUM(normal_unit_price_micros),0) AS micros "
        "FROM route_price_versions GROUP BY status ORDER BY status"
    ).fetchall()
    return [(row["status"], row["rows"], row["micros"]) for row in rows]


def seed_pending_price_binding(db, price_count=1):
    process_id = db.execute(
        "INSERT INTO processes(name,category,status,process_code,lifecycle_status) "
        "VALUES ('V074 工序','机加工','active','PROC-V074','active')"
    ).lastrowid
    process_version_id = db.execute(
        "INSERT INTO process_versions(process_id,version,process_code_snapshot,name,"
        "category,status,content_digest,idempotency_key) "
        "VALUES (?,1,'PROC-V074','V074 工序','机加工','pending_approval',"
        "'process-digest','v074-process')", (process_id,)
    ).lastrowid
    route_id = db.execute(
        "INSERT INTO process_routes(name,category,status,route_code,lifecycle_status) "
        "VALUES ('V074 路线','机加工','inactive','ROUTE-V074','active')"
    ).lastrowid
    route_version_id = db.execute(
        "INSERT INTO process_route_versions(process_route_id,version,route_code_snapshot,"
        "name,category,status,content_digest,idempotency_key) "
        "VALUES (?,1,'ROUTE-V074','V074 路线','机加工','pending_approval',"
        "'route-digest','v074-route')", (route_id,)
    ).lastrowid
    db.execute(
        "INSERT INTO process_route_version_items(route_version_id,process_id,"
        "process_version_id,seq_order) VALUES (?,?,?,10)",
        (route_version_id, process_id, process_version_id),
    )
    for index in range(price_count):
        db.execute(
            "INSERT INTO route_price_versions(route_id,route_version_id,process_id,"
            "process_version_id,normal_unit_price_micros,valid_from,status,remark) "
            "VALUES (?,?,?,?,100000,?,'draft',?)",
            (
                route_id, route_version_id, process_id, process_version_id,
                f"2026-08-{index + 1:02d} 07:00:00", f"draft-{index + 1}",
            ),
        )
    db.commit()
    return db


def migrated_v074_database_with_draft_price():
    return seed_pending_price_binding(migrate_database_through(74))


def test_v074_preserves_prices_and_adds_voided_lifecycle():
    db = migrate_database_through(73)
    before = price_snapshot(db)

    m074_pending_route_price_controls(db)

    columns = {row["name"] for row in db.execute("PRAGMA table_info(route_price_versions)")}
    assert {
        "idempotency_key", "request_digest",
        "route_content_digest_snapshot", "process_content_digest_snapshot",
        "voided_at", "voided_by", "voided_by_name", "void_reason",
    }.issubset(columns)
    assert price_snapshot(db) == before
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_v074_voided_price_is_immutable():
    db = migrated_v074_database_with_draft_price()
    db.execute(
        "UPDATE route_price_versions SET status='voided',"
        "voided_at='2026-08-24 12:00:00',voided_by_name='测试人',"
        "void_reason='路线驳回' WHERE id=1"
    )
    with pytest.raises(sqlite3.IntegrityError, match="voided price versions are immutable"):
        db.execute("UPDATE route_price_versions SET remark='changed' WHERE id=1")


def test_v074_rejects_null_exact_bindings_with_blocking_price_ids():
    db = migrate_database_through(73)
    db.execute("DROP TRIGGER validate_price_version_binding_insert")
    db.execute(
        "INSERT INTO route_price_versions(route_id,process_id,normal_unit_price_micros,"
        "valid_from,status) VALUES (1,1,100000,'2026-08-01 07:00:00','draft')"
    )
    price_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

    with pytest.raises(MigrationInvariantError, match=rf"{price_id}"):
        m074_pending_route_price_controls(db)


def test_v074_rejects_duplicate_drafts_for_one_pending_node():
    db = seed_pending_price_binding(migrate_database_through(73), price_count=2)
    price_ids = [row[0] for row in db.execute("SELECT id FROM route_price_versions ORDER BY id")]

    with pytest.raises(MigrationInvariantError, match=rf"{price_ids[0]}.*{price_ids[1]}"):
        m074_pending_route_price_controls(db)


def test_v074_backfills_digest_evidence_once_for_existing_drafts():
    db = seed_pending_price_binding(migrate_database_through(73))

    m074_pending_route_price_controls(db)
    price = db.execute(
        "SELECT route_content_digest_snapshot,process_content_digest_snapshot "
        "FROM route_price_versions WHERE id=1"
    ).fetchone()
    assert tuple(price) == ("route-digest", "process-digest")
    event = db.execute(
        "SELECT event_type,idempotency_key FROM payroll_events "
        "WHERE idempotency_key='v074:price:1:digest'"
    ).fetchone()
    assert tuple(event) == ("price_version_v074_digest_backfilled", "v074:price:1:digest")

    m074_pending_route_price_controls(db)
    assert db.execute(
        "SELECT COUNT(*) FROM payroll_events WHERE idempotency_key='v074:price:1:digest'"
    ).fetchone()[0] == 1
