import importlib.util
import json
import sqlite3
from pathlib import Path


def _load_maintenance_module():
    path = Path(__file__).parents[1] / "scripts" / "db-maintenance.py"
    spec = importlib.util.spec_from_file_location("db_maintenance", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_audit_outbox_publishes_idempotently():
    maintenance = _load_maintenance_module()
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE,
            user_id INTEGER,
            action TEXT NOT NULL,
            target_type TEXT,
            target_id INTEGER,
            detail TEXT,
            category TEXT,
            severity TEXT,
            mandatory INTEGER,
            schema_version INTEGER,
            redaction_version INTEGER,
            request_id TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE audit_event_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE NOT NULL,
            action TEXT NOT NULL,
            category TEXT NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '',
            next_retry_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            published_at TEXT
        );
        """
    )
    payload = {
        "event_id": "evt-1",
        "user_id": 7,
        "action": "save_settings",
        "target_type": "system",
        "target_id": 0,
        "detail": '{"changed_keys":["page_size"]}',
        "category": "system",
        "severity": "warning",
        "mandatory": 1,
        "schema_version": 1,
        "redaction_version": 1,
        "request_id": "req-1",
    }
    conn.execute(
        "INSERT INTO audit_event_outbox(event_id,action,category,payload) VALUES(?,?,?,?)",
        ("evt-1", "save_settings", "system", json.dumps(payload)),
    )
    conn.commit()

    assert maintenance.publish_audit_outbox(conn) == {"published": 1, "failed": 0}
    assert maintenance.publish_audit_outbox(conn) == {"published": 0, "failed": 0}
    assert conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == 1
