import json
import sqlite3
from types import SimpleNamespace

import pytest

from scripts import production_operations
from scripts import export_performance_v2_review_diff as review_export
from scripts import production_performance_v2_apply as performance_apply
from scripts import production_performance_v2_approve as performance_approve
from scripts import production_performance_v2_cutover as performance_cutover
from scripts import production_performance_v2_post_cutover_smoke as performance_smoke
from scripts import production_performance_v2_preflight as performance_preflight
from scripts import production_performance_v2_supervisor_review as performance_review
from scripts import validate_performance_v57_replica as performance_replica


READ_ONLY_OPENERS = (
    performance_apply._open_ro,
    performance_approve._open_ro,
    performance_cutover._open_ro,
    performance_smoke._open_ro,
    performance_review._open_ro,
    review_export._open_ro,
)

BACKUP_FUNCTIONS = (
    performance_apply._backup,
    performance_approve._backup,
    performance_review._backup,
    performance_cutover._database_backup,
    performance_replica._online_backup,
)

PAYROLL_FUNCTIONS = (
    performance_apply._payroll_fingerprint,
    performance_approve._payroll,
    performance_cutover._payroll,
    performance_smoke._payroll,
    performance_review._payroll,
)

CLI_MODULES = (
    (review_export, None),
    (performance_apply, None),
    (performance_approve, None),
    (performance_cutover, None),
    (performance_smoke, None),
    (performance_preflight, None),
    (performance_review, None),
    (performance_replica, 2),
)

PAYROLL_TABLES = (
    "payroll_batches",
    "payroll_employee_lines",
    "payroll_adjustments",
    "payroll_detail_lines",
    "payroll_work_price_resolutions",
    "payroll_events",
    "payroll_migration_manifests",
)


READ_ONLY_MODULES = (
    (performance_apply, "_open_ro"),
    (performance_approve, "_open_ro"),
    (performance_cutover, "_open_ro"),
    (performance_smoke, "_open_ro"),
    (performance_preflight, "_open_read_only"),
    (performance_review, "_open_ro"),
    (review_export, "_open_ro"),
)

BACKUP_MODULES = (
    (performance_apply, "_backup"),
    (performance_approve, "_backup"),
    (performance_review, "_backup"),
    (performance_cutover, "_database_backup"),
    (performance_replica, "_online_backup"),
)

PAYROLL_MODULES = (
    (performance_apply, "_payroll_fingerprint"),
    (performance_approve, "_payroll"),
    (performance_cutover, "_payroll"),
    (performance_smoke, "_payroll"),
    (performance_review, "_payroll"),
)

EVIDENCE_WRITERS = (
    (review_export, "_write_json"),
    (performance_preflight, "_write_json"),
)

FINGERPRINT_MODULES = (
    review_export,
    performance_apply,
    performance_approve,
    performance_cutover,
    performance_smoke,
    performance_preflight,
    performance_review,
    performance_replica,
)


@pytest.fixture
def source_database(tmp_path):
    path = tmp_path / "source.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
    db.execute("INSERT INTO sample(value) VALUES ('基线')")
    db.commit()
    db.close()
    return path


def _parser_stub():
    return SimpleNamespace(parse_args=lambda argv: SimpleNamespace())


@pytest.mark.parametrize("module,helper_name", READ_ONLY_MODULES)
def test_read_only_helpers_delegate_to_shared_primitive(
    monkeypatch, module, helper_name
):
    sentinel = object()
    calls = []

    def fake_open(path):
        calls.append(path)
        return sentinel

    monkeypatch.setattr(production_operations, "open_read_only_sqlite", fake_open)

    assert getattr(module, helper_name)("source.db") is sentinel
    assert calls == ["source.db"]


@pytest.mark.parametrize("module,helper_name", BACKUP_MODULES)
def test_backup_helpers_delegate_to_shared_primitive(
    monkeypatch, module, helper_name
):
    calls = []

    def fake_backup(source, target):
        calls.append((source, target))
        return {"status": "passed"}

    monkeypatch.setattr(production_operations, "online_database_backup", fake_backup)

    assert getattr(module, helper_name)("source.db", "backup.db") is None
    assert calls == [("source.db", "backup.db")]


@pytest.mark.parametrize("module,helper_name", PAYROLL_MODULES)
def test_payroll_helpers_delegate_with_frozen_table_order(
    monkeypatch, module, helper_name
):
    sentinel = object()
    calls = []

    def fake_fingerprint(db, tables):
        calls.append((db, tuple(tables)))
        return {"payroll_batches": 4}

    monkeypatch.setattr(
        production_operations, "table_count_fingerprint", fake_fingerprint
    )

    assert getattr(module, helper_name)(sentinel) == {"payroll_batches": 4}
    assert calls == [(sentinel, PAYROLL_TABLES)]


@pytest.mark.parametrize("module,helper_name", EVIDENCE_WRITERS)
def test_evidence_writer_helpers_delegate_to_shared_primitive(
    monkeypatch, module, helper_name
):
    calls = []

    def fake_write(path, payload, *, overwrite=False):
        calls.append((path, payload, overwrite))

    monkeypatch.setattr(production_operations, "write_evidence_json", fake_write)
    payload = {"status": "passed"}

    assert getattr(module, helper_name)("evidence.json", payload) is None
    assert calls == [("evidence.json", payload, False)]


@pytest.mark.parametrize("module", FINGERPRINT_MODULES)
def test_sha256_helpers_delegate_to_shared_file_fingerprint(monkeypatch, module):
    calls = []

    def fake_fingerprint(path):
        calls.append(path)
        return {"sha256": "frozen-digest"}

    monkeypatch.setattr(production_operations, "file_fingerprint", fake_fingerprint)

    assert module._sha256("artifact.json") == "frozen-digest"
    assert calls == ["artifact.json"]


@pytest.mark.parametrize("module,failure_indent", CLI_MODULES)
def test_performance_cli_entrypoints_delegate_to_shared_runner(
    monkeypatch, module, failure_indent
):
    calls = []

    def fake_run_json_cli(parser_factory, operation, argv, *, failure_indent=None):
        calls.append((parser_factory, operation, argv, failure_indent))
        return 17

    monkeypatch.setattr(production_operations, "run_json_cli", fake_run_json_cli)
    argv = ["--contract-check"]

    assert module.main(argv) == 17
    assert calls == [(module._parser, module.run, argv, failure_indent)]


@pytest.mark.parametrize("open_ro", READ_ONLY_OPENERS)
def test_read_only_openers_preserve_sqlite_safety_pragmas(source_database, open_ro):
    db = open_ro(source_database)
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


@pytest.mark.parametrize("backup", BACKUP_FUNCTIONS)
def test_database_backup_helpers_preserve_schema_and_rows(
    tmp_path, source_database, backup
):
    target = tmp_path / "backup.db"
    backup(source_database, target)

    db = sqlite3.connect(target)
    try:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT id,value FROM sample").fetchall() == [(1, "基线")]
    finally:
        db.close()


@pytest.mark.parametrize("fingerprint", PAYROLL_FUNCTIONS)
def test_payroll_fingerprints_preserve_keys_order_and_counts(fingerprint):
    db = sqlite3.connect(":memory:")
    try:
        for index, table in enumerate(PAYROLL_TABLES):
            db.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
            db.executemany(
                f"INSERT INTO {table}(id) VALUES (?)",
                [(row_id,) for row_id in range(1, index + 1)],
            )

        actual = fingerprint(db)
        assert list(actual) == list(PAYROLL_TABLES)
        assert actual == {
            table: index for index, table in enumerate(PAYROLL_TABLES)
        }
    finally:
        db.close()


@pytest.mark.parametrize("module,failure_indent", CLI_MODULES)
def test_performance_cli_success_contract(monkeypatch, capsys, module, failure_indent):
    result = {"status": "passed", "message": "受控完成"}
    monkeypatch.setattr(module, "_parser", _parser_stub)
    monkeypatch.setattr(module, "run", lambda args: result)

    assert module.main([]) == 0
    captured = capsys.readouterr()
    assert captured.out == json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    assert captured.err == ""


@pytest.mark.parametrize("module,failure_indent", CLI_MODULES)
def test_performance_cli_failure_contract(monkeypatch, capsys, module, failure_indent):
    def fail(_args):
        raise RuntimeError("受控失败")

    monkeypatch.setattr(module, "_parser", _parser_stub)
    monkeypatch.setattr(module, "run", fail)

    assert module.main([]) == 1
    captured = capsys.readouterr()
    expected = {"status": "failed", "error": "受控失败"}
    assert captured.out == ""
    assert captured.err == (
        json.dumps(expected, ensure_ascii=False, indent=failure_indent) + "\n"
    )
