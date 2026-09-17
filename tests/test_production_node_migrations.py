import sqlite3

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


@pytest.fixture
def migrated_v085_db():
    from modules.migrations import MIGRATIONS

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        for version, _, migrate in MIGRATIONS:
            if version > 75:
                break
            migrate(db)

        for sequence, process_name in enumerate(APPROVED_NODE_COUNTS, start=101):
            db.execute(
                "INSERT OR IGNORE INTO processes (name,description,seq_order,status) "
                "VALUES (?,?,?,'active')",
                (process_name, f"{process_name}生产节点", sequence),
            )

        for version, _, migrate in MIGRATIONS:
            if 76 <= version <= 85:
                migrate(db)
        db.commit()
        yield db
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

