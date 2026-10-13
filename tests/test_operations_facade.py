"""Contracts for the stable operations facade used by scripts."""

import sqlite3
import hashlib
import subprocess
import sys
from dataclasses import FrozenInstanceError

import pytest

from modules.application.operations_facade import OperationsFacade
from modules.migrations import run_migrations


def test_migration_plan_is_read_only_and_returns_stable_dto(tmp_path):
    database = tmp_path / "operations-plan.db"
    connection = sqlite3.connect(database)
    try:
        run_migrations(connection)
    finally:
        connection.close()

    before = sqlite3.connect(database).execute("PRAGMA user_version").fetchone()[0]
    result = OperationsFacade.migration_plan(database)
    after = sqlite3.connect(database).execute("PRAGMA user_version").fetchone()[0]

    assert result["connection_mode"] == "read-only"
    assert result["quick_check"] == "ok"
    assert result["current_version"] == before == after
    assert result["pending"] == []


def test_schedule_preflight_preserves_read_only_source_and_coverage_shape(tmp_path):
    from scripts.preflight_schedule_precision import run_preflight

    source = tmp_path / "precision-source.db"
    connection = sqlite3.connect(source)
    try:
        run_migrations(connection)
        before_version = connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()

    result = run_preflight(source, limit=3)
    check = sqlite3.connect(source)
    try:
        after_version = check.execute("PRAGMA user_version").fetchone()[0]
    finally:
        check.close()

    assert before_version == after_version == 96
    assert result["work_time_coverage"]["operation_count"] == 0
    assert result["work_time_coverage"]["missing_standard_operation_count"] == 0


def test_e2e_schema_facade_restores_migration_catalog():
    from modules import migrations

    connection = sqlite3.connect(":memory:")
    catalog = migrations.MIGRATIONS
    OperationsFacade.prepare_e2e_schema(connection)
    assert migrations.MIGRATIONS is catalog
    assert connection.execute("PRAGMA user_version").fetchone()[0] < 60
    OperationsFacade.migrate_database(connection)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == migrations.LATEST_VERSION
    connection.close()


def test_importing_facade_has_no_application_bootstrap_side_effects():
    subprocess.run([
        sys.executable, "-c",
        "import sys; from modules.application.operations_facade import OperationsFacade; "
        "assert 'modules.app' not in sys.modules; assert 'server' not in sys.modules; "
        "assert 'modules.config' not in sys.modules; assert 'modules.migrations' not in sys.modules",
    ], check=True)


def test_migration_steps_are_frozen_metadata_without_callbacks():
    steps = OperationsFacade.pending_migration_steps(94)
    assert [step.version for step in steps] == [95, 96]
    assert all(not hasattr(step, "callback") for step in steps)
    with pytest.raises(FrozenInstanceError):
        steps[0].version = 999


def test_scoped_flags_restore_nested_overrides_after_failure(monkeypatch):
    from modules import config

    monkeypatch.setattr(config, "PRODUCTION_NODE_ENGINE_ENABLED", False)
    with pytest.raises(RuntimeError, match="fixture"):
        with OperationsFacade.schedule_flags(PRODUCTION_NODE_ENGINE_ENABLED=True):
            assert config.PRODUCTION_NODE_ENGINE_ENABLED is True
            with OperationsFacade.schedule_flags(PRODUCTION_NODE_ENGINE_ENABLED=False):
                assert config.PRODUCTION_NODE_ENGINE_ENABLED is False
            assert config.PRODUCTION_NODE_ENGINE_ENABLED is True
            raise RuntimeError("fixture")
    assert config.PRODUCTION_NODE_ENGINE_ENABLED is False


def test_invalid_override_does_not_change_any_flag(monkeypatch):
    from modules import config

    monkeypatch.setattr(config, "PRODUCTION_NODE_ENGINE_ENABLED", False)
    with pytest.raises(ValueError):
        with OperationsFacade.schedule_flags(PRODUCTION_NODE_ENGINE_ENABLED=True, invalid=True):
            pytest.fail("invalid overrides must not enter")
    assert config.PRODUCTION_NODE_ENGINE_ENABLED is False


def _simple_database(path):
    with sqlite3.connect(path) as db:
        db.executescript("CREATE TABLE facts(id INTEGER PRIMARY KEY, value TEXT); INSERT INTO facts VALUES(1,'protected'); PRAGMA user_version=96;")


def test_replica_copy_captures_wal_data_without_touching_source(tmp_path):
    source, target = tmp_path / "source.db", tmp_path / "replica.db"
    _simple_database(source)
    writer = sqlite3.connect(source)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("INSERT INTO facts VALUES(2,'wal fact')")
        writer.commit()
        protected = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (source, tmp_path / "source.db-wal")}
        OperationsFacade.copy_database_replica(source, target)
        with sqlite3.connect(target) as copy:
            assert copy.execute("SELECT COUNT(*) FROM facts").fetchone()[0] == 2
        assert all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in protected.items())
    finally:
        writer.close()


def test_replica_copy_rejects_source_path_and_existing_target(tmp_path):
    source, target = tmp_path / "source.db", tmp_path / "target.db"
    _simple_database(source)
    target.write_bytes(b"existing evidence")
    with pytest.raises(ValueError, match="must differ"):
        OperationsFacade.copy_database_replica(source, source)
    with pytest.raises(FileExistsError):
        OperationsFacade.copy_database_replica(source, target)
    assert target.read_bytes() == b"existing evidence"


def test_deployment_and_rollback_checks_are_read_only_and_detect_drift(tmp_path):
    database, attachment = tmp_path / "facts.db", tmp_path / "document.pdf"
    _simple_database(database)
    attachment.write_bytes(b"attachment")
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    baseline = OperationsFacade.database_evidence(database)
    digest = hashlib.sha256(attachment.read_bytes()).hexdigest()
    commit = "a" * 40
    assert OperationsFacade.deployment_acceptance(database, expected_version=96,
        expected_commit=commit, health={"status": "ok", "db": "connected", "commit": commit})["ok"]
    assert not OperationsFacade.deployment_acceptance(database, expected_version=96,
        expected_commit=commit, health={"status": "ok", "db": "connected", "commit": "b" * 40})["ok"]
    assert OperationsFacade.rollback_check(database, baseline, attachments=((attachment, digest),))["ok"]
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    attachment.write_bytes(b"changed")
    assert not OperationsFacade.rollback_check(database, baseline, attachments=((attachment, digest),))["ok"]
    with sqlite3.connect(database) as db:
        db.execute("UPDATE facts SET value='new production fact' WHERE id=1")
    assert not OperationsFacade.rollback_check(database, baseline)["facts_unchanged"]


@pytest.mark.parametrize("operation", ["shadow_trial", "replica_replay"])
def test_isolated_schedule_operations_preserve_source_facts_and_return_detached_values(client, operation):
    from modules.db import get_db
    from test_production_node_shadow_scheduling import _seed_order

    with client.application.app_context():
        db = get_db()
        order_id, _ = _seed_order(db)
        actor_id = db.execute("SELECT id FROM users WHERE role='admin' LIMIT 1").fetchone()[0]
        source = db.execute("PRAGMA database_list").fetchone()[2]
        before = OperationsFacade.database_evidence(source)
        result = getattr(OperationsFacade, operation)(
            source, order_id=order_id, run_key=f"operations-{operation}",
            actor_id=actor_id, start_date="2026-09-19",
        )
        assert result["ok"] is True
        assert result["operations"]
        assert isinstance(result["operations"][0], dict)
        assert OperationsFacade.database_evidence(source)["facts_digest"] == before["facts_digest"]


def test_repository_rows_do_not_escape_facade(client):
    from modules.db import get_db
    from test_production_node_shadow_scheduling import _seed_order

    with client.application.app_context():
        db = get_db()
        order_id, _ = _seed_order(db)
        rows = OperationsFacade.list_schedulable_orders(1000, db=db)
        row = next(row for row in rows if row["id"] == order_id)
        assert isinstance(row, dict)
        row["order_no"] = "changed detached row"
        assert db.execute("SELECT order_no FROM orders WHERE id=?", (order_id,)).fetchone()[0] != row["order_no"]


def test_verification_context_uses_plain_settings_and_restores_outer_context():
    from flask import current_app, has_app_context

    with OperationsFacade.verification_context("outer-check") as outer:
        assert type(outer) is dict
        outer["OPERATIONS_FIXTURE"] = "outer"
        assert current_app.config["OPERATIONS_FIXTURE"] == "outer"
        with OperationsFacade.verification_context("inner-check") as inner:
            assert type(inner) is dict
            assert "OPERATIONS_FIXTURE" not in inner
        assert current_app.config["OPERATIONS_FIXTURE"] == "outer"
    assert not has_app_context()


def test_e2e_server_entrypoint_does_not_return_the_framework(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    run = Mock(return_value=None)
    monkeypatch.setitem(sys.modules, "server", SimpleNamespace(app=SimpleNamespace(run=run)))
    assert OperationsFacade.run_e2e_server(port=4321) is None
    run.assert_called_once_with(host="127.0.0.1", port=4321, debug=False, use_reloader=False, threaded=True)


def test_replica_copy_refuses_symlink_destination(tmp_path):
    source = tmp_path / "source.db"
    _simple_database(source)
    link = tmp_path / "source-link.db"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("symlink creation unavailable on this host")
    with pytest.raises(ValueError, match="symlink"):
        OperationsFacade.copy_database_replica(source, link)
    assert OperationsFacade.database_evidence(source)["tables"]["facts"]["count"] == 1
