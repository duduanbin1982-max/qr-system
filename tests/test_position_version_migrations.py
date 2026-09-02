import json
import sqlite3

import pytest


EXPECTED_TABLES = {
    "position_versions",
    "position_version_processes",
    "position_version_events",
    "position_lifecycle_requests",
    "position_version_migration_manifests",
    "position_version_migration_exceptions",
}

FACT_VERSION_COLUMNS = {
    "performance_assignment_history": "position_version_id",
    "performance_source_facts": "position_version_id",
    "performance_score_revisions": "position_version_id_snapshot",
    "work_records": "submit_position_version_id",
    "performance_position_target_versions": "position_version_id_snapshot",
}


def _v069_db():
    from modules.migrations import MIGRATIONS

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    for version, _, migration in MIGRATIONS:
        if version > 69:
            continue
        migration(db)
        db.execute(f"PRAGMA user_version={version}")
        db.commit()
    return db


def _names(db, object_type):
    return {
        row["name"]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type=?", (object_type,)
        ).fetchall()
    }


def _columns(db, table):
    return {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}


def _seed_legacy_position(db):
    process_id = db.execute(
        "INSERT INTO processes (process_code,name,description,category,seq_order,status,lifecycle_status) "
        "VALUES ('PROC-9001','岗位迁移工序','测试','机加工',9001,'active','active')"
    ).lastrowid
    position_id = db.execute(
        "INSERT INTO positions(name,description,status,updated_at) "
        "VALUES ('岗位迁移测试','迁移前描述','active','2026-08-19 08:00:00')"
    ).lastrowid
    db.execute(
        "INSERT INTO position_processes(position_id,process_id) VALUES (?,?)",
        (position_id, process_id),
    )
    user_id = db.execute(
        "INSERT INTO users(username,password,name,role,employee_no,status,position_id) "
        "VALUES ('position-v070-user','hash','岗位迁移员工','worker','POS-V070','active',?)",
        (position_id,),
    ).lastrowid
    db.execute(
        "INSERT INTO user_sessions(user_id,token,is_active,active_position_id) "
        "VALUES (?,'position-v070-session',1,?)",
        (user_id, position_id),
    )
    assignment_id = db.execute(
        "INSERT INTO performance_assignment_history ("
        "user_id,employee_name_snapshot,employee_no_snapshot,position_id,"
        "position_name_snapshot,valid_from,valid_to,source_type,source_key) "
        "VALUES (?,?,?,?,?,'2026-08-01 07:00:00','','application','position-v070-open')",
        (user_id, "岗位迁移员工", "POS-V070", position_id, "岗位迁移测试"),
    ).lastrowid
    target_id = db.execute(
        "INSERT INTO performance_position_target_versions ("
        "position_id,position_name_snapshot,target_output_qty,minimum_effective_work_days,"
        "effective_from_month,status) VALUES (?,?,100,15,'2026-08','draft')",
        (position_id, "岗位迁移测试"),
    ).lastrowid
    order_id = db.execute(
        "INSERT INTO orders(order_no,product_name,quantity,status) "
        "VALUES ('POSITION-V070-ORDER','迁移产品',1,'pending')"
    ).lastrowid
    work_record_id = db.execute(
        "INSERT INTO work_records(order_id,process_id,user_id,status,quantity,created_at) "
        "VALUES (?,?,?,'approved',1,'2026-08-19 10:00:00')",
        (order_id, process_id, user_id),
    ).lastrowid
    db.commit()
    return {
        "position_id": position_id,
        "process_id": process_id,
        "user_id": user_id,
        "assignment_id": assignment_id,
        "target_id": target_id,
        "work_record_id": work_record_id,
    }


def _version_counts(db):
    return {
        table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in EXPECTED_TABLES
    }


def test_v070_creates_position_v1_and_preserves_legacy_facts():
    from modules.migration_position_versioning import m070_position_versioning

    db = _v069_db()
    try:
        seeded = _seed_legacy_position(db)
        before = {
            "positions": db.execute("SELECT COUNT(*) FROM positions").fetchone()[0],
            "position_processes": db.execute(
                "SELECT COUNT(*) FROM position_processes"
            ).fetchone()[0],
            "work_records": db.execute("SELECT COUNT(*) FROM work_records").fetchone()[0],
            "work_quantity": db.execute(
                "SELECT COALESCE(SUM(quantity),0) FROM work_records"
            ).fetchone()[0],
        }

        m070_position_versioning(db)

        assert EXPECTED_TABLES <= _names(db, "table")
        assert {
            "position_code",
            "lifecycle_status",
            "current_effective_version_id",
            "row_version",
            "created_by",
            "retired_at",
        } <= _columns(db, "positions")
        for table, column in FACT_VERSION_COLUMNS.items():
            assert column in _columns(db, table)

        root = db.execute(
            "SELECT * FROM positions WHERE id=?", (seeded["position_id"],)
        ).fetchone()
        version = db.execute(
            "SELECT * FROM position_versions WHERE position_id=?",
            (seeded["position_id"],),
        ).fetchone()
        assert root["position_code"] == f"POS-{seeded['position_id']:04d}"
        assert root["lifecycle_status"] == "active"
        assert root["current_effective_version_id"] == version["id"]
        assert version["version"] == 1
        assert version["status"] == "published"
        assert version["name"] == root["name"] == "岗位迁移测试"
        assert version["legacy_baseline"] == 1
        assert version["prior_revision_unavailable"] == 1
        assert len(version["content_digest"]) == 64
        assert db.execute(
            "SELECT process_id FROM position_version_processes "
            "WHERE position_version_id=?",
            (version["id"],),
        ).fetchone()[0] == seeded["process_id"]

        old_assignment = db.execute(
            "SELECT valid_to,position_version_id FROM performance_assignment_history WHERE id=?",
            (seeded["assignment_id"],),
        ).fetchone()
        new_assignment = db.execute(
            "SELECT valid_from,valid_to,position_version_id,position_name_snapshot "
            "FROM performance_assignment_history WHERE user_id=? AND id<>? ORDER BY id DESC LIMIT 1",
            (seeded["user_id"], seeded["assignment_id"]),
        ).fetchone()
        assert old_assignment["valid_to"]
        assert old_assignment["position_version_id"] is None
        assert new_assignment["valid_from"] == old_assignment["valid_to"]
        assert new_assignment["valid_to"] == ""
        assert new_assignment["position_version_id"] == version["id"]
        assert new_assignment["position_name_snapshot"] == "岗位迁移测试"

        assert db.execute(
            "SELECT submit_position_version_id FROM work_records WHERE id=?",
            (seeded["work_record_id"],),
        ).fetchone()[0] is None
        assert db.execute(
            "SELECT position_version_id_snapshot FROM performance_position_target_versions WHERE id=?",
            (seeded["target_id"],),
        ).fetchone()[0] is None
        assert db.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == before["positions"]
        assert db.execute(
            "SELECT COUNT(*) FROM position_processes"
        ).fetchone()[0] == before["position_processes"]
        assert db.execute("SELECT COUNT(*) FROM work_records").fetchone()[0] == before["work_records"]
        assert db.execute(
            "SELECT COALESCE(SUM(quantity),0) FROM work_records"
        ).fetchone()[0] == before["work_quantity"]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []

        event = db.execute(
            "SELECT * FROM position_version_events WHERE position_id=?",
            (seeded["position_id"],),
        ).fetchone()
        assert event["event_type"] == "legacy_baseline_created"
        assert event["position_version_id"] == version["id"]
        assert json.loads(event["payload_json"])["prior_revision_unavailable"] == 1
        manifest = db.execute(
            "SELECT * FROM position_version_migration_manifests "
            "WHERE migration_key='v070:position-legacy-baseline'"
        ).fetchone()
        assert manifest["source_position_count"] == before["positions"]
        assert manifest["migrated_version_count"] == before["positions"]
        assert len(manifest["manifest_sha256"]) == 64
    finally:
        db.close()


def test_v070_indexes_immutability_root_guard_and_idempotent_replay():
    from modules.migration_position_versioning import m070_position_versioning

    db = _v069_db()
    try:
        seeded = _seed_legacy_position(db)
        m070_position_versioning(db)
        before = _version_counts(db)
        m070_position_versioning(db)
        m070_position_versioning(db)
        assert _version_counts(db) == before

        assert {
            "idx_position_versions_root_version",
            "idx_position_versions_one_published",
            "idx_position_versions_one_open",
            "idx_position_versions_idempotency",
            "idx_position_version_processes_unique",
            "idx_position_version_events_idempotency",
            "idx_position_lifecycle_one_pending",
        } <= _names(db, "index")

        version = db.execute(
            "SELECT * FROM position_versions WHERE position_id=?",
            (seeded["position_id"],),
        ).fetchone()
        version_process = db.execute(
            "SELECT id FROM position_version_processes WHERE position_version_id=?",
            (version["id"],),
        ).fetchone()[0]
        event_id = db.execute(
            "SELECT id FROM position_version_events WHERE position_id=?",
            (seeded["position_id"],),
        ).fetchone()[0]

        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "UPDATE position_versions SET name='覆盖' WHERE id=?", (version["id"],)
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "UPDATE position_version_processes SET seq_order=99 WHERE id=?",
                (version_process,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "DELETE FROM position_version_processes WHERE id=?", (version_process,)
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "UPDATE position_version_events SET reason='覆盖' WHERE id=?", (event_id,)
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "UPDATE positions SET position_code='POS-X' WHERE id=?",
                (seeded["position_id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="referenced"):
            db.execute("DELETE FROM positions WHERE id=?", (seeded["position_id"],))
    finally:
        db.close()


def test_v070_records_preflight_exception_before_version_schema_changes():
    from modules.migration_helpers import MigrationInvariantError
    from modules.migration_position_versioning import m070_position_versioning

    db = _v069_db()
    try:
        seeded = _seed_legacy_position(db)
        db.execute(
            "UPDATE positions SET status='legacy_unknown' WHERE id=?",
            (seeded["position_id"],),
        )
        db.commit()

        with pytest.raises(MigrationInvariantError, match="invalid_lifecycle_status"):
            m070_position_versioning(db)

        issue = db.execute(
            "SELECT entity_type,legacy_id,reason_code,blocking "
            "FROM position_version_migration_exceptions WHERE legacy_id=?",
            (seeded["position_id"],),
        ).fetchone()
        assert dict(issue) == {
            "entity_type": "position",
            "legacy_id": seeded["position_id"],
            "reason_code": "invalid_lifecycle_status",
            "blocking": 1,
        }
        assert "position_versions" not in _names(db, "table")
        assert "position_code" not in _columns(db, "positions")
        assert db.execute("PRAGMA user_version").fetchone()[0] == 69
    finally:
        db.close()
