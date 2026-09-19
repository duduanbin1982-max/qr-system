import json
from pathlib import Path
import sqlite3

import pytest

from scripts import production_node_operations


COMMIT = "307f99e68c52626b72f3cb25159e4211510d5051"
ROLLBACK_COMMIT = "c19304a31a6edb32d721df664a601ec1405bf1f1"


def _create_database(path: Path, *, version=87, mapped=True):
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript(
            """
            CREATE TABLE process_production_lines (
                id INTEGER PRIMARY KEY,
                process_id INTEGER NOT NULL,
                line_code TEXT NOT NULL,
                line_name TEXT NOT NULL,
                status TEXT NOT NULL,
                calendar_id INTEGER NOT NULL
            );
            CREATE TABLE production_nodes (
                id INTEGER PRIMARY KEY,
                process_id INTEGER NOT NULL,
                node_code TEXT NOT NULL,
                node_name TEXT NOT NULL,
                capacity_mode TEXT NOT NULL DEFAULT 'exclusive',
                status TEXT NOT NULL DEFAULT 'active',
                calendar_id INTEGER NOT NULL,
                legacy_process_line_id INTEGER UNIQUE
            );
            CREATE TABLE production_node_migration_differences (
                id INTEGER PRIMARY KEY,
                source_table TEXT NOT NULL,
                source_id INTEGER NOT NULL,
                legacy_process_line_id INTEGER,
                difference_code TEXT NOT NULL,
                detail_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE production_node_compatibility_observations (
                id INTEGER PRIMARY KEY,
                observation_key TEXT NOT NULL UNIQUE,
                scope TEXT NOT NULL,
                source_id INTEGER,
                legacy_digest TEXT NOT NULL,
                node_digest TEXT NOT NULL,
                mismatch INTEGER NOT NULL,
                difference_json TEXT NOT NULL DEFAULT '{}',
                observed_at TEXT NOT NULL
            );
            CREATE TABLE order_process_schedules (
                id INTEGER PRIMARY KEY,
                process_line_id INTEGER,
                production_node_id INTEGER,
                execution_mode TEXT NOT NULL DEFAULT 'internal',
                quantity INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'planned'
            );
            CREATE TABLE schedule_revision_items (
                id INTEGER PRIMARY KEY,
                process_line_id INTEGER,
                production_node_id INTEGER,
                execution_mode TEXT NOT NULL DEFAULT 'internal'
            );
            CREATE TABLE order_process_schedule_segments (
                id INTEGER PRIMARY KEY,
                schedule_id INTEGER NOT NULL,
                production_node_id INTEGER,
                segment_start_at TEXT NOT NULL,
                segment_end_at TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        db.execute(
            "INSERT INTO process_production_lines VALUES (1,1,'WELD-01','焊接-01','active',1)"
        )
        if mapped:
            for node_id in range(1, 22):
                db.execute(
                    "INSERT INTO production_nodes "
                    "(id,process_id,node_code,node_name,capacity_mode,status,calendar_id,legacy_process_line_id) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        node_id,
                        1,
                        f"NODE-{node_id:02d}",
                        f"节点-{node_id:02d}",
                        "exclusive",
                        "active",
                        1,
                        1 if node_id == 1 else None,
                    ),
                )
        db.execute("PRAGMA user_version=%d" % version)
        db.commit()
    finally:
        db.close()


@pytest.fixture
def node_database(tmp_path):
    path = tmp_path / "node.db"
    _create_database(path)
    return path


def test_preflight_is_read_only_and_reports_v087_baseline(node_database):
    before = node_database.read_bytes()

    report = production_node_operations.run_preflight(
        node_database, expected_commit=COMMIT, actual_commit=COMMIT
    )

    assert report["ok"] is True
    assert report["mode"] == "read_only_preflight"
    assert report["checks"]["database_integrity"] is True
    assert report["checks"]["core_node_count_21"] is True
    assert report["checks"]["legacy_mapping_complete"] is True
    assert report["checks"]["latest_compat_mismatch_zero"] is True
    assert node_database.read_bytes() == before


def test_preflight_accepts_v085_segments_without_production_node_column(tmp_path):
    path = tmp_path / "v085.db"
    with sqlite3.connect(path) as db:
        db.executescript(
            """
            CREATE TABLE order_process_schedules (
                id INTEGER PRIMARY KEY,
                quantity INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE order_process_schedule_segments (
                id INTEGER PRIMARY KEY,
                schedule_id INTEGER NOT NULL,
                process_line_id INTEGER NOT NULL,
                segment_start_at TEXT NOT NULL,
                segment_end_at TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 0
            );
            INSERT INTO order_process_schedules(id,quantity) VALUES (1,10);
            INSERT INTO order_process_schedule_segments(
                id,schedule_id,process_line_id,segment_start_at,segment_end_at,quantity
            ) VALUES (1,1,7,'2026-09-19 08:00','2026-09-19 09:00',10);
            PRAGMA user_version=85;
            """
        )

    before = path.read_bytes()
    report = production_node_operations.run_preflight(
        path, expected_commit=COMMIT, actual_commit=COMMIT
    )

    assert report["ok"] is True
    assert report["checks"]["expected_database_version"] is True
    assert report["counts"]["shadow_conflict_count"] == 0
    assert report["counts"]["quantity_difference"] == 0
    assert path.read_bytes() == before


def test_preflight_blocks_unmapped_historical_facts(node_database):
    with sqlite3.connect(node_database) as db:
        db.execute(
            "INSERT INTO production_node_migration_differences "
            "(source_table,source_id,legacy_process_line_id,difference_code) "
            "VALUES ('order_process_schedules',7,1,'missing_mapping')"
        )

    report = production_node_operations.run_preflight(
        node_database, expected_commit=COMMIT, actual_commit=COMMIT
    )

    assert report["ok"] is False
    assert report["checks"]["unmapped_historical_facts"] is False
    assert report["counts"]["unmapped_historical_facts"] == 1


def test_preflight_blocks_wrong_commit_and_stale_database(node_database):
    wrong_commit = production_node_operations.run_preflight(
        node_database, expected_commit=COMMIT, actual_commit="f" * 40
    )
    assert wrong_commit["ok"] is False
    assert wrong_commit["checks"]["expected_commit_matches"] is False

    with sqlite3.connect(node_database) as db:
        db.execute("PRAGMA user_version=75")
    stale = production_node_operations.run_preflight(
        node_database, expected_commit=COMMIT, actual_commit=COMMIT
    )
    assert stale["checks"]["expected_database_version"] is False


def test_preflight_uses_latest_compatibility_observation(node_database):
    with sqlite3.connect(node_database) as db:
        db.executemany(
            "INSERT INTO production_node_compatibility_observations "
            "(observation_key,scope,source_id,legacy_digest,node_digest,mismatch,observed_at) "
            "VALUES (?,?,?,?,?,?,?)",
            [
                ("old", "resource_list", 1, "a", "b", 1, "2026-09-17 08:00:00"),
                ("new", "resource_list", 1, "a", "a", 0, "2026-09-17 09:00:00"),
                ("bad", "resource_list", 2, "a", "b", 1, "2026-09-17 09:00:00"),
            ],
        )

    report = production_node_operations.run_preflight(
        node_database, expected_commit=COMMIT, actual_commit=COMMIT
    )

    assert report["checks"]["latest_compat_mismatch_zero"] is False
    assert report["counts"]["latest_compat_mismatch_count"] == 1


def test_shadow_run_blocks_exclusive_node_overlap_and_quantity_loss(node_database):
    with sqlite3.connect(node_database) as db:
        db.executemany(
            "INSERT INTO order_process_schedules "
            "(id,process_line_id,production_node_id,execution_mode,quantity,status) "
            "VALUES (?,?,?,?,?,?)",
            [(1, 1, 1, "internal", 10, "planned"), (2, 1, 1, "internal", 8, "planned")],
        )
        db.executemany(
            "INSERT INTO order_process_schedule_segments "
            "(id,schedule_id,production_node_id,segment_start_at,segment_end_at,quantity) "
            "VALUES (?,?,?,?,?,?)",
            [
                (1, 1, 1, "2026-09-20 08:00", "2026-09-20 09:00", 9),
                (2, 2, 1, "2026-09-20 08:30", "2026-09-20 09:30", 8),
            ],
        )

    report = production_node_operations.run_shadow_run(
        node_database, expected_commit=COMMIT, actual_commit=COMMIT
    )

    assert report["ok"] is False
    assert report["checks"]["shadow_conflicts_zero"] is False
    assert report["checks"]["quantity_conservation_100_percent"] is False
    assert report["counts"]["shadow_conflict_count"] == 1
    assert report["counts"]["quantity_difference"] == 1


def test_flags_only_advance_one_approved_stage_and_require_rollback_evidence():
    off = production_node_operations.flags_for_state("off")
    observe = production_node_operations.flags_for_state("query_audit")
    engine = production_node_operations.flags_for_state("engine")

    assert production_node_operations.validate_flag_transition(off, observe)["changed"] is True
    with pytest.raises(ValueError, match="cannot skip"):
        production_node_operations.validate_flag_transition(off, engine)
    with pytest.raises(ValueError, match="rollback evidence"):
        production_node_operations.validate_flag_transition(observe, off)


def test_set_flags_preserves_unrelated_env_and_replays_idempotently(
    node_database, tmp_path
):
    env_file = tmp_path / ".env"
    env_file.write_text("SECRET_KEY=keep-me\nOTHER=value\n", encoding="utf-8")
    evidence_dir = tmp_path / "evidence"

    first = production_node_operations.set_flags(
        db=node_database,
        env_file=env_file,
        state="query_audit",
        evidence_dir=evidence_dir,
        expected_commit=COMMIT,
        actual_commit=COMMIT,
        idempotency_key="node-observe-001",
    )
    replay = production_node_operations.set_flags(
        db=node_database,
        env_file=env_file,
        state="query_audit",
        evidence_dir=evidence_dir,
        expected_commit=COMMIT,
        actual_commit=COMMIT,
        idempotency_key="node-observe-001",
    )

    content = env_file.read_text(encoding="utf-8")
    assert first["ok"] is True
    assert replay["idempotent_replay"] is True
    assert "SECRET_KEY=keep-me" in content
    assert "OTHER=value" in content
    assert "PRODUCTION_NODE_QUERY_ENABLED=true" in content
    assert "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED=true" in content
    assert "PRODUCTION_NODE_WRITE_ENABLED=false" in content


def test_rollback_readiness_evidence_allows_a_backward_flag_transition(
    node_database, tmp_path
):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "PRODUCTION_NODE_QUERY_ENABLED=true\n"
        "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED=true\n",
        encoding="utf-8",
    )
    evidence_dir = tmp_path / "evidence"
    readiness = production_node_operations.rollback_readiness(
        db=node_database,
        evidence_dir=evidence_dir,
        expected_commit=COMMIT,
        actual_commit=COMMIT,
        rollback_commit=ROLLBACK_COMMIT,
        idempotency_key="node-rollback-ready-001",
    )
    result = production_node_operations.set_flags(
        db=node_database,
        env_file=env_file,
        state="off",
        evidence_dir=evidence_dir,
        expected_commit=COMMIT,
        actual_commit=COMMIT,
        idempotency_key="node-rollback-001",
        rollback_evidence=readiness["artifacts"]["evidence"],
    )

    assert result["ok"] is True
    assert "PRODUCTION_NODE_QUERY_ENABLED=false" in env_file.read_text(encoding="utf-8")


def test_cli_emits_one_json_object_and_uses_exit_code_two_for_blocked(
    node_database, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        production_node_operations,
        "resolve_checkout_commit",
        lambda _root: COMMIT,
    )
    with sqlite3.connect(node_database) as db:
        db.execute(
            "INSERT INTO production_node_migration_differences "
            "(source_table,source_id,legacy_process_line_id,difference_code) "
            "VALUES ('order_process_schedules',7,1,'missing_mapping')"
        )

    code = production_node_operations.main(
        [
            "preflight",
            "--db",
            str(node_database),
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--expected-commit",
            COMMIT,
        ]
    )

    assert code == 2
    output = json.loads(capsys.readouterr().out)
    assert output["ok"] is False
    assert output["command"] == "preflight"
