import sqlite3

from modules.migration_audit import m066_audit_event_foundation


def _database():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT NOT NULL,
            target_type TEXT DEFAULT '',
            target_id INTEGER DEFAULT 0,
            detail TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE operation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            user_name TEXT DEFAULT '',
            action TEXT NOT NULL,
            target_type TEXT DEFAULT '',
            target_id INTEGER,
            detail TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    return db


def test_v066_redacts_and_converges_legacy_operation_logs():
    db = _database()
    db.execute(
        "INSERT INTO audit_logs(action,detail) VALUES(?,?)",
        ("save_settings", "smtp_password=old-secret"),
    )
    db.execute(
        "INSERT INTO operation_logs(action,target_type,target_id,detail) VALUES(?,?,?,?)",
        ("update_role", "role", 7, "changed"),
    )

    m066_audit_event_foundation(db)

    rows = db.execute(
        "SELECT event_id,category,detail FROM audit_logs ORDER BY id"
    ).fetchall()
    assert rows[0]["event_id"] == "legacy-1"
    assert rows[0]["category"] == "system"
    assert "old-secret" not in rows[0]["detail"]
    assert rows[1]["event_id"] == "operation-1"
    assert rows[1]["category"] == "permission"

    try:
        db.execute(
            "INSERT INTO operation_logs(action) VALUES('legacy_write')"
        )
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("operation_logs must be read-only after v066")


def test_v066_archive_is_immutable():
    db = _database()
    m066_audit_event_foundation(db)
    db.execute(
        "INSERT INTO audit_log_archive(archive_batch_id,source_id,event_id,payload) "
        "VALUES('batch',1,'event','{}')"
    )
    try:
        db.execute("DELETE FROM audit_log_archive")
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError("audit archive must reject deletion")
