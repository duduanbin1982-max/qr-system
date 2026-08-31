from pathlib import Path
import sqlite3

import pytest


def _v069_file(path: Path):
    from modules.migrations import MIGRATIONS

    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    for version, _, migration in MIGRATIONS:
        if version > 69:
            continue
        migration(db)
        db.execute(f"PRAGMA user_version={version}")
        db.commit()
    process_id = db.execute(
        "INSERT INTO processes (process_code,name,description,category,seq_order,status,lifecycle_status) "
        "VALUES ('PROC-9070','岗位发布预检工序','测试','机加工',9070,'active','active')"
    ).lastrowid
    position_id = db.execute(
        "INSERT INTO positions(name,description,status,updated_at) "
        "VALUES ('岗位发布预检','迁移前描述','active','2026-08-20 08:00:00')"
    ).lastrowid
    db.execute(
        "INSERT INTO position_processes(position_id,process_id) VALUES (?,?)",
        (position_id, process_id),
    )
    user_id = db.execute(
        "INSERT INTO users(username,password,name,role,employee_no,status,position_id) "
        "VALUES ('position-v070-preflight','hash','岗位预检员工','worker','PV070','active',?)",
        (position_id,),
    ).lastrowid
    db.execute(
        "INSERT INTO performance_assignment_history ("
        "user_id,employee_name_snapshot,employee_no_snapshot,position_id,"
        "position_name_snapshot,valid_from,valid_to,source_type,source_key) "
        "VALUES (?,?,?,?,?,'2026-08-01 07:00:00','','application','position-v070-preflight')",
        (user_id, "岗位预检员工", "PV070", position_id, "岗位发布预检"),
    )
    order_id = db.execute(
        "INSERT INTO orders(order_no,product_name,quantity,status) "
        "VALUES ('POSITION-V070-PREFLIGHT','迁移产品',1,'pending')"
    ).lastrowid
    db.execute(
        "INSERT INTO work_records(order_id,process_id,user_id,status,quantity,created_at) "
        "VALUES (?,?,?,'approved',2,'2026-08-20 10:00:00')",
        (order_id, process_id, user_id),
    )
    db.commit()
    db.close()
    return {"position_id": position_id, "process_id": process_id, "user_id": user_id}


@pytest.fixture
def replica_db(tmp_path):
    path = tmp_path / "position-v069.db"
    _v069_file(path)
    return path


def test_preflight_blocks_unresolved_manual_review(replica_db):
    from scripts.preflight_position_v070 import PRECHECK_THRESHOLDS, preflight

    manifest = {
        "manual_review": [
            {
                "position_id": 1,
                "reason_code": "POSITION_PROCESS_EVIDENCE_CONFLICT",
                "resolution_status": "open",
            }
        ]
    }

    result = preflight(replica_db, recovery_manifest=manifest)

    assert result["ready"] is False
    assert result["checks"]["unresolved_recovery_items"] == 1
    assert result["thresholds"] == PRECHECK_THRESHOLDS
    assert result["source_unchanged"] is True
    assert result["database"]["query_only"] == 1


def test_preflight_passes_clean_v069_database_without_writing(replica_db):
    from scripts.preflight_position_v070 import preflight
    from scripts.recover_position_processes import file_sha256

    source_hash = file_sha256(replica_db)
    source_size = replica_db.stat().st_size

    result = preflight(replica_db)

    assert result["ready"] is True
    assert set(result["checks"].values()) == {0}
    assert file_sha256(replica_db) == source_hash
    assert replica_db.stat().st_size == source_size


def test_preflight_blocks_duplicate_normalized_position_name(replica_db):
    from scripts.preflight_position_v070 import preflight

    db = sqlite3.connect(replica_db)
    db.execute(
        "INSERT INTO positions(name,description,status) VALUES ('  岗位发布预检  ','重复','inactive')"
    )
    db.commit()
    db.close()

    result = preflight(replica_db)

    assert result["ready"] is False
    assert result["checks"]["duplicate_position_name"] == 1


def test_replica_validation_runs_v070_and_preserves_source(replica_db, tmp_path):
    from scripts.recover_position_processes import file_sha256
    from scripts.validate_position_v070_replica import validate_replica

    source_hash = file_sha256(replica_db)
    source_size = replica_db.stat().st_size
    replica = tmp_path / "validated-v070.db"

    report = validate_replica(replica_db, replica)

    assert report["status"] == "passed", report["blocking_failures"]
    assert report["migration"]["checks"]["user_version"] >= 70
    assert report["legacy_v1_parity"]["ok"] is True
    assert report["assignments"]["ok"] is True
    assert report["business_fact_baseline"]["ok"] is True
    assert report["business_fact_baseline"]["tables"]["work_records"][
        "source_count"
    ] == 1
    assert report["business_fact_baseline"]["tables"]["work_records"][
        "candidate_count"
    ] == 1
    assert report["business_fact_baseline"]["tables"]["work_records"][
        "count_delta"
    ] == 0
    assert report["idempotent_replay"]["ok"] is True
    assert report["source_unchanged"] is True
    assert file_sha256(replica_db) == source_hash
    assert replica_db.stat().st_size == source_size


def test_replica_fact_baseline_uses_latest_source_counts(replica_db, tmp_path):
    from scripts.validate_position_v070_replica import validate_replica

    db = sqlite3.connect(replica_db)
    existing = db.execute(
        "SELECT order_id,process_id,user_id FROM work_records ORDER BY id LIMIT 1"
    ).fetchone()
    db.execute(
        "INSERT INTO work_records(order_id,process_id,user_id,status,quantity,created_at) "
        "VALUES (?,?,?,'approved',3,'2026-08-21 14:59:59')",
        existing,
    )
    db.commit()
    db.close()

    report = validate_replica(replica_db, tmp_path / "latest-facts-v070.db")

    facts = report["business_fact_baseline"]
    assert report["status"] == "passed", report["blocking_failures"]
    assert facts["ok"] is True
    assert facts["tables"]["work_records"]["source_count"] == 2
    assert facts["tables"]["work_records"]["candidate_count"] == 2
    assert facts["tables"]["work_records"]["count_delta"] == 0


def test_replica_fact_baseline_blocks_migration_fact_mutation(
    replica_db, tmp_path, monkeypatch
):
    import modules.migrations as migrations
    from scripts.validate_position_v070_replica import validate_replica

    real_run_migrations = migrations.run_migrations

    def mutate_fact_after_migration(db):
        executed = real_run_migrations(db)
        db.execute("UPDATE work_records SET quantity=quantity+1")
        return executed

    monkeypatch.setattr(migrations, "run_migrations", mutate_fact_after_migration)

    report = validate_replica(replica_db, tmp_path / "mutated-facts-v070.db")

    facts = report["business_fact_baseline"]
    assert report["status"] == "failed"
    assert facts["ok"] is False
    assert facts["tables"]["work_records"]["equal"] is False
    assert "migration changed the dynamic business fact baseline" in report[
        "blocking_failures"
    ]
