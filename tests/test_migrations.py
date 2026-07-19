import sqlite3


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
    finally:
        db.close()

def test_latest_version_matches_highest_registered_migration():
    from modules import migrations

    assert migrations.LATEST_VERSION == max(version for version, _, _ in migrations.MIGRATIONS)


def test_database_at_version_29_runs_migration_30():
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

        assert migrations.run_migrations(db) == 1
        assert db.execute("PRAGMA user_version").fetchone()[0] == 30
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
