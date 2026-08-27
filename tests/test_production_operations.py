import io
import json
import sqlite3
from types import SimpleNamespace

import pytest

from scripts import production_operations


@pytest.fixture
def source_database(tmp_path):
    path = tmp_path / "source.db"
    db = sqlite3.connect(path)
    db.execute("PRAGMA user_version=75")
    db.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("INSERT INTO sample(value) VALUES ('基线')")
    db.commit()
    db.close()
    return path


def test_open_read_only_sqlite_enforces_characterized_pragmas(source_database):
    db = production_operations.open_read_only_sqlite(source_database)
    try:
        assert db.row_factory is sqlite3.Row
        assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert db.execute("PRAGMA busy_timeout").fetchone()[0] == 10000
        assert db.execute("PRAGMA query_only").fetchone()[0] == 1
        assert dict(db.execute("SELECT * FROM sample").fetchone()) == {
            "id": 1,
            "value": "基线",
        }
        with pytest.raises(sqlite3.OperationalError):
            db.execute("INSERT INTO sample(value) VALUES ('禁止写入')")
    finally:
        db.close()


def test_database_and_table_fingerprints_are_stable(source_database):
    fingerprint = production_operations.database_fingerprint(source_database)
    assert fingerprint["path"] == str(source_database.resolve())
    assert len(fingerprint["sha256"]) == 64
    assert fingerprint["size_bytes"] == source_database.stat().st_size
    assert fingerprint["user_version"] == 75
    assert fingerprint["integrity_check"] == "ok"
    assert fingerprint["foreign_key_error_count"] == 0

    db = sqlite3.connect(source_database)
    try:
        assert production_operations.table_count_fingerprint(db, ("sample",)) == {
            "sample": 1
        }
        with pytest.raises(
            production_operations.ProductionOperationError,
            match="unsupported table identifier",
        ):
            production_operations.table_count_fingerprint(db, ("sample; DROP",))
    finally:
        db.close()


def test_write_evidence_json_is_atomic_and_refuses_overwrite(tmp_path):
    path = tmp_path / "nested" / "evidence.json"
    payload = {"status": "passed", "message": "受控完成"}

    assert production_operations.write_evidence_json(path, payload) == path.resolve()
    assert path.read_text(encoding="utf-8") == (
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    )
    assert not list(path.parent.glob(".*.tmp.*"))

    with pytest.raises(
        production_operations.ProductionOperationError,
        match="evidence destination already exists",
    ):
        production_operations.write_evidence_json(path, {"status": "failed"})

    production_operations.write_evidence_json(
        path, {"status": "replaced"}, overwrite=True
    )
    assert json.loads(path.read_text(encoding="utf-8")) == {"status": "replaced"}


def test_write_evidence_json_removes_its_reservation_after_failure(
    monkeypatch, tmp_path
):
    path = tmp_path / "failed.json"
    monkeypatch.setattr(
        production_operations.deployment_manifest,
        "atomic_write_json",
        lambda target, payload: (_ for _ in ()).throw(RuntimeError("写入失败")),
    )

    with pytest.raises(RuntimeError, match="写入失败"):
        production_operations.write_evidence_json(path, {"status": "failed"})

    assert not path.exists()


def test_online_database_backup_preserves_rows_and_verifies(source_database, tmp_path):
    target = tmp_path / "backup" / "verified.db"

    evidence = production_operations.online_database_backup(source_database, target)

    assert evidence["path"] == str(target.resolve())
    assert evidence["user_version"] == 75
    assert evidence["integrity_check"] == "ok"
    db = sqlite3.connect(target)
    try:
        assert db.execute("SELECT id,value FROM sample").fetchall() == [(1, "基线")]
    finally:
        db.close()

    with pytest.raises(
        production_operations.ProductionOperationError,
        match="database backup already exists",
    ):
        production_operations.online_database_backup(source_database, target)


def test_online_database_backup_removes_only_its_failed_target(
    monkeypatch, source_database, tmp_path
):
    target = tmp_path / "failed.db"
    monkeypatch.setattr(
        production_operations,
        "database_fingerprint",
        lambda path: (_ for _ in ()).throw(RuntimeError("校验失败")),
    )

    with pytest.raises(RuntimeError, match="校验失败"):
        production_operations.online_database_backup(source_database, target)

    assert not target.exists()


def test_run_authoritative_backup_invokes_script_and_verifies_metadata(
    monkeypatch, tmp_path
):
    root = tmp_path / "system"
    script = root / "scripts" / "backup-db.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    database = root / "data" / "production.db"
    backup_dir = root / "data" / "backups"
    metadata = backup_dir / "evidence.json"
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="BACKUP OK\n", stderr="")

    expected = {"schema": "qr-system-backup-evidence/v1"}
    monkeypatch.setattr(production_operations.subprocess, "run", fake_run)
    monkeypatch.setattr(
        production_operations.deployment_manifest,
        "verify_backup_metadata",
        lambda path: expected if path == metadata.resolve() else None,
    )

    assert production_operations.run_authoritative_backup(
        project_root=root,
        database=database,
        backup_dir=backup_dir,
        metadata_file=metadata,
    ) == expected
    command, kwargs = calls[0]
    assert command == ["bash", str(script.resolve())]
    assert kwargs["cwd"] == str(root.resolve())
    assert kwargs["check"] is False
    assert kwargs["capture_output"] is True
    assert kwargs["env"]["QR_PROJECT_ROOT"] == str(root.resolve())
    assert kwargs["env"]["DB_PATH"] == str(database.resolve())
    assert kwargs["env"]["BACKUP_DIR"] == str(backup_dir.resolve())
    assert kwargs["env"]["BACKUP_METADATA_FILE"] == str(metadata.resolve())


def test_run_authoritative_backup_classifies_command_and_integrity_failures(
    monkeypatch, tmp_path
):
    root = tmp_path / "system"
    script = root / "scripts" / "backup-db.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    metadata = tmp_path / "evidence.json"

    monkeypatch.setattr(
        production_operations.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=7, stdout="", stderr="受控备份失败\n"
        ),
    )
    with pytest.raises(production_operations.ProductionOperationError) as error:
        production_operations.run_authoritative_backup(
            project_root=root,
            database=tmp_path / "source.db",
            backup_dir=tmp_path / "backups",
            metadata_file=metadata,
        )
    assert error.value.category == "backup"
    assert str(error.value) == "受控备份失败"

    monkeypatch.setattr(
        production_operations.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    monkeypatch.setattr(
        production_operations.deployment_manifest,
        "verify_backup_metadata",
        lambda path: (_ for _ in ()).throw(RuntimeError("校验失败")),
    )
    with pytest.raises(production_operations.ProductionOperationError) as error:
        production_operations.run_authoritative_backup(
            project_root=root,
            database=tmp_path / "source.db",
            backup_dir=tmp_path / "backups",
            metadata_file=metadata,
        )
    assert error.value.category == "integrity"
    assert str(error.value) == "校验失败"


@pytest.mark.parametrize("failure_indent", (None, 2))
def test_run_json_cli_preserves_success_and_failure_streams(failure_indent):
    parser = lambda: SimpleNamespace(parse_args=lambda argv: SimpleNamespace())
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert production_operations.run_json_cli(
        parser,
        lambda args: {"status": "passed", "message": "受控完成"},
        [],
        failure_indent=failure_indent,
        stdout=stdout,
        stderr=stderr,
    ) == 0
    assert stdout.getvalue() == json.dumps(
        {"status": "passed", "message": "受控完成"},
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    assert stderr.getvalue() == ""

    stdout = io.StringIO()
    stderr = io.StringIO()

    def fail(_args):
        raise RuntimeError("受控失败")

    assert production_operations.run_json_cli(
        parser,
        fail,
        [],
        failure_indent=failure_indent,
        stdout=stdout,
        stderr=stderr,
    ) == 1
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == json.dumps(
        {"status": "failed", "error": "受控失败"},
        ensure_ascii=False,
        indent=failure_indent,
    ) + "\n"
