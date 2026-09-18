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


def test_test_template_reaches_v086_with_the_approved_21_node_baseline(tmp_path):
    from conftest import _create_schema_database

    database = tmp_path / "v086-template.db"
    _create_schema_database(str(database))
    db = sqlite3.connect(database)
    try:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 86
        assert db.execute("SELECT COUNT(*) FROM production_nodes").fetchone()[0] == 21
    finally:
        db.close()


def test_v070_replica_reaches_v086_with_complete_approved_process_versions():
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
        assert db.execute("PRAGMA user_version").fetchone()[0] == 86
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
