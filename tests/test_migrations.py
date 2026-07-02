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
