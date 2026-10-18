import sqlite3

import pytest

from modules.repositories.performance_fact_repository import PerformanceFactRepository
from modules.repositories.performance_history_migration_repository import (
    PerformanceHistoryMigrationRepository,
)
from modules.repositories.performance_ledger_repository import PerformanceLedgerRepository


class _ConnectionGuard:
    def __init__(self, connection):
        self.connection = connection
        self.executed = []

    def execute(self, *args, **kwargs):
        self.executed.append((args, kwargs))
        return self.connection.execute(*args, **kwargs)

    def commit(self):
        raise AssertionError("repository methods must not commit")

    def rollback(self):
        raise AssertionError("repository methods must not roll back")


class _FailingConnection:
    def execute(self, *args, **kwargs):
        raise sqlite3.IntegrityError("fixture constraint")


def _connection():
    connection = sqlite3.connect(":memory:")
    connection.execute(
        "CREATE TABLE performance_batches ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "production_month TEXT NOT NULL, version INTEGER NOT NULL"
        ")"
    )
    connection.execute(
        "CREATE TABLE performance_data_exceptions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id INTEGER, user_id INTEGER,"
        "exception_type TEXT NOT NULL, source_type TEXT, source_id INTEGER,"
        "status TEXT NOT NULL, snapshot_json TEXT NOT NULL"
        ",UNIQUE(batch_id, exception_type, source_type, source_id)"
        ")"
    )
    connection.execute(
        "INSERT INTO performance_batches (production_month,version) VALUES (?,?)",
        ("2026-10", 1),
    )
    return connection


def test_history_version_delegate_preserves_connection_and_version_rule():
    connection = _connection()
    guarded = _ConnectionGuard(connection)

    assert PerformanceHistoryMigrationRepository.next_version("2026-10", guarded) == 2
    assert len(guarded.executed) == 1


def test_exception_delegates_preserve_defaults_and_do_not_commit():
    connection = _connection()
    guarded = _ConnectionGuard(connection)
    historical_payload = {
        "source_type": "quality_event",
        "source_id": 11,
        "snapshot_json": '{"source_id":11}',
    }
    batch_payload = {
        "batch_id": 7,
        "user_id": 12,
        "exception_type": "missing_work_time",
    }

    historical_id = PerformanceHistoryMigrationRepository.insert_historical_quality_ambiguity(
        historical_payload,
        guarded,
    )
    batch_id = PerformanceLedgerRepository.insert_exception(batch_payload, guarded)
    duplicate_id = PerformanceFactRepository.insert_batch_exception(batch_payload, guarded)

    rows = connection.execute(
        "SELECT id,batch_id,user_id,exception_type,source_type,source_id,status,snapshot_json "
        "FROM performance_data_exceptions ORDER BY id"
    ).fetchall()
    assert historical_id == rows[0][0]
    assert batch_id == rows[1][0]
    assert duplicate_id == batch_id
    assert len(rows) == 2
    assert rows[0][1:] == (
        None,
        None,
        "ambiguous_quality_source",
        "quality_event",
        11,
        "pending",
        '{"source_id":11}',
    )
    assert rows[1][1:] == (7, 12, "missing_work_time", "", 0, "pending", "{}")


def test_fact_owner_keeps_database_errors_unchanged():
    batch_payload = {
        "batch_id": 7,
        "exception_type": "missing_work_time",
    }
    historical_payload = {
        "source_type": "quality_event",
        "source_id": 11,
        "snapshot_json": "{}",
    }

    for operation in (
        lambda: PerformanceFactRepository.insert_batch_exception(
            batch_payload, _FailingConnection()
        ),
        lambda: PerformanceLedgerRepository.insert_exception(
            batch_payload, _FailingConnection()
        ),
        lambda: PerformanceHistoryMigrationRepository.insert_historical_quality_ambiguity(
            historical_payload, _FailingConnection()
        ),
    ):
        with pytest.raises(sqlite3.IntegrityError, match="fixture constraint"):
            operation()
