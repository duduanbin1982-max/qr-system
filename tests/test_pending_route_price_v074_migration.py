import sqlite3

import pytest

import modules.migration_pending_route_price_v074 as v074
from modules.migration_catalog import MIGRATIONS
from modules.migration_helpers import MigrationInvariantError
from modules.migration_pending_route_price_v074 import (
    V074_PRICE_COLUMNS,
    m074_pending_route_price_controls,
)


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


V073_PRICE_COLUMNS = (
    "id", "route_id", "process_id", "normal_unit_price_micros",
    "rework_rate_basis_points", "rework_rate_configured", "valid_from", "valid_to",
    "status", "created_by", "created_by_name", "created_at", "approved_by",
    "approved_by_name", "approved_at", "remark", "legacy_route_price_id",
    "row_version", "route_version_id", "process_version_id", "legacy_binding_unavailable",
)


def rows_as_tuples(db, table, columns):
    return [
        tuple(row[column] for column in columns)
        for row in db.execute(
            f"SELECT {','.join(columns)} FROM {table} ORDER BY id"
        ).fetchall()
    ]


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


def seed_price_lifecycles_with_references(db):
    seed_pending_price_binding(db)
    binding = db.execute(
        "SELECT route_id,route_version_id,process_id,process_version_id "
        "FROM route_price_versions WHERE id=1"
    ).fetchone()
    db.execute("DROP TRIGGER validate_approved_price_version_insert")
    approved_price_id = db.execute(
        "INSERT INTO route_price_versions(route_id,route_version_id,process_id,"
        "process_version_id,normal_unit_price_micros,valid_from,valid_to,status,remark) "
        "VALUES (?,?,?,?,200000,'2026-01-01 07:00:00','2026-02-01 07:00:00',"
        "'approved','approved-v073')",
        tuple(binding),
    ).lastrowid
    retired_price_id = db.execute(
        "INSERT INTO route_price_versions(route_id,route_version_id,process_id,"
        "process_version_id,normal_unit_price_micros,valid_from,valid_to,status,remark) "
        "VALUES (?,?,?,?,300000,'2026-02-01 07:00:00','2026-03-01 07:00:00',"
        "'retired','retired-v073')",
        tuple(binding),
    ).lastrowid
    order_id = db.execute(
        "INSERT INTO orders(order_no,route_id,route_version_id,route_name_snapshot) "
        "VALUES ('V074-PRESERVE-1',?,?, 'V074 路线')",
        (binding["route_id"], binding["route_version_id"]),
    ).lastrowid
    work_ids = []
    for index in range(3):
        work_ids.append(db.execute(
            "INSERT INTO work_records(order_id,process_id,user_id,status,quantity,"
            "process_version_id,route_id,route_version_id,process_code_snapshot,"
            "process_name_snapshot,process_category_snapshot,route_name_snapshot,"
            "version_binding_source) VALUES (?,?,1,'approved',1,?,?,?,"
            "'PROC-V074','V074 工序','机加工','V074 路线','captured')",
            (order_id, binding["process_id"], binding["process_version_id"],
             binding["route_id"], binding["route_version_id"]),
        ).lastrowid)
    batch_id = db.execute(
        "INSERT INTO payroll_batches(payroll_month,version,period_start,period_end,"
        "source_cutoff_at,idempotency_key) VALUES "
        "('2026-08',1,'2026-08-01 07:00:00','2026-09-01 07:00:00',"
        "'2026-09-01 07:00:00','v074-preserve-batch')"
    ).lastrowid
    employee_line_id = db.execute(
        "INSERT INTO payroll_employee_lines(batch_id,employee_id,employee_name_snapshot) "
        "VALUES (?,1,'V074 审计员工')", (batch_id,)
    ).lastrowid
    price_ids = (1, approved_price_id, retired_price_id)
    for index, (price_id, work_id) in enumerate(zip(price_ids, work_ids), start=1):
        db.execute(
            "INSERT INTO payroll_detail_lines(batch_id,employee_line_id,source_type,"
            "source_id,work_record_id,order_id,route_id,process_id,quantity,"
            "price_version_id,unit_price_micros,amount_cents,resolution_method,"
            "resolution_reason,route_version_id,process_version_id,version_binding_source) "
            "VALUES (?,?,'normal_work',?,?,?,?,?,?,?,100000,100,'exact','v073',?,?, 'captured')",
            (batch_id, employee_line_id, index, work_id, order_id, binding["route_id"],
             binding["process_id"], 1, price_id, binding["route_version_id"],
             binding["process_version_id"]),
        )
        db.execute(
            "INSERT INTO payroll_work_price_resolutions(work_record_id,price_version_id,"
            "resolution_method,resolution_reason) VALUES (?,?,'current_price_migration','v073')",
            (work_id, price_id),
        )
    db.commit()
    return price_ids


def test_v074_preserves_prices_and_adds_voided_lifecycle():
    db = migrate_database_through(73)
    price_ids = seed_price_lifecycles_with_references(db)
    before_prices = rows_as_tuples(db, "route_price_versions", V073_PRICE_COLUMNS)
    before_references = {
        "orders": rows_as_tuples(db, "orders", ("id", "route_id", "route_version_id")),
        "work": rows_as_tuples(
            db, "work_records", ("id", "order_id", "process_id", "process_version_id", "route_version_id")
        ),
        "detail": rows_as_tuples(
            db, "payroll_detail_lines", ("id", "work_record_id", "price_version_id", "route_version_id", "process_version_id")
        ),
        "resolution": rows_as_tuples(
            db, "payroll_work_price_resolutions", ("id", "work_record_id", "price_version_id")
        ),
    }

    m074_pending_route_price_controls(db)

    metadata = {row["name"]: row for row in db.execute("PRAGMA table_info(route_price_versions)")}
    assert {
        "idempotency_key", "request_digest",
        "route_content_digest_snapshot", "process_content_digest_snapshot",
        "voided_at", "voided_by", "voided_by_name", "void_reason",
    }.issubset(metadata)
    assert metadata["idempotency_key"][3:] == (0, None, 0)
    assert metadata["voided_at"][3:] == (0, None, 0)
    for name in (
        "request_digest",
        "route_content_digest_snapshot",
        "process_content_digest_snapshot",
        "voided_by_name",
        "void_reason",
    ):
        assert metadata[name][3:] == (1, "''", 0)
    assert db.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' "
        "AND name='idx_route_price_versions_idempotency'"
    ).fetchone()[0].endswith(
        "WHERE idempotency_key IS NOT NULL AND idempotency_key<>''"
    )
    assert rows_as_tuples(db, "route_price_versions", V073_PRICE_COLUMNS) == before_prices
    assert {
        "orders": rows_as_tuples(db, "orders", ("id", "route_id", "route_version_id")),
        "work": rows_as_tuples(
            db, "work_records", ("id", "order_id", "process_id", "process_version_id", "route_version_id")
        ),
        "detail": rows_as_tuples(
            db, "payroll_detail_lines", ("id", "work_record_id", "price_version_id", "route_version_id", "process_version_id")
        ),
        "resolution": rows_as_tuples(
            db, "payroll_work_price_resolutions", ("id", "work_record_id", "price_version_id")
        ),
    } == before_references
    assert [row["status"] for row in db.execute(
        "SELECT status FROM route_price_versions WHERE id IN (?,?,?) ORDER BY id", price_ids
    )] == ["draft", "approved", "retired"]
    assert [row["name"] for row in db.execute("PRAGMA table_info(master_data_release_member_events)")] == [
        "id", "batch_id", "action", "member_type", "member_id", "replacement_member_id",
        "actor_id", "actor_name", "reason", "idempotency_key", "created_at",
    ]
    assert [row["name"] for row in db.execute("PRAGMA table_info(route_price_reference_compat_audit)")] == [
        "id", "price_version_id", "published_route_content_digest",
        "published_process_content_digest", "price_route_content_digest_snapshot",
        "price_process_content_digest_snapshot", "mismatch", "detail_json", "observed_at",
    ]
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

    batch_id = db.execute(
        "INSERT INTO master_data_release_batches(release_no,revision_reason) VALUES ('V074-AUDIT','test')"
    ).lastrowid
    db.execute(
        "INSERT INTO master_data_release_member_events(batch_id,action,member_type,member_id,"
        "reason,idempotency_key) VALUES (?, 'added', 'price_version', ?, 'test', 'v074-member')",
        (batch_id, price_ids[0]),
    )
    db.execute(
        "INSERT INTO route_price_reference_compat_audit(price_version_id,mismatch,detail_json) "
        "VALUES (?,0,'{}')", (price_ids[0],)
    )
    db.commit()
    for table in ("master_data_release_member_events", "route_price_reference_compat_audit"):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(f"UPDATE {table} SET id=id WHERE id=1")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(f"DELETE FROM {table} WHERE id=1")

    null_price_id = db.execute(
        "INSERT INTO route_price_versions(route_id,route_version_id,process_id,process_version_id,"
        "normal_unit_price_micros,valid_from,status,remark) "
        "SELECT route_id,route_version_id,process_id,process_version_id,400000,"
        "'2026-09-01 07:00:00','draft','nullable-idempotency' "
        "FROM route_price_versions WHERE id=?",
        (price_ids[0],),
    ).lastrowid
    db.execute("UPDATE route_price_versions SET idempotency_key=NULL WHERE id=?", (price_ids[0],))
    db.execute("UPDATE route_price_versions SET idempotency_key=NULL WHERE id=?", (null_price_id,))
    db.execute("UPDATE route_price_versions SET voided_at=NULL WHERE id=?", (price_ids[0],))
    assert db.execute(
        "SELECT COUNT(*) FROM route_price_versions WHERE idempotency_key IS NULL"
    ).fetchone()[0] >= 2
    db.execute("UPDATE route_price_versions SET idempotency_key='v074-unique' WHERE id=?", (price_ids[0],))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE route_price_versions SET idempotency_key='v074-unique' WHERE id=?", (null_price_id,))


def test_v074_preserves_release_batch_price_members_during_price_table_rebuild():
    db = migrate_database_through(73)
    price_ids = seed_price_lifecycles_with_references(db)
    batch_id = db.execute(
        "INSERT INTO master_data_release_batches(release_no,revision_reason) "
        "VALUES ('V074-PRICE-MEMBER','preserve exact member')"
    ).lastrowid
    member_id = db.execute(
        "INSERT INTO master_data_release_price_versions(batch_id,price_version_id) "
        "VALUES (?,?)",
        (batch_id, price_ids[0]),
    ).lastrowid
    before = db.execute(
        "SELECT id,batch_id,price_version_id FROM master_data_release_price_versions"
    ).fetchall()

    m074_pending_route_price_controls(db)

    assert db.execute(
        "SELECT id,batch_id,price_version_id FROM master_data_release_price_versions"
    ).fetchall() == before
    assert db.execute(
        "SELECT price_version_id FROM master_data_release_price_versions WHERE id=?",
        (member_id,),
    ).fetchone()[0] == price_ids[0]
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_v074_refuses_to_overwrite_unexpected_temporary_backup_table():
    db = seed_pending_price_binding(migrate_database_through(73))
    db.execute(
        "CREATE TABLE __v074_master_data_release_price_versions_backup "
        "(evidence TEXT NOT NULL)"
    )
    db.execute(
        "INSERT INTO __v074_master_data_release_price_versions_backup(evidence) "
        "VALUES ('preserve-me')"
    )

    with pytest.raises(MigrationInvariantError, match="temporary backup table already exists"):
        m074_pending_route_price_controls(db)

    assert db.execute(
        "SELECT evidence FROM __v074_master_data_release_price_versions_backup"
    ).fetchone()[0] == "preserve-me"


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


def test_v074_rejects_root_and_version_binding_mismatch():
    db = seed_pending_price_binding(migrate_database_through(73))
    mismatched_route_id = db.execute(
        "INSERT INTO process_routes(name,category,status,route_code,lifecycle_status) "
        "VALUES ('V074 错配路线','机加工','inactive','ROUTE-V074-MISMATCH','active')"
    ).lastrowid
    db.execute("DROP TRIGGER validate_price_version_binding_update")
    db.execute(
        "UPDATE route_price_versions SET route_id=? WHERE id=1",
        (mismatched_route_id,),
    )

    with pytest.raises(MigrationInvariantError, match=r"\b1\b"):
        m074_pending_route_price_controls(db)


def test_v074_rejects_duplicate_drafts_for_one_pending_node():
    db = seed_pending_price_binding(migrate_database_through(73), price_count=2)
    price_ids = [row[0] for row in db.execute("SELECT id FROM route_price_versions ORDER BY id")]

    with pytest.raises(MigrationInvariantError, match=rf"{price_ids[0]}.*{price_ids[1]}"):
        m074_pending_route_price_controls(db)


def test_v074_rejects_duplicate_drafts_for_pending_route_with_published_process():
    db = seed_pending_price_binding(migrate_database_through(73), price_count=2)
    process_version_id = db.execute(
        "SELECT process_version_id FROM route_price_versions WHERE id=1"
    ).fetchone()[0]
    db.execute("UPDATE process_versions SET status='published' WHERE id=?", (process_version_id,))
    assert db.execute("SELECT status FROM process_versions WHERE id=?", (process_version_id,)).fetchone()[0] == "published"
    price_ids = [row[0] for row in db.execute("SELECT id FROM route_price_versions ORDER BY id")]

    with pytest.raises(MigrationInvariantError, match=rf"{price_ids[0]}.*{price_ids[1]}"):
        m074_pending_route_price_controls(db)


def test_v074_rolls_back_all_schema_changes_after_post_rebuild_failure(monkeypatch):
    db = seed_pending_price_binding(migrate_database_through(73))
    db.execute("PRAGMA foreign_keys=ON")
    original_foreign_keys = db.execute("PRAGMA foreign_keys").fetchone()[0]
    original_price_sql = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='route_price_versions'"
    ).fetchone()[0]
    original_trigger_names = [
        row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='route_price_versions' ORDER BY name"
        )
    ]

    def fail_after_rebuild(_db):
        raise RuntimeError("injected v074 failure")

    monkeypatch.setattr(v074, "_create_member_event_table", fail_after_rebuild)
    with pytest.raises(RuntimeError, match="injected v074 failure"):
        m074_pending_route_price_controls(db)

    assert db.execute("PRAGMA foreign_keys").fetchone()[0] == original_foreign_keys
    assert db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='route_price_versions'"
    ).fetchone()[0] == original_price_sql
    assert V074_PRICE_COLUMNS.isdisjoint({
        row["name"] for row in db.execute("PRAGMA table_info(route_price_versions)")
    })
    assert db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='master_data_release_member_events'"
    ).fetchone() is None
    assert [row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='route_price_versions' ORDER BY name"
    )] == original_trigger_names


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
