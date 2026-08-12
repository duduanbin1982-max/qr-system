import json
import sqlite3

import pytest


EXPECTED_TABLES = {
    "process_versions",
    "process_route_versions",
    "process_route_version_items",
    "process_version_events",
    "process_route_version_events",
    "process_lifecycle_requests",
    "process_route_lifecycle_requests",
    "master_data_release_batches",
    "master_data_release_process_versions",
    "master_data_release_route_versions",
    "master_data_release_price_versions",
    "process_version_migration_manifests",
    "process_version_migration_exceptions",
}


def _legacy_db():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE processes (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            category TEXT DEFAULT '结构件',
            seq_order INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT '2026-01-01 08:00:00',
            updated_at TEXT DEFAULT ''
        );
        CREATE TABLE process_routes (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            category TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT '2026-01-01 08:00:00',
            updated_at TEXT DEFAULT ''
        );
        CREATE TABLE process_route_items (
            id INTEGER PRIMARY KEY,
            route_id INTEGER NOT NULL,
            process_id INTEGER NOT NULL,
            seq_order INTEGER DEFAULT 0,
            is_required INTEGER DEFAULT 1,
            required_audit INTEGER DEFAULT 0,
            FOREIGN KEY(route_id) REFERENCES process_routes(id),
            FOREIGN KEY(process_id) REFERENCES processes(id)
        );
        CREATE TABLE route_price_versions (
            id INTEGER PRIMARY KEY,
            route_id INTEGER NOT NULL,
            process_id INTEGER NOT NULL
        );
        INSERT INTO users(id,name) VALUES (10,'迁移制单人');
        INSERT INTO processes
            (id,name,description,category,seq_order,status,created_at)
        VALUES
            (1,'车削','车床加工','机加工',10,'active','2026-01-02 08:00:00'),
            (27,'包装','成品包装','包装',20,'inactive','2026-01-03 08:00:00');
        INSERT INTO process_routes
            (id,name,description,category,status,created_at)
        VALUES
            (3,'机加工路线','车削路线','机加工','active','2026-02-01 08:00:00'),
            (18,'包装路线','包装路线','包装','inactive','2026-02-02 08:00:00');
        INSERT INTO process_route_items
            (id,route_id,process_id,seq_order,is_required,required_audit)
        VALUES
            (31,3,1,1,1,1),
            (32,18,27,1,1,0);
        PRAGMA user_version=59;
        """
    )
    return db


def _names(db, object_type):
    return {
        row["name"]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type=?", (object_type,)
        ).fetchall()
    }


def _counts(db):
    tables = (
        "process_versions",
        "process_route_versions",
        "process_route_version_items",
        "process_version_events",
        "process_route_version_events",
        "process_version_migration_manifests",
    )
    return {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}


def test_v060_creates_versioned_process_schema_and_legacy_v1_baseline():
    from modules.migration_process_versioning import m060_process_master_versioning

    db = _legacy_db()
    try:
        m060_process_master_versioning(db)

        assert EXPECTED_TABLES.issubset(_names(db, "table"))
        process_columns = {row["name"] for row in db.execute("PRAGMA table_info(processes)")}
        route_columns = {row["name"] for row in db.execute("PRAGMA table_info(process_routes)")}
        assert {
            "process_code",
            "lifecycle_status",
            "current_effective_version_id",
            "row_version",
            "created_by",
        }.issubset(process_columns)
        assert {
            "route_code",
            "lifecycle_status",
            "current_effective_version_id",
            "row_version",
            "created_by",
        }.issubset(route_columns)

        processes = db.execute(
            "SELECT p.id,p.process_code,p.lifecycle_status,p.current_effective_version_id,"
            "v.version,v.process_code_snapshot,v.name,v.category,v.description,v.seq_order,"
            "v.status,v.legacy_baseline,v.prior_revision_unavailable "
            "FROM processes p JOIN process_versions v "
            "ON v.id=p.current_effective_version_id ORDER BY p.id"
        ).fetchall()
        assert [row["process_code"] for row in processes] == ["PROC-0001", "PROC-0027"]
        assert [row["version"] for row in processes] == [1, 1]
        assert [row["status"] for row in processes] == ["published", "retired"]
        assert [row["lifecycle_status"] for row in processes] == ["active", "retired"]
        assert all(row["process_code"] == row["process_code_snapshot"] for row in processes)
        assert all(row["legacy_baseline"] == 1 for row in processes)
        assert all(row["prior_revision_unavailable"] == 1 for row in processes)

        routes = db.execute(
            "SELECT r.id,r.route_code,r.name AS legacy_name,r.category AS legacy_category,"
            "r.description AS legacy_description,r.lifecycle_status,"
            "r.current_effective_version_id,v.version,v.route_code_snapshot,v.name,v.category,"
            "v.description,v.status,v.legacy_baseline,v.prior_revision_unavailable "
            "FROM process_routes r JOIN process_route_versions v "
            "ON v.id=r.current_effective_version_id ORDER BY r.id"
        ).fetchall()
        assert [row["route_code"] for row in routes] == ["ROUTE-0003", "ROUTE-0018"]
        assert [row["status"] for row in routes] == ["published", "retired"]
        assert all(row["legacy_name"] == row["name"] for row in routes)
        assert all(row["legacy_category"] == row["category"] for row in routes)
        assert all(row["legacy_description"] == row["description"] for row in routes)
        assert all(row["legacy_baseline"] == 1 for row in routes)
        assert all(row["prior_revision_unavailable"] == 1 for row in routes)

        item = db.execute(
            "SELECT item.route_version_id,item.process_id,item.process_version_id,"
            "item.seq_order,item.is_required,item.required_audit,pv.process_id AS version_process_id "
            "FROM process_route_version_items item "
            "JOIN process_versions pv ON pv.id=item.process_version_id "
            "WHERE item.legacy_route_item_id=31"
        ).fetchone()
        assert dict(item) == {
            "route_version_id": routes[0]["current_effective_version_id"],
            "process_id": 1,
            "process_version_id": processes[0]["current_effective_version_id"],
            "seq_order": 1,
            "is_required": 1,
            "required_audit": 1,
            "version_process_id": 1,
        }

        manifest = db.execute(
            "SELECT * FROM process_version_migration_manifests "
            "WHERE migration_key='v060:legacy-baseline'"
        ).fetchone()
        assert manifest["source_process_count"] == 2
        assert manifest["source_route_count"] == 2
        assert manifest["source_route_item_count"] == 2
        assert manifest["migrated_process_version_count"] == 2
        assert manifest["migrated_route_version_count"] == 2
        assert manifest["migrated_route_item_count"] == 2
        assert len(manifest["manifest_sha256"]) == 64
        assert json.loads(manifest["summary_json"])["legacy_baseline"] is True
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        db.close()


def test_v060_indexes_immutability_and_idempotent_replay():
    from modules.migration_process_versioning import m060_process_master_versioning

    db = _legacy_db()
    try:
        m060_process_master_versioning(db)
        before = _counts(db)
        m060_process_master_versioning(db)
        assert _counts(db) == before

        index_names = _names(db, "index")
        assert {
            "idx_process_versions_root_version",
            "idx_process_versions_one_published",
            "idx_process_versions_idempotency",
            "idx_route_versions_root_version",
            "idx_route_versions_one_published",
            "idx_route_versions_idempotency",
            "idx_route_version_items_sequence",
            "idx_process_version_events_idempotency",
            "idx_route_version_events_idempotency",
            "idx_master_data_release_idempotency",
        }.issubset(index_names)

        published_process = db.execute(
            "SELECT id FROM process_versions WHERE process_id=1"
        ).fetchone()[0]
        retired_process = db.execute(
            "SELECT id FROM process_versions WHERE process_id=27"
        ).fetchone()[0]
        published_route = db.execute(
            "SELECT id FROM process_route_versions WHERE process_route_id=3"
        ).fetchone()[0]
        route_item = db.execute(
            "SELECT id FROM process_route_version_items WHERE route_version_id=?",
            (published_route,),
        ).fetchone()[0]

        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE process_versions SET name='覆盖' WHERE id=?", (published_process,))
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE process_versions SET status='draft' WHERE id=?", (published_process,))
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("DELETE FROM process_versions WHERE id=?", (retired_process,))
        db.execute("UPDATE process_versions SET status='superseded' WHERE id=?", (published_process,))
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE process_versions SET category='覆盖' WHERE id=?", (published_process,))
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE process_route_version_items SET seq_order=9 WHERE id=?", (route_item,))
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("DELETE FROM process_route_version_items WHERE id=?", (route_item,))
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE process_route_versions SET status='draft' WHERE id=?", (published_route,))
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "INSERT INTO process_route_version_items "
                "(route_version_id,process_id,process_version_id,seq_order) VALUES (?,?,?,?)",
                (published_route, 27, retired_process, 2),
            )

        event_id = db.execute("SELECT id FROM process_version_events LIMIT 1").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE process_version_events SET reason='覆盖' WHERE id=?", (event_id,))
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("DELETE FROM process_version_events WHERE id=?", (event_id,))
    finally:
        db.close()


def test_v060_records_blocking_legacy_exception_before_schema_changes():
    from modules.migration_helpers import MigrationInvariantError
    from modules.migration_process_versioning import m060_process_master_versioning

    db = _legacy_db()
    try:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute(
            "INSERT INTO process_route_items "
            "(id,route_id,process_id,seq_order,is_required,required_audit) "
            "VALUES (99,3,9999,2,1,0)"
        )
        db.commit()

        with pytest.raises(MigrationInvariantError, match="blocking legacy exception"):
            m060_process_master_versioning(db)

        issue = db.execute(
            "SELECT entity_type,legacy_id,reason_code,blocking,source_summary_json "
            "FROM process_version_migration_exceptions WHERE legacy_id=99"
        ).fetchone()
        assert issue["entity_type"] == "process_route_item"
        assert issue["reason_code"] == "missing_process_root"
        assert issue["blocking"] == 1
        assert json.loads(issue["source_summary_json"])["process_id"] == 9999
        assert "process_versions" not in _names(db, "table")
        assert "process_code" not in {
            row["name"] for row in db.execute("PRAGMA table_info(processes)")
        }
    finally:
        db.close()
