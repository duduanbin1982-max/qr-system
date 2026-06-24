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
