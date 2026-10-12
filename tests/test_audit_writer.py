import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError

import pytest
from flask import g

from modules.audit_writer import AuditCommand, AuditWriter
from modules.db import get_db
from modules.db_unit_of_work import BaseService
from modules.middleware.audit import safe_audit_log


class FailingAuditPort:
    @staticmethod
    def insert_command(command, *, db):
        raise RuntimeError("audit unavailable")


def _setting_exists(db, key):
    return db.execute(
        "SELECT 1 FROM system_settings WHERE key=?",
        (key,),
    ).fetchone() is not None


def _create_audit_table(db):
    db.execute(
        "CREATE TABLE audit_logs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,event_id TEXT NOT NULL UNIQUE,"
        "user_id INTEGER,action TEXT NOT NULL,target_type TEXT,target_id INTEGER,"
        "detail TEXT,category TEXT,severity TEXT,mandatory INTEGER,"
        "schema_version INTEGER,redaction_version INTEGER,request_id TEXT)"
    )
    db.commit()


def test_audit_command_is_immutable_and_sanitizes_at_the_boundary():
    command = AuditCommand.create(
        1000,
        "save_settings",
        "system",
        0,
        {"changed_keys": ["smtp_password"], "smtp_password": "secret"},
        event_id="immutable-event",
        request_id="r" * 140,
    )

    assert command.event_id == "immutable-event"
    assert command.category == "system"
    assert command.mandatory == 1
    assert json.loads(command.detail)["smtp_password"] == "[REDACTED]"
    assert command.request_id == "r" * 140
    with pytest.raises(FrozenInstanceError):
        command.action = "changed"


def test_required_audit_failure_rolls_back_the_business_transaction(client):
    command = AuditCommand.create(1000, "save_settings", "system")

    with client.application.app_context():
        db = get_db()
        with pytest.raises(RuntimeError, match="audit unavailable"):
            with BaseService.transaction() as txn:
                txn.execute(
                    "INSERT INTO system_settings(key,value) VALUES(?,?)",
                    ("audit-required-rollback", "1"),
                )
                AuditWriter.required(command, db=txn, port=FailingAuditPort)

        assert not _setting_exists(db, "audit-required-rollback")


def test_best_effort_failure_rolls_back_only_its_savepoint(client, caplog):
    command = AuditCommand.create(1000, "legacy_event", "system")

    with client.application.app_context():
        db = get_db()
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "INSERT INTO system_settings(key,value) VALUES(?,?)",
            ("audit-best-effort-business", "1"),
        )

        assert AuditWriter.best_effort(
            command,
            db=db,
            port=FailingAuditPort,
        ) is None
        assert db.in_transaction
        db.commit()

        assert _setting_exists(db, "audit-best-effort-business")
        assert "best-effort audit write failed" in caplog.text


def test_request_audit_preserves_context_redaction_and_metadata(client):
    request_id = "request-" + "x" * 140
    with client.application.test_request_context(
        "/api/settings",
        headers={"X-Request-ID": request_id},
    ):
        g.current_user = {"id": 1000}
        event_row_id = safe_audit_log(
            "save_settings",
            "system",
            0,
            {"smtp_password": "top-secret", "changed_keys": ["smtp_password"]},
        )
        assert event_row_id is not None

        row = get_db().execute(
            "SELECT user_id,category,severity,mandatory,detail,request_id "
            "FROM audit_logs WHERE id=?",
            (event_row_id,),
        ).fetchone()
        assert dict(row) == {
            "user_id": 1000,
            "category": "system",
            "severity": "warning",
            "mandatory": 1,
            "detail": '{"changed_keys":["smtp_password"],"smtp_password":"[REDACTED]"}',
            "request_id": request_id[:120],
        }
        assert not get_db().in_transaction


def test_best_effort_concurrent_writes_are_complete(tmp_path):
    database = tmp_path / "audit-concurrency.db"
    setup = sqlite3.connect(database)
    setup.execute("PRAGMA journal_mode=WAL")
    _create_audit_table(setup)
    setup.close()

    def write_event(index):
        connection = sqlite3.connect(database, timeout=10)
        try:
            return AuditWriter.best_effort(
                AuditCommand.create(
                    1000,
                    "legacy_event",
                    "concurrency",
                    index,
                    {"sequence": index},
                    event_id=f"concurrent-{index}",
                ),
                db=connection,
            )
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(write_event, range(16)))

    verify = sqlite3.connect(database)
    try:
        assert all(result is not None for result in results)
        assert verify.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == 16
        assert verify.execute(
            "SELECT COUNT(DISTINCT event_id) FROM audit_logs"
        ).fetchone()[0] == 16
    finally:
        verify.close()
