import json
import shutil
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.config import DB_PATH


def _copy_test_database(tmp_path, name="source.db"):
    target = tmp_path / name
    shutil.copy2(DB_PATH, target)
    return target


def _create_v59_database(path):
    from modules.migrations import MIGRATIONS

    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        for version, _, migration in MIGRATIONS:
            if version > 59:
                break
            migration(db)
            db.execute(f"PRAGMA user_version={version}")
            db.commit()
    finally:
        db.close()
    return path


def test_preflight_is_read_only_and_reports_required_sections(tmp_path):
    from scripts.process_v2_operations import database_sha256, run_preflight

    source = _copy_test_database(tmp_path)
    before = database_sha256(source)

    report = run_preflight(source)

    assert database_sha256(source) == before
    assert report["mode"] == "read_only_preflight"
    assert report["database"]["user_version"] == 63
    assert report["database"]["integrity_check"] == "ok"
    assert report["database"]["query_only"] == 1
    assert set(report["counts"]) >= {
        "roots",
        "versions",
        "route_nodes",
        "prices",
        "orders",
        "facts",
    }
    assert set(report) >= {
        "duplicates",
        "category_mismatches",
        "reference_coverage",
        "migration_simulation",
        "manual_review",
        "summary_sha256",
    }


def test_preflight_counts_all_twelve_legacy_price_route_references():
    from scripts.process_v2_operations import collect_reference_coverage

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE process_routes (id INTEGER PRIMARY KEY);
        CREATE TABLE processes (id INTEGER PRIMARY KEY);
        CREATE TABLE route_price_versions (
            id INTEGER PRIMARY KEY,
            route_id INTEGER NOT NULL,
            process_id INTEGER NOT NULL
        );
        """
    )
    db.executemany(
        "INSERT INTO process_routes(id) VALUES (?)", [(value,) for value in range(1, 13)]
    )
    db.execute("INSERT INTO processes(id) VALUES (1)")
    db.executemany(
        "INSERT INTO route_price_versions(id,route_id,process_id) VALUES (?,?,1)",
        [(value, value) for value in range(1, 13)],
    )

    coverage = collect_reference_coverage(db)

    assert coverage["price_route_references"]["rows"] == 12
    assert coverage["price_route_references"]["distinct_routes"] == 12
    assert coverage["price_route_references"]["route_ids"] == list(range(1, 13))
    db.close()


def test_replica_validation_uses_shared_migration_entry_and_compares_all_groups(tmp_path):
    from scripts.process_v2_operations import validate_replica

    source = _create_v59_database(tmp_path / "source-v59.db")
    replica = tmp_path / "replica.db"

    report = validate_replica(source, replica)

    assert replica.is_file()
    assert report["status"] == "passed"
    assert report["migration"]["source_version"] == 59
    assert report["migration"]["target_version"] == 63
    assert report["migration"]["executed_migrations"] == 4
    assert report["source_stability"]["blocking_differences"] == []
    assert set(report["comparison"]) >= {
        "roots",
        "versions",
        "route_nodes",
        "prices",
        "orders",
        "facts",
        "summary",
    }
    assert report["blocking_differences"] == []


def test_review_diff_exports_json_and_csv_without_mutating_candidate(tmp_path):
    from scripts.process_v2_operations import database_sha256, export_review_diff

    source = _copy_test_database(tmp_path)
    candidate = _copy_test_database(tmp_path, "candidate.db")
    db = sqlite3.connect(candidate)
    db.execute("PRAGMA user_version=62")
    db.close()
    before = database_sha256(candidate)

    result = export_review_diff(source, candidate, tmp_path / "review")

    assert database_sha256(candidate) == before
    assert Path(result["json"]["path"]).is_file()
    assert Path(result["csv"]["path"]).is_file()
    payload = json.loads(Path(result["json"]["path"]).read_text(encoding="utf-8"))
    assert payload["mode"] == "review_only"
    assert payload["differences"]
    assert payload["automatic_repairs_applied"] is False


def test_review_diff_blocks_same_count_business_field_changes(tmp_path):
    from scripts.process_v2_operations import compare_snapshots, database_snapshot

    source = _copy_test_database(tmp_path)
    candidate = _copy_test_database(tmp_path, "candidate.db")
    for path, name in ((source, "Source"), (candidate, "Candidate")):
        db = sqlite3.connect(path)
        db.execute(
            "INSERT INTO processes(name,description,category,seq_order,status) "
            "VALUES (?, '', 'test', 1, 'active')",
            (name,),
        )
        db.commit()
        db.close()

    compared = compare_snapshots(database_snapshot(source), database_snapshot(candidate))

    assert any(item.get("table") == "processes" for item in compared["blocking_differences"])


def test_cutover_flags_must_advance_one_stage_at_a_time(tmp_path):
    from scripts.process_v2_operations import advance_cutover_stage, read_process_flags

    env_path = tmp_path / ".env"
    env_path.write_text("SECRET_KEY=test\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="next allowed stage"):
        advance_cutover_stage(env_path, "compat_audit", apply=True)

    dry_run = advance_cutover_stage(env_path, "query", apply=False)
    assert dry_run["changed"] is False
    assert read_process_flags(env_path)["PROCESS_VERSIONED_QUERY_ENABLED"] is False

    for stage in ("query", "compat_audit", "versioned_write", "legacy_block"):
        result = advance_cutover_stage(env_path, stage, apply=True)
        assert result["stage"] == stage
        assert result["changed"] is True

    assert all(read_process_flags(env_path).values())


def test_cutover_authorization_requires_commit_database_operator_and_idempotency(tmp_path):
    from scripts.process_v2_operations import database_sha256, validate_cutover_authorization

    source = _copy_test_database(tmp_path)
    digest = database_sha256(source)
    commit = "a" * 40

    result = validate_cutover_authorization(
        expected_commit=commit,
        actual_commit=commit,
        expected_database_sha256=digest,
        actual_database_sha256=digest,
        operator="release-operator",
        idempotency_key="process-v2-cutover-20260815",
    )
    assert result["authorized"] is True

    with pytest.raises(RuntimeError, match="operator"):
        validate_cutover_authorization(
            expected_commit=commit,
            actual_commit=commit,
            expected_database_sha256=digest,
            actual_database_sha256=digest,
            operator="",
            idempotency_key="process-v2-cutover-20260815",
        )


def test_cutover_idempotent_replay_rechecks_database_and_preflight_authorization(tmp_path):
    from scripts.production_process_v2_cutover import _idempotent_replay

    evidence_path = tmp_path / "cutover.json"
    evidence_path.write_text(
        json.dumps(
            {
                "status": "passed",
                "stage": "query",
                "target_commit": "a" * 40,
                "operator": "release-operator",
                "idempotency_key": "process-v2-query-1",
                "authorization": {"database_sha256": "b" * 64},
                "preflight": {"file_sha256": "c" * 64},
                "database_after": {"sha256": "d" * 64},
            }
        ),
        encoding="utf-8",
    )
    args = SimpleNamespace(
        stage="query",
        target_commit="a" * 40,
        operator="release-operator",
        idempotency_key="process-v2-query-1",
        database_sha256="b" * 64,
        preflight_sha256="c" * 64,
    )

    replay = _idempotent_replay(evidence_path, args, "a" * 40, "d" * 64)
    assert replay["idempotent_replay"] is True

    args.database_sha256 = "e" * 64
    with pytest.raises(RuntimeError, match="database authorization"):
        _idempotent_replay(evidence_path, args, "a" * 40, "d" * 64)


def test_cutover_atomic_restore_replaces_the_target(tmp_path):
    from scripts.production_process_v2_cutover import _atomic_restore

    source = tmp_path / "verified.backup"
    target = tmp_path / "production.db"
    source.write_bytes(b"verified backup")
    target.write_bytes(b"failed migration")

    _atomic_restore(source, target)

    assert target.read_bytes() == b"verified backup"


def test_cutover_dry_run_keeps_database_and_environment_unchanged(tmp_path, monkeypatch):
    from scripts import production_process_v2_cutover as cutover
    from scripts.process_v2_operations import database_sha256, file_sha256, run_preflight

    root = tmp_path / "system"
    root.mkdir()
    env_path = root / ".env"
    env_path.write_text("SECRET_KEY=test\n", encoding="utf-8")
    database = _copy_test_database(tmp_path)
    preflight = run_preflight(database)
    preflight_path = tmp_path / "preflight.json"
    preflight_path.write_text(json.dumps(preflight), encoding="utf-8")
    commit = "a" * 40
    monkeypatch.setattr(cutover, "_git_commit", lambda _root: commit)
    args = SimpleNamespace(
        system_root=str(root),
        db=str(database),
        output_dir=str(tmp_path / "cutover"),
        stage="query",
        preflight_evidence=str(preflight_path),
        preflight_sha256=file_sha256(preflight_path),
        target_commit=commit,
        database_sha256=database_sha256(database),
        operator="release-operator",
        idempotency_key="process-v2-query-dry-run",
        service="qr-system",
        health_url="https://127.0.0.1:3000/api/health",
        apply=False,
        confirm_production_cutover=False,
    )
    before_database = database_sha256(database)
    before_environment = env_path.read_bytes()

    result = cutover.run(args)

    assert result["status"] == "dry_run"
    assert database_sha256(database) == before_database
    assert env_path.read_bytes() == before_environment


def test_post_cutover_gate_checks_health_legacy_v2_and_missing_bindings(tmp_path):
    from scripts.process_v2_operations import evaluate_post_cutover

    passed = evaluate_post_cutover(
        database={
            "user_version": 63,
            "integrity_check": "ok",
            "foreign_key_violations": 0,
        },
        flags={
            "PROCESS_VERSIONED_QUERY_ENABLED": True,
            "PROCESS_VERSION_COMPAT_AUDIT_ENABLED": True,
            "PROCESS_VERSIONED_WRITE_ENABLED": True,
            "PROCESS_LEGACY_WRITE_BLOCKED": True,
        },
        health={"status": "ok", "db": "connected"},
        api_results={
            "permissions": "passed",
            "legacy_get": 200,
            "legacy_write": 409,
            "v2_query": 200,
            "historical_snapshot": "passed",
        },
        missing_bindings={"orders": 0, "order_processes": 0, "work_records": 0},
    )
    assert passed["status"] == "passed"

    failed = evaluate_post_cutover(
        database={
            "user_version": 63,
            "integrity_check": "ok",
            "foreign_key_violations": 0,
        },
        flags={
            "PROCESS_VERSIONED_QUERY_ENABLED": True,
            "PROCESS_VERSION_COMPAT_AUDIT_ENABLED": True,
            "PROCESS_VERSIONED_WRITE_ENABLED": True,
            "PROCESS_LEGACY_WRITE_BLOCKED": True,
        },
        health={"status": "ok", "db": "connected"},
        api_results={
            "permissions": "passed",
            "legacy_get": 200,
            "legacy_write": 409,
            "v2_query": 200,
            "historical_snapshot": "passed",
        },
        missing_bindings={"orders": 0, "order_processes": 0, "work_records": 1},
    )
    assert failed["status"] == "failed"
    assert failed["blocking_failures"]


def test_preflight_cli_returns_nonzero_and_writes_no_success_marker_on_failure(tmp_path):
    from scripts.production_process_v2_preflight import main

    output_dir = tmp_path / "evidence"
    exit_code = main(
        [
            "--db",
            str(tmp_path / "missing.db"),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code != 0
    assert not list(output_dir.glob("*passed*")) if output_dir.exists() else True
