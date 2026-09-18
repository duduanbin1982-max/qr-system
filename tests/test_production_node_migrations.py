import json
import sqlite3
from inspect import unwrap

import pytest


APPROVED_NODE_COUNTS = {
    "下料": 1,
    "铆接": 4,
    "焊接": 10,
    "抛丸": 1,
    "打磨": 1,
    "镗孔": 2,
    "喷漆": 2,
}


def _build_v085_db(*, include_approved_processes):
    from modules.migrations import MIGRATIONS

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    for version, _, migrate in MIGRATIONS:
        if version > 75:
            break
        if version == 59 and not include_approved_processes:
            migrate = unwrap(migrate)
        migrate(db)

    if include_approved_processes:
        for sequence, process_name in enumerate(APPROVED_NODE_COUNTS, start=101):
            db.execute(
                "INSERT OR IGNORE INTO processes (name,description,seq_order,status) "
                "VALUES (?,?,?,'active')",
                (process_name, f"{process_name}生产节点", sequence),
            )

    for version, _, migrate in MIGRATIONS:
        if 76 <= version <= 85:
            migrate(db)
    db.execute("PRAGMA user_version=85")
    db.commit()
    return db


def _v086_tables(db):
    return {
        row["name"]
        for row in db.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name LIKE 'production_node%'"
        ).fetchall()
    }


@pytest.fixture
def migrated_v085_db():
    db = _build_v085_db(include_approved_processes=True)
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def incomplete_v085_db():
    db = _build_v085_db(include_approved_processes=False)
    try:
        yield db
    finally:
        db.close()


def _legacy_fact_fingerprint(db, table, row_id):
    additive_v087_columns = {
        "production_node_id",
        "node_code_snapshot",
        "node_name_snapshot",
        "capacity_mode_snapshot",
        "node_calendar_snapshot_json",
        "node_capability_snapshot_json",
        "locked",
        "lock_reason",
    }
    columns = [
        row["name"]
        for row in db.execute(f"PRAGMA table_info({table})").fetchall()
        if row["name"] not in additive_v087_columns
    ]
    row = db.execute(
        f"SELECT {','.join(columns)} FROM {table} WHERE id=?", (row_id,)
    ).fetchone()
    return json.dumps(
        [row[column] for column in columns],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _seed_v087_fact_set(db, *, suffix, process_line_id):
    line = db.execute(
        "SELECT process_id,calendar_id FROM process_production_lines WHERE id=?",
        (process_line_id,),
    ).fetchone()
    order_id = db.execute(
        "INSERT INTO orders (order_no,product_name,quantity,status,plan_start,plan_end) "
        "VALUES (?,?,?,?,?,?)",
        (
            f"V087-{suffix}",
            f"V087产品-{suffix}",
            7,
            "in_progress",
            "2026-09-18",
            "2026-09-19",
        ),
    ).lastrowid
    process_version_id = db.execute(
        "SELECT current_effective_version_id FROM processes WHERE id=?",
        (line["process_id"],),
    ).fetchone()[0]
    order_process_id = db.execute(
        "INSERT INTO order_processes "
        "(order_id,process_id,seq_order,status,process_version_id,process_name_snapshot) "
        "SELECT ?,id,1,'in_progress',?,name FROM processes WHERE id=?",
        (order_id, process_version_id, line["process_id"]),
    ).lastrowid
    standard_id = db.execute(
        "INSERT INTO work_time_standards "
        "(process_id,process_version_id,standard_minutes_per_unit,setup_minutes,"
        "difficulty_factor,effective_from,status,version,version_binding_source) "
        "VALUES (?,?,?,?,?,?,'active',7,?)",
        (
            line["process_id"],
            process_version_id,
            12.5,
            3.0,
            1.2,
            "2026-09-01",
            "captured",
        ),
    ).lastrowid
    schedule_run_id = db.execute(
        "INSERT INTO schedule_runs "
        "(schedule_run_key,order_id,status,requested_start_date,result_digest) "
        "VALUES (?,?, 'completed',?,?)",
        (
            f"v087-run-{suffix}",
            order_id,
            "2026-09-18",
            f"run-digest-{suffix}",
        ),
    ).lastrowid
    revision_id = db.execute(
        "INSERT INTO schedule_revisions "
        "(order_id,schedule_run_id,revision_no,status,source_run_key,result_digest) "
        "VALUES (?,?,1,'published',?,?)",
        (
            order_id,
            schedule_run_id,
            f"v087-run-{suffix}",
            f"revision-digest-{suffix}",
        ),
    ).lastrowid
    schedule_id = db.execute(
        "INSERT INTO order_process_schedules "
        "(order_id,order_process_id,process_id,process_version_id,process_line_id,"
        "seq_order,quantity,standard_id,standard_version,"
        "standard_minutes_per_unit,setup_minutes,difficulty_factor,planned_minutes,"
        "plan_start,plan_end,status,schedule_run_key,schedule_run_id,"
        "planned_start_at,planned_end_at,"
        "occupied_minutes,capacity_snapshot_json,standard_match_scope,calendar_id,"
        "shift_snapshot_json,line_name_snapshot,schedule_revision_id,"
        "completed_quantity_snapshot,rework_quantity_snapshot,"
        "remaining_quantity_snapshot,source_fact_digest,execution_mode) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            order_id,
            order_process_id,
            line["process_id"],
            process_version_id,
            process_line_id,
            1,
            7,
            standard_id,
            7,
            12.5,
            3.0,
            1.2,
            108.0,
            "2026-09-18",
            "2026-09-19",
            "in_progress",
            f"v087-run-{suffix}",
            schedule_run_id,
            "2026-09-18 08:00:00",
            "2026-09-18 09:48:00",
            108.0,
            f'{{"legacy":"capacity-{suffix}"}}',
            "exact_product",
            line["calendar_id"],
            f'[{{"legacy":"shift-{suffix}"}}]',
            f"旧产线快照-{suffix}",
            revision_id,
            2,
            1,
            6,
            f"source-fact-{suffix}",
            "internal",
        ),
    ).lastrowid
    segment_id = db.execute(
        "INSERT INTO order_process_schedule_segments "
        "(schedule_id,process_line_id,segment_start_at,segment_end_at,"
        "occupied_minutes,quantity) VALUES (?,?,?,?,?,?)",
        (
            schedule_id,
            process_line_id,
            "2026-09-18 08:00:00",
            "2026-09-18 09:48:00",
            108.0,
            7,
        ),
    ).lastrowid
    revision_item_id = db.execute(
        "INSERT INTO schedule_revision_items "
        "(revision_id,source_schedule_id,order_process_id,process_id,process_line_id,"
        "seq_order,quantity,status,planned_start_at,planned_end_at,occupied_minutes,"
        "payload_json,payload_digest,completed_quantity_snapshot,"
        "rework_quantity_snapshot,remaining_quantity_snapshot,source_fact_digest,"
        "execution_mode) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            revision_id,
            schedule_id,
            order_process_id,
            line["process_id"],
            process_line_id,
            1,
            7,
            "in_progress",
            "2026-09-18 08:00:00",
            "2026-09-18 09:48:00",
            108.0,
            f'{{"legacy":"payload-{suffix}"}}',
            f"payload-digest-{suffix}",
            2,
            1,
            6,
            f"source-fact-{suffix}",
            "internal",
        ),
    ).lastrowid
    downtime_id = db.execute(
        "INSERT INTO schedule_downtime_events "
        "(process_line_id,start_at,end_at,reason,status,source_type,source_id) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            process_line_id,
            "2026-09-18 10:00:00",
            "2026-09-18 10:30:00",
            f"旧停机-{suffix}",
            "completed",
            "manual",
            order_id,
        ),
    ).lastrowid
    db.commit()
    return {
        "schedule": schedule_id,
        "segment": segment_id,
        "revision_item": revision_item_id,
        "downtime": downtime_id,
    }


def _assert_v087_schema_absent(db):
    additive_columns = {
        "production_node_id",
        "node_code_snapshot",
        "node_name_snapshot",
        "capacity_mode_snapshot",
        "node_calendar_snapshot_json",
        "node_capability_snapshot_json",
        "locked",
        "lock_reason",
    }
    for table in ("order_process_schedules", "schedule_revision_items"):
        columns = {
            row["name"]
            for row in db.execute(f"PRAGMA table_info({table})").fetchall()
        }
        assert additive_columns.isdisjoint(columns)
    for table in ("order_process_schedule_segments", "schedule_downtime_events"):
        columns = {
            row["name"]
            for row in db.execute(f"PRAGMA table_info({table})").fetchall()
        }
        assert "production_node_id" not in columns
    assert db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='production_node_migration_differences'"
    ).fetchone() is None
    index_names = {
        row["name"]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
    }
    assert {
        "idx_schedule_facts_node_time",
        "idx_schedule_segments_node_time",
        "idx_schedule_revision_items_node",
        "idx_schedule_downtime_node_time",
    }.isdisjoint(index_names)


def _prepare_v086_failure_fixture(db, *, suffix):
    from modules.migration_production_nodes import m086_production_node_master

    m086_production_node_master(db)
    mapped = db.execute(
        "SELECT legacy_process_line_id FROM production_nodes ORDER BY id LIMIT 1"
    ).fetchone()
    ids = _seed_v087_fact_set(
        db,
        suffix=suffix,
        process_line_id=mapped["legacy_process_line_id"],
    )
    db.execute("PRAGMA user_version=86")
    db.commit()
    source_tables = {
        "schedule": "order_process_schedules",
        "segment": "order_process_schedule_segments",
        "revision_item": "schedule_revision_items",
        "downtime": "schedule_downtime_events",
    }
    fingerprints = {
        key: _legacy_fact_fingerprint(db, table, ids[key])
        for key, table in source_tables.items()
    }
    trigger_sql = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' "
        "AND name='protect_schedule_revision_items_update'"
    ).fetchone()[0]
    return ids, source_tables, fingerprints, trigger_sql


def _assert_v086_restored_after_v087_failure(
    db,
    *,
    ids,
    source_tables,
    fingerprints,
    trigger_sql,
):
    assert db.execute("PRAGMA user_version").fetchone()[0] == 86
    _assert_v087_schema_absent(db)
    assert {
        key: _legacy_fact_fingerprint(db, table, ids[key])
        for key, table in source_tables.items()
    } == fingerprints
    restored_trigger = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' "
        "AND name='protect_schedule_revision_items_update'"
    ).fetchone()
    assert restored_trigger is not None
    assert restored_trigger[0] == trigger_sql
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        db.execute(
            "UPDATE schedule_revision_items SET payload_digest='mutated' WHERE id=?",
            (ids["revision_item"],),
        )
    db.rollback()


def test_v086_rejects_null_legacy_calendar_before_creating_any_schema(
    migrated_v085_db,
):
    from modules.migration_production_nodes import m086_production_node_master

    legacy_line = migrated_v085_db.execute(
        "SELECT id FROM process_production_lines ORDER BY id LIMIT 1"
    ).fetchone()
    migrated_v085_db.execute(
        "UPDATE process_production_lines SET calendar_id=NULL WHERE id=?",
        (legacy_line["id"],),
    )
    migrated_v085_db.commit()

    with pytest.raises(RuntimeError, match=r"NULL calendar_id.*legacy ids"):
        m086_production_node_master(migrated_v085_db)

    assert _v086_tables(migrated_v085_db) == set()


def test_v086_rejects_incomplete_14_node_baseline_before_ddl(incomplete_v085_db):
    from modules.migration_production_nodes import m086_production_node_master

    assert incomplete_v085_db.execute(
        "SELECT COUNT(*) FROM process_production_lines"
    ).fetchone()[0] == 14

    with pytest.raises(RuntimeError, match=r"expected total=21.*actual total=14"):
        m086_production_node_master(incomplete_v085_db)

    assert _v086_tables(incomplete_v085_db) == set()


def test_v086_rejects_wrong_21_node_distribution_before_ddl(migrated_v085_db):
    from modules.migration_production_nodes import m086_production_node_master

    cutting_id = migrated_v085_db.execute(
        "SELECT id FROM processes WHERE name='下料'"
    ).fetchone()[0]
    welding_line_id = migrated_v085_db.execute(
        "SELECT pl.id FROM process_production_lines pl "
        "JOIN processes p ON p.id=pl.process_id "
        "WHERE p.name='焊接' ORDER BY pl.id LIMIT 1"
    ).fetchone()[0]
    migrated_v085_db.execute(
        "UPDATE process_production_lines SET process_id=? WHERE id=?",
        (cutting_id, welding_line_id),
    )
    migrated_v085_db.commit()

    with pytest.raises(RuntimeError, match=r"expected total=21.*actual total=21"):
        m086_production_node_master(migrated_v085_db)

    assert _v086_tables(migrated_v085_db) == set()


def test_v086_catalog_failure_keeps_version_85_and_leaves_no_partial_schema(
    migrated_v085_db,
):
    from modules import migrations

    legacy_line_id = migrated_v085_db.execute(
        "SELECT id FROM process_production_lines ORDER BY id LIMIT 1"
    ).fetchone()[0]
    migrated_v085_db.execute(
        "UPDATE process_production_lines SET calendar_id=NULL WHERE id=?",
        (legacy_line_id,),
    )
    migrated_v085_db.commit()

    with pytest.raises(RuntimeError, match=r"NULL calendar_id"):
        migrations.run_migrations(migrated_v085_db)

    assert migrated_v085_db.execute("PRAGMA user_version").fetchone()[0] == 85
    assert _v086_tables(migrated_v085_db) == set()


def test_test_template_reaches_v087_with_the_approved_21_node_baseline(tmp_path):
    from conftest import _create_schema_database

    database = tmp_path / "v086-template.db"
    _create_schema_database(str(database))
    db = sqlite3.connect(database)
    try:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 87
        assert db.execute("SELECT COUNT(*) FROM production_nodes").fetchone()[0] == 21
    finally:
        db.close()


def test_v070_replica_reaches_v087_with_complete_approved_process_versions():
    from modules import migrations

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        for version, _, migrate in migrations.MIGRATIONS:
            if version > 70:
                break
            if version == 59:
                migrate = unwrap(migrate)
            migrate(db)
            db.execute(f"PRAGMA user_version={version}")
            db.commit()

        migrations.run_migrations(db)

        approved = db.execute(
            "SELECT p.name,p.current_effective_version_id,v.process_id,v.status,"
            "v.legacy_baseline,v.prior_revision_unavailable "
            "FROM processes p "
            "LEFT JOIN process_versions v ON v.id=p.current_effective_version_id "
            "WHERE p.name IN ('下料','铆接','焊接','抛丸','打磨','镗孔','喷漆') "
            "ORDER BY p.name"
        ).fetchall()
        assert len(approved) == 7
        assert all(row["current_effective_version_id"] is not None for row in approved)
        assert all(row["process_id"] is not None for row in approved)
        assert {row["status"] for row in approved} == {"published"}
        assert {row["legacy_baseline"] for row in approved} == {1}
        assert {row["prior_revision_unavailable"] for row in approved} == {1}
        assert db.execute(
            "SELECT COUNT(*) FROM process_version_events e "
            "JOIN processes p ON p.id=e.entity_id "
            "WHERE p.name IN ('下料','铆接','焊接','抛丸','打磨','镗孔','喷漆') "
            "AND e.event_type='legacy_baseline_created'"
        ).fetchone()[0] == 7
        assert db.execute("PRAGMA user_version").fetchone()[0] == 87
        assert db.execute("SELECT COUNT(*) FROM production_nodes").fetchone()[0] == 21
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        db.close()


def test_v086_maps_each_process_line_to_one_stable_node(migrated_v085_db):
    from modules.migration_production_nodes import m086_production_node_master

    before = migrated_v085_db.execute(
        "SELECT COUNT(*) FROM process_production_lines"
    ).fetchone()[0]
    assert before == 21

    m086_production_node_master(migrated_v085_db)
    m086_production_node_master(migrated_v085_db)

    mapped = migrated_v085_db.execute(
        "SELECT COUNT(*) FROM production_nodes "
        "WHERE legacy_process_line_id IS NOT NULL"
    ).fetchone()[0]
    assert mapped == before
    assert migrated_v085_db.execute(
        "SELECT COUNT(*) FROM production_nodes WHERE capacity_mode<>'exclusive'"
    ).fetchone()[0] == 0
    assert migrated_v085_db.execute(
        "SELECT COUNT(*) FROM production_nodes n "
        "JOIN process_production_lines pl ON pl.id=n.legacy_process_line_id "
        "WHERE n.process_id<>pl.process_id OR n.node_code<>pl.line_code "
        "OR n.node_name<>pl.line_name OR n.status<>pl.status "
        "OR n.calendar_id<>pl.calendar_id"
    ).fetchone()[0] == 0


def test_v086_seeds_the_approved_21_node_distribution(migrated_v085_db):
    from modules.migration_production_nodes import m086_production_node_master

    m086_production_node_master(migrated_v085_db)

    distribution = {
        row["name"]: row["node_count"]
        for row in migrated_v085_db.execute(
            "SELECT p.name,COUNT(n.id) AS node_count "
            "FROM processes p JOIN production_nodes n ON n.process_id=p.id "
            "WHERE p.name IN ('下料','铆接','焊接','抛丸','打磨','镗孔','喷漆') "
            "GROUP BY p.id,p.name"
        ).fetchall()
    }
    assert distribution == APPROVED_NODE_COUNTS


def test_v086_capability_foreign_keys_restrict_master_data_deletes(
    migrated_v085_db,
):
    from modules.migration_production_nodes import m086_production_node_master

    m086_production_node_master(migrated_v085_db)
    migrated_v085_db.commit()
    migrated_v085_db.execute("PRAGMA foreign_keys=ON")
    node = migrated_v085_db.execute(
        "SELECT id,process_id FROM production_nodes ORDER BY id LIMIT 1"
    ).fetchone()
    process = migrated_v085_db.execute(
        "SELECT process_code,name,category,description,seq_order "
        "FROM processes WHERE id=?",
        (node["process_id"],),
    ).fetchone()
    process_version_id = migrated_v085_db.execute(
        "INSERT INTO process_versions ("
        "process_id,version,process_code_snapshot,name,category,description,seq_order,status"
        ") VALUES (?,?,?,?,?,?,?,'draft')",
        (
            node["process_id"],
            99,
            process["process_code"],
            process["name"],
            process["category"],
            process["description"],
            process["seq_order"],
        ),
    ).lastrowid
    route_id = migrated_v085_db.execute(
        "INSERT INTO process_routes(name,status) VALUES ('节点能力删除保护路线','active')"
    ).lastrowid
    route_version_id = migrated_v085_db.execute(
        "INSERT INTO process_route_versions ("
        "process_route_id,version,route_code_snapshot,name,status"
        ") VALUES (?,1,'NODE-CAPABILITY-ROUTE','节点能力删除保护路线','draft')",
        (route_id,),
    ).lastrowid
    product_id = migrated_v085_db.execute(
        "INSERT INTO products(product_name,product_code) "
        "VALUES ('节点能力删除保护产品','NODE-CAPABILITY-PRODUCT')"
    ).lastrowid
    migrated_v085_db.execute(
        "INSERT INTO production_node_capabilities ("
        "production_node_id,product_id,route_version_id,process_version_id"
        ") VALUES (?,?,?,?)",
        (node["id"], product_id, route_version_id, process_version_id),
    )
    migrated_v085_db.commit()
    assert migrated_v085_db.execute("PRAGMA foreign_keys").fetchone()[0] == 1

    foreign_keys = {
        (row["from"], row["table"], row["to"], row["on_delete"])
        for row in migrated_v085_db.execute(
            "PRAGMA foreign_key_list(production_node_capabilities)"
        ).fetchall()
    }
    assert {
        ("product_id", "products", "id", "RESTRICT"),
        ("route_version_id", "process_route_versions", "id", "RESTRICT"),
        ("process_version_id", "process_versions", "id", "RESTRICT"),
    }.issubset(foreign_keys)

    for table, identity in (
        ("products", product_id),
        ("process_route_versions", route_version_id),
        ("process_versions", process_version_id),
    ):
        with pytest.raises(sqlite3.IntegrityError):
            migrated_v085_db.execute(f"DELETE FROM {table} WHERE id=?", (identity,))

    assert migrated_v085_db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_v086_node_calendars_retain_540_effective_minutes(migrated_v085_db):
    from modules.migration_production_nodes import m086_production_node_master

    m086_production_node_master(migrated_v085_db)

    calendar_minutes = migrated_v085_db.execute(
        "SELECT n.id,SUM(s.end_minute-s.start_minute) AS effective_minutes "
        "FROM production_nodes n "
        "JOIN schedule_shifts s ON s.calendar_id=n.calendar_id AND s.status='active' "
        "GROUP BY n.id"
    ).fetchall()
    assert len(calendar_minutes) == 21
    assert {row["effective_minutes"] for row in calendar_minutes} == {540}
    assert {
        tuple(row)
        for row in migrated_v085_db.execute(
            "SELECT start_minute,end_minute FROM schedule_shifts "
            "WHERE shift_code IN ('DAY-AM','DAY-PM') ORDER BY start_minute"
        ).fetchall()
    } == {(480, 720), (780, 1080)}


def test_v086_creates_constrained_additive_node_schema(migrated_v085_db):
    from modules.migration_production_nodes import m086_production_node_master

    m086_production_node_master(migrated_v085_db)

    tables = {
        row["name"]
        for row in migrated_v085_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {
        "production_nodes",
        "production_node_capabilities",
        "production_node_calendar_overrides",
        "production_node_audit_events",
        "production_lines",
        "process_production_lines",
    }.issubset(tables)

    node_columns = {
        row["name"]
        for row in migrated_v085_db.execute(
            "PRAGMA table_info(production_nodes)"
        ).fetchall()
    }
    assert node_columns == {
        "id",
        "process_id",
        "node_code",
        "node_name",
        "capacity_mode",
        "status",
        "calendar_id",
        "legacy_process_line_id",
        "row_version",
        "created_at",
        "updated_at",
    }

    index_names = {
        row["name"]
        for row in migrated_v085_db.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
    }
    assert {
        "idx_production_nodes_process_status",
        "idx_production_node_capabilities_lookup",
        "idx_production_node_overrides_time",
        "idx_production_node_audit_node_time",
    }.issubset(index_names)

    node = migrated_v085_db.execute(
        "SELECT * FROM production_nodes ORDER BY id LIMIT 1"
    ).fetchone()
    with pytest.raises(sqlite3.IntegrityError):
        migrated_v085_db.execute(
            "UPDATE production_nodes SET capacity_mode='parallel' WHERE id=?",
            (node["id"],),
        )
    with pytest.raises(sqlite3.IntegrityError):
        migrated_v085_db.execute(
            "UPDATE production_nodes SET row_version=0 WHERE id=?",
            (node["id"],),
        )
    with pytest.raises(sqlite3.IntegrityError):
        migrated_v085_db.execute(
            "INSERT INTO production_nodes "
            "(process_id,node_code,node_name,calendar_id,legacy_process_line_id) "
            "VALUES (?,?,?,?,?)",
            (
                node["process_id"],
                "DUPLICATE-LEGACY",
                "重复旧产线",
                node["calendar_id"],
                node["legacy_process_line_id"],
            ),
        )

    migrated_v085_db.execute(
        "INSERT INTO production_node_audit_events "
        "(production_node_id,event_type,idempotency_key) VALUES (?,?,?)",
        (node["id"], "created", "node-audit-once"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        migrated_v085_db.execute(
            "INSERT INTO production_node_audit_events "
            "(production_node_id,event_type,idempotency_key) VALUES (?,?,?)",
            (node["id"], "created", "node-audit-once"),
        )
    with pytest.raises(sqlite3.IntegrityError):
        migrated_v085_db.execute(
            "INSERT INTO production_node_calendar_overrides "
            "(production_node_id,start_at,end_at,override_type) VALUES (?,?,?,?)",
            (node["id"], "2026-09-17 12:00", "2026-09-17 11:00", "maintenance"),
        )


def test_v087_backfills_only_exact_legacy_mappings_without_changing_business_facts(
    migrated_v085_db,
):
    from modules.migration_production_nodes import (
        m086_production_node_master,
        m087_production_node_schedule_facts,
    )

    m086_production_node_master(migrated_v085_db)
    mapped = migrated_v085_db.execute(
        "SELECT id,legacy_process_line_id,node_code,node_name,capacity_mode,calendar_id "
        "FROM production_nodes ORDER BY id LIMIT 1"
    ).fetchone()
    ids = _seed_v087_fact_set(
        migrated_v085_db,
        suffix="mapped",
        process_line_id=mapped["legacy_process_line_id"],
    )
    source_tables = {
        "schedule": "order_process_schedules",
        "segment": "order_process_schedule_segments",
        "revision_item": "schedule_revision_items",
        "downtime": "schedule_downtime_events",
    }
    before = {
        key: _legacy_fact_fingerprint(migrated_v085_db, table, ids[key])
        for key, table in source_tables.items()
    }

    m087_production_node_schedule_facts(migrated_v085_db)
    m087_production_node_schedule_facts(migrated_v085_db)

    after = {
        key: _legacy_fact_fingerprint(migrated_v085_db, table, ids[key])
        for key, table in source_tables.items()
    }
    assert after == before

    schedule = migrated_v085_db.execute(
        "SELECT production_node_id,node_code_snapshot,node_name_snapshot,"
        "capacity_mode_snapshot,node_calendar_snapshot_json,"
        "node_capability_snapshot_json,locked,lock_reason "
        "FROM order_process_schedules WHERE id=?",
        (ids["schedule"],),
    ).fetchone()
    revision_item = migrated_v085_db.execute(
        "SELECT production_node_id,node_code_snapshot,node_name_snapshot,"
        "capacity_mode_snapshot,node_calendar_snapshot_json,"
        "node_capability_snapshot_json,locked,lock_reason "
        "FROM schedule_revision_items WHERE id=?",
        (ids["revision_item"],),
    ).fetchone()
    expected_identity = (
        mapped["id"],
        mapped["node_code"],
        mapped["node_name"],
        mapped["capacity_mode"],
    )
    assert tuple(schedule[:4]) == expected_identity
    assert tuple(revision_item[:4]) == expected_identity
    assert schedule["locked"] == revision_item["locked"] == 0
    assert schedule["lock_reason"] == revision_item["lock_reason"] == ""
    for fact in (schedule, revision_item):
        calendar = json.loads(fact["node_calendar_snapshot_json"])
        assert calendar["calendar_id"] == mapped["calendar_id"]
        assert [(shift["start_minute"], shift["end_minute"]) for shift in calendar["shifts"]] == [
            (480, 720),
            (780, 1080),
        ]
        assert json.loads(fact["node_capability_snapshot_json"]) == []

    assert migrated_v085_db.execute(
        "SELECT production_node_id FROM order_process_schedule_segments WHERE id=?",
        (ids["segment"],),
    ).fetchone()[0] == mapped["id"]
    assert migrated_v085_db.execute(
        "SELECT production_node_id FROM schedule_downtime_events WHERE id=?",
        (ids["downtime"],),
    ).fetchone()[0] == mapped["id"]
    assert migrated_v085_db.execute(
        "SELECT COUNT(*) FROM production_node_migration_differences"
    ).fetchone()[0] == 0


def test_v087_records_unmapped_legacy_facts_without_guessing_by_process(
    migrated_v085_db,
):
    from modules.migration_production_nodes import (
        m086_production_node_master,
        m087_production_node_schedule_facts,
    )

    m086_production_node_master(migrated_v085_db)
    mapped = migrated_v085_db.execute(
        "SELECT process_id,calendar_id FROM production_nodes ORDER BY id LIMIT 1"
    ).fetchone()
    unmapped_line_id = migrated_v085_db.execute(
        "INSERT INTO process_production_lines "
        "(process_id,line_code,line_name,daily_minutes,status,calendar_id,remark) "
        "VALUES (?,?,?,?,?,?,?)",
        (
            mapped["process_id"],
            "LEGACY-UNMAPPED-99",
            "同工序但未映射的旧产线",
            540,
            "active",
            mapped["calendar_id"],
            "V087差异测试",
        ),
    ).lastrowid
    ids = _seed_v087_fact_set(
        migrated_v085_db,
        suffix="unmapped",
        process_line_id=unmapped_line_id,
    )

    m087_production_node_schedule_facts(migrated_v085_db)
    m087_production_node_schedule_facts(migrated_v085_db)

    assert migrated_v085_db.execute(
        "SELECT production_node_id FROM order_process_schedules WHERE id=?",
        (ids["schedule"],),
    ).fetchone()[0] is None
    assert migrated_v085_db.execute(
        "SELECT production_node_id FROM order_process_schedule_segments WHERE id=?",
        (ids["segment"],),
    ).fetchone()[0] is None
    assert migrated_v085_db.execute(
        "SELECT production_node_id FROM schedule_revision_items WHERE id=?",
        (ids["revision_item"],),
    ).fetchone()[0] is None
    assert migrated_v085_db.execute(
        "SELECT production_node_id FROM schedule_downtime_events WHERE id=?",
        (ids["downtime"],),
    ).fetchone()[0] is None

    differences = migrated_v085_db.execute(
        "SELECT source_table,source_id,legacy_process_line_id,difference_code,detail_json "
        "FROM production_node_migration_differences ORDER BY source_table,source_id"
    ).fetchall()
    assert {
        (row["source_table"], row["source_id"])
        for row in differences
    } == {
        ("order_process_schedules", ids["schedule"]),
        ("order_process_schedule_segments", ids["segment"]),
        ("schedule_revision_items", ids["revision_item"]),
        ("schedule_downtime_events", ids["downtime"]),
    }
    assert {row["legacy_process_line_id"] for row in differences} == {unmapped_line_id}
    assert {row["difference_code"] for row in differences} == {"missing_mapping"}
    assert all(
        json.loads(row["detail_json"])["mapping_key"]
        == "production_nodes.legacy_process_line_id"
        for row in differences
    )
    assert len(differences) == 4


def test_v087_adds_node_fact_columns_and_rebuilds_complete_immutable_trigger(
    migrated_v085_db,
):
    from modules.migration_production_nodes import (
        m086_production_node_master,
        m087_production_node_schedule_facts,
    )

    m086_production_node_master(migrated_v085_db)
    mapped = migrated_v085_db.execute(
        "SELECT id,legacy_process_line_id FROM production_nodes ORDER BY id LIMIT 1"
    ).fetchone()
    ids = _seed_v087_fact_set(
        migrated_v085_db,
        suffix="immutable",
        process_line_id=mapped["legacy_process_line_id"],
    )

    m087_production_node_schedule_facts(migrated_v085_db)

    schedule_columns = {
        row["name"]
        for row in migrated_v085_db.execute(
            "PRAGMA table_info(order_process_schedules)"
        ).fetchall()
    }
    revision_columns = {
        row["name"]
        for row in migrated_v085_db.execute(
            "PRAGMA table_info(schedule_revision_items)"
        ).fetchall()
    }
    snapshot_columns = {
        "production_node_id",
        "node_code_snapshot",
        "node_name_snapshot",
        "capacity_mode_snapshot",
        "node_calendar_snapshot_json",
        "node_capability_snapshot_json",
        "locked",
        "lock_reason",
    }
    assert snapshot_columns.issubset(schedule_columns)
    assert snapshot_columns.issubset(revision_columns)
    for table in ("order_process_schedule_segments", "schedule_downtime_events"):
        assert "production_node_id" in {
            row["name"]
            for row in migrated_v085_db.execute(
                f"PRAGMA table_info({table})"
            ).fetchall()
        }
    assert migrated_v085_db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' "
        "AND name='idx_node_migration_differences_source'"
    ).fetchone() is None

    trigger_sql = migrated_v085_db.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' "
        "AND name='protect_schedule_revision_items_update'"
    ).fetchone()[0]
    for column in (
        "payload_json",
        "payload_digest",
        "source_fact_digest",
        *sorted(snapshot_columns),
    ):
        assert column in trigger_sql

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        migrated_v085_db.execute(
            "UPDATE schedule_revision_items SET payload_digest='changed' WHERE id=?",
            (ids["revision_item"],),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        migrated_v085_db.execute(
            "UPDATE schedule_revision_items SET production_node_id=NULL WHERE id=?",
            (ids["revision_item"],),
        )
    assert migrated_v085_db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_v087_runner_failure_rolls_back_all_schema_facts_and_trigger_changes(
    migrated_v085_db,
    monkeypatch,
):
    from modules import migration_production_nodes, migrations

    ids, source_tables, fingerprints, trigger_sql = _prepare_v086_failure_fixture(
        migrated_v085_db,
        suffix="runner-rollback",
    )

    def fail_trigger_rebuild(_db):
        raise RuntimeError("injected V087 trigger rebuild failure")

    monkeypatch.setattr(
        migration_production_nodes,
        "_create_revision_item_immutability_trigger",
        fail_trigger_rebuild,
    )

    with pytest.raises(RuntimeError, match="injected V087 trigger rebuild failure"):
        migrations.run_migrations(migrated_v085_db)

    _assert_v086_restored_after_v087_failure(
        migrated_v085_db,
        ids=ids,
        source_tables=source_tables,
        fingerprints=fingerprints,
        trigger_sql=trigger_sql,
    )


def test_v087_direct_failure_can_be_fully_restored_by_caller_rollback(
    migrated_v085_db,
    monkeypatch,
):
    from modules import migration_production_nodes

    ids, source_tables, fingerprints, trigger_sql = _prepare_v086_failure_fixture(
        migrated_v085_db,
        suffix="caller-rollback",
    )

    def fail_trigger_rebuild(_db):
        raise RuntimeError("injected direct V087 trigger rebuild failure")

    monkeypatch.setattr(
        migration_production_nodes,
        "_create_revision_item_immutability_trigger",
        fail_trigger_rebuild,
    )

    with pytest.raises(RuntimeError, match="injected direct V087 trigger rebuild failure"):
        migration_production_nodes.m087_production_node_schedule_facts(
            migrated_v085_db
        )

    assert migrated_v085_db.in_transaction is True
    migrated_v085_db.rollback()
    _assert_v086_restored_after_v087_failure(
        migrated_v085_db,
        ids=ids,
        source_tables=source_tables,
        fingerprints=fingerprints,
        trigger_sql=trigger_sql,
    )
