import ast
import sqlite3
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_run_migrations_uses_supplied_connection():
    from modules import migrations

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        executed = migrations.run_migrations(db)
        assert executed == len(migrations.MIGRATIONS)
        assert db.execute("PRAGMA user_version").fetchone()[0] == migrations.LATEST_VERSION

        table_names = {
            row["name"]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "users" in table_names
        assert "board_sessions" in table_names
        assert "product_bom" in table_names
        assert "order_materials" in table_names
        assert "process_quality_evaluation_tasks" in table_names
        assert "process_quality_evaluations" in table_names
        assert "process_quality_evaluation_reviews" in table_names
        assert "quality_standards" in table_names
        assert "quality_inspection_plans" in table_names
        assert "quality_inspection_tasks" in table_names
        assert "quality_nonconformances" in table_names
        assert "quality_capa_records" in table_names
        assert "quality_supplier_inspections" in table_names
        assert "quality_gauges" in table_names
    finally:
        db.close()

def test_latest_version_matches_highest_registered_migration():
    from modules import migrations

    assert migrations.LATEST_VERSION == max(version for version, _, _ in migrations.MIGRATIONS)


def test_migration_registry_is_split_by_domain_without_duplicate_versions():
    from modules import migrations

    versions = [version for version, _, _ in migrations.MIGRATIONS]
    assert versions == [1, *range(13, 36)]
    assert len(versions) == len(set(versions))
    assert {migration_fn.__module__ for _, _, migration_fn in migrations.MIGRATIONS} == {
        "modules.migration_baseline",
        "modules.migration_auth",
        "modules.migration_core",
        "modules.migration_performance",
        "modules.migration_work_time",
        "modules.migration_order_completion",
        "modules.migration_process_quality",
        "modules.migration_quality_management",
    }
    assert len((PROJECT_ROOT / "modules" / "migrations.py").read_text(encoding="utf-8").splitlines()) < 100


def test_session_migration_deactivates_tokens_that_cannot_authenticate():
    from modules.migration_auth import m031_align_single_token_sessions

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, status TEXT, token TEXT)"
        )
        db.execute(
            "CREATE TABLE user_sessions (id INTEGER PRIMARY KEY, user_id INTEGER, token TEXT, is_active INTEGER)"
        )
        db.execute("INSERT INTO users VALUES (1, 'active', 'current-token')")
        db.executemany(
            "INSERT INTO user_sessions VALUES (?, 1, ?, ?)",
            [
                (1, "current-token", 1),
                (2, "stale-token", 1),
                (3, "old-inactive-token", 0),
            ],
        )

        m031_align_single_token_sessions(db)
        m031_align_single_token_sessions(db)

        assert [
            row["is_active"]
            for row in db.execute("SELECT is_active FROM user_sessions ORDER BY id").fetchall()
        ] == [1, 0, 0]
    finally:
        db.close()


def test_order_completion_migration_removes_only_legacy_extra_status():
    from modules.migration_order_completion import m032_remove_legacy_order_status_from_extra_fields

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, extra_fields TEXT)")
        db.executemany(
            "INSERT INTO orders (id, extra_fields) VALUES (?, ?)",
            [
                (1, '{"status":"pending","model":"A"}'),
                (2, '{"model":"B"}'),
                (3, 'invalid-json'),
            ],
        )

        m032_remove_legacy_order_status_from_extra_fields(db)
        m032_remove_legacy_order_status_from_extra_fields(db)

        values = [
            row["extra_fields"]
            for row in db.execute("SELECT extra_fields FROM orders ORDER BY id").fetchall()
        ]
        assert values == ['{"model":"A"}', '{"model":"B"}', 'invalid-json']
    finally:
        db.close()


def test_database_at_version_29_runs_all_pending_migrations():
    from modules import migrations

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        for version, _, migration_fn in sorted(migrations.MIGRATIONS):
            if version > 29:
                continue
            migration_fn(db)
            db.execute(f"PRAGMA user_version = {version}")
        db.execute("DROP INDEX IF EXISTS idx_wt_records_route_process")
        db.execute("DROP INDEX IF EXISTS idx_wt_records_standard_missing")
        db.execute("PRAGMA user_version = 29")
        db.commit()

        assert migrations.run_migrations(db) == 6
        assert db.execute("PRAGMA user_version").fetchone()[0] == 35
        index_names = {
            row["name"]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_wt_records_route_process" in index_names
        assert "idx_wt_records_standard_missing" in index_names
    finally:
        db.close()


def test_init_db_always_delegates_to_migration_runner(tmp_path, monkeypatch):
    from modules import db as db_module

    db_path = tmp_path / "version-30.db"
    db = sqlite3.connect(db_path)
    db.execute("PRAGMA user_version = 30")
    db.close()
    observed_versions = []

    def record_version(connection):
        observed_versions.append(
            connection.execute("PRAGMA user_version").fetchone()[0]
        )

    monkeypatch.setattr(db_module, "DB_PATH", str(db_path))
    monkeypatch.setattr(db_module, "run_migrations", record_version)

    db_module.init_db()

    assert observed_versions == [30]

def test_schema_compat_helper_creates_expected_compat_tables():
    from modules.migration_schema_compat import ensure_current_schema_compat

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        ensure_current_schema_compat(db)
        table_names = {
            row["name"]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "departments" in table_names
        assert "wage_snapshots" in table_names
        assert any(row[1] == "deleted_at" for row in db.execute("PRAGMA table_info(users)"))
    finally:
        db.close()

def test_material_migration_helper_creates_material_planning_tables():
    from modules.migration_materials import ensure_material_planning_tables

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        ensure_material_planning_tables(db)
        table_names = {
            row["name"]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "product_bom" in table_names
        assert "order_materials" in table_names
        index_names = {
            row["name"]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_product_bom_product" in index_names
        assert "idx_order_materials_order" in index_names
    finally:
        db.close()


def test_add_column_helper_is_explicit_and_idempotent():
    from modules.migration_helpers import add_column_if_missing

    db = sqlite3.connect(":memory:")
    try:
        assert add_column_if_missing(db, "missing", "value", "TEXT") is False
        db.execute("CREATE TABLE example (id INTEGER PRIMARY KEY)")
        assert add_column_if_missing(db, "example", "value", "TEXT DEFAULT ''") is True
        assert add_column_if_missing(db, "example", "value", "TEXT DEFAULT ''") is False
    finally:
        db.close()


def test_unique_index_failure_reports_existing_duplicate_data():
    from modules.migration_helpers import MigrationInvariantError, create_unique_index

    db = sqlite3.connect(":memory:")
    try:
        db.execute("CREATE TABLE example (id INTEGER PRIMARY KEY, code TEXT)")
        db.executemany("INSERT INTO example (code) VALUES (?)", [("DUP",), ("DUP",)])

        with pytest.raises(MigrationInvariantError, match=r"duplicate example\(code\) data"):
            create_unique_index(db, "idx_example_code", "example", "code")
    finally:
        db.close()


def test_failed_migration_does_not_advance_database_version(monkeypatch):
    from modules import migrations

    def broken_migration(db):
        db.execute("SELECT * FROM table_that_does_not_exist")

    monkeypatch.setattr(migrations, "MIGRATIONS", [(1, "intentional failure", broken_migration)])
    db = sqlite3.connect(":memory:")
    try:
        with pytest.raises(sqlite3.OperationalError, match="table_that_does_not_exist"):
            migrations.run_migrations(db)
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0
    finally:
        db.close()


def test_migration_modules_do_not_silently_swallow_exceptions():
    violations = []
    for path in sorted((PROJECT_ROOT / "modules").glob("migration*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                violations.append(f"{path.name}:{node.lineno}")
            if isinstance(node.type, ast.Name) and node.type.id == "Exception":
                if not any(isinstance(child, ast.Raise) for child in ast.walk(node)):
                    violations.append(f"{path.name}:{node.lineno}")

    assert violations == []
