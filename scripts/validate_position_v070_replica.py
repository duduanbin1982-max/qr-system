#!/usr/bin/env python3
"""Create and validate a disposable position V070 database replica."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.environ.setdefault("SECRET_KEY", "offline-position-v070-replica-validation")

from scripts.preflight_position_v070 import preflight  # noqa: E402
from scripts.recover_position_processes import (  # noqa: E402
    apply_exact_recovery_manifest,
    file_sha256,
    load_manifest,
    open_read_only,
)


EXACT_PROTECTED_TABLES = (
    "positions",
    "position_processes",
    "users",
    "work_records",
    "performance_source_facts",
    "performance_score_revisions",
    "performance_position_target_versions",
)

BUSINESS_FACT_TABLES = (
    "work_records",
    "performance_source_facts",
    "performance_score_revisions",
    "performance_position_target_versions",
)


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _table_exists(db: sqlite3.Connection, table: str) -> bool:
    return (
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )


def _columns(db: sqlite3.Connection, table: str) -> list[str]:
    if not _table_exists(db, table):
        return []
    return [str(row[1]) for row in db.execute(f'PRAGMA table_info("{table}")')]


def _rows_for_columns(
    db: sqlite3.Connection, table: str, columns: list[str]
) -> list[list[Any]]:
    if not columns:
        return []
    quoted = ",".join(f'"{column}"' for column in columns)
    order = '"id"' if "id" in columns else quoted
    return [
        list(row)
        for row in db.execute(
            f'SELECT {quoted} FROM "{table}" ORDER BY {order}'
        ).fetchall()
    ]


def _snapshot_tables(
    db: sqlite3.Connection,
    tables: tuple[str, ...],
    *,
    columns_by_table: dict[str, list[str]] | None = None,
) -> dict[str, dict[str, Any]]:
    result = {}
    for table in tables:
        columns = (
            columns_by_table.get(table, [])
            if columns_by_table is not None
            else _columns(db, table)
        )
        rows = _rows_for_columns(db, table, columns)
        result[table] = {
            "exists": _table_exists(db, table),
            "columns": columns,
            "count": len(rows),
            "sha256": _digest(rows),
        }
    return result


def _business_fact_baseline(
    source_snapshot: dict[str, dict[str, Any]],
    candidate_snapshot: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    tables = {
        table: {
            "source_count": source_snapshot[table]["count"],
            "candidate_count": candidate_snapshot[table]["count"],
            "count_delta": (
                candidate_snapshot[table]["count"]
                - source_snapshot[table]["count"]
            ),
            "source_sha256": source_snapshot[table]["sha256"],
            "candidate_sha256": candidate_snapshot[table]["sha256"],
            "equal": source_snapshot[table] == candidate_snapshot[table],
        }
        for table in BUSINESS_FACT_TABLES
    }
    return {
        "source": "migration input snapshot from stop-window online backup",
        "tables": tables,
        "ok": all(item["equal"] for item in tables.values()),
    }


def _logical_database_snapshot(db: sqlite3.Connection) -> dict[str, Any]:
    tables = [
        str(row[0])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name<>'sqlite_sequence' ORDER BY name"
        ).fetchall()
    ]
    snapshot = {}
    for table in tables:
        columns = _columns(db, table)
        rows = _rows_for_columns(db, table, columns)
        snapshot[table] = {
            "columns": columns,
            "count": len(rows),
            "sha256": _digest(rows),
        }
    return snapshot


def _online_backup(source_path: Path, replica_path: Path) -> None:
    if source_path == replica_path:
        raise ValueError("replica database cannot overwrite the source database")
    if replica_path.exists():
        raise RuntimeError(f"replica destination already exists: {replica_path}")
    replica_path.parent.mkdir(parents=True, exist_ok=True)
    source = open_read_only(source_path)
    target = sqlite3.connect(replica_path)
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()


def _expected_assignment_splits(db: sqlite3.Connection) -> list[dict[str, Any]]:
    assignment_columns = set(_columns(db, "performance_assignment_history"))
    position_columns = set(_columns(db, "positions"))
    if not assignment_columns or "position_id" not in assignment_columns:
        return []
    version_predicate = (
        "AND assignment.position_version_id IS NULL "
        if "position_version_id" in assignment_columns
        else ""
    )
    lifecycle_predicate = (
        "AND position.lifecycle_status='active' "
        if "lifecycle_status" in position_columns
        else "AND position.status='active' "
    )
    return [
        dict(row)
        for row in db.execute(
            "SELECT assignment.id,assignment.user_id,assignment.position_id,"
            "assignment.position_name_snapshot,assignment.valid_to "
            "FROM performance_assignment_history assignment "
            "JOIN users user ON user.id=assignment.user_id AND user.status='active' "
            "JOIN positions position ON position.id=assignment.position_id "
            f"{lifecycle_predicate}"
            "WHERE COALESCE(assignment.valid_to,'')='' "
            f"{version_predicate}"
            "ORDER BY assignment.id"
        ).fetchall()
    ]


def _assignment_source_snapshot(db: sqlite3.Connection) -> dict[str, Any]:
    columns = _columns(db, "performance_assignment_history")
    protected_columns = [column for column in columns if column != "valid_to"]
    rows = _rows_for_columns(db, "performance_assignment_history", protected_columns)
    valid_to = {
        int(row[0]): row[1]
        for row in db.execute(
            "SELECT id,valid_to FROM performance_assignment_history ORDER BY id"
        ).fetchall()
    }
    return {
        "columns": columns,
        "protected_columns": protected_columns,
        "count": len(rows),
        "protected_rows": rows,
        "protected_sha256": _digest(rows),
        "valid_to": valid_to,
        "expected_splits": _expected_assignment_splits(db),
    }


def _validate_assignments(
    before: dict[str, Any], db: sqlite3.Connection
) -> dict[str, Any]:
    columns = before["protected_columns"]
    id_index = columns.index("id")
    after_rows = _rows_for_columns(db, "performance_assignment_history", columns)
    after_by_id = {int(row[id_index]): row for row in after_rows}
    protected_issues = []
    for row in before["protected_rows"]:
        row_id = int(row[id_index])
        if after_by_id.get(row_id) != row:
            protected_issues.append(
                {"assignment_id": row_id, "reason": "source_snapshot_changed"}
            )
    split_issues = []
    for item in before["expected_splits"]:
        old = db.execute(
            "SELECT valid_to FROM performance_assignment_history WHERE id=?",
            (item["id"],),
        ).fetchone()
        source_key = f"position_v070:{item['id']}:"
        created = db.execute(
            "SELECT id,position_version_id,position_name_snapshot,valid_from,valid_to "
            "FROM performance_assignment_history WHERE source_type='position_v070_cutover' "
            "AND source_key LIKE ? ORDER BY id",
            (source_key + "%",),
        ).fetchall()
        if old is None or not str(old[0] or ""):
            split_issues.append(
                {"assignment_id": item["id"], "reason": "legacy_assignment_not_closed"}
            )
        elif len(created) != 1 or created[0][1] is None:
            split_issues.append(
                {"assignment_id": item["id"], "reason": "versioned_assignment_not_created"}
            )
        elif created[0][2] != item["position_name_snapshot"] or created[0][4] != "":
            split_issues.append(
                {"assignment_id": item["id"], "reason": "assignment_snapshot_mismatch"}
            )
    expected_ids = {int(item["id"]) for item in before["expected_splits"]}
    for row_id, source_value in before["valid_to"].items():
        if row_id in expected_ids:
            continue
        after = db.execute(
            "SELECT valid_to FROM performance_assignment_history WHERE id=?", (row_id,)
        ).fetchone()
        if after is None or after[0] != source_value:
            split_issues.append(
                {"assignment_id": row_id, "reason": "unrelated_valid_to_changed"}
            )
    expected_count = before["count"] + len(before["expected_splits"])
    actual_count = int(
        db.execute("SELECT COUNT(*) FROM performance_assignment_history").fetchone()[0]
    )
    return {
        "source_count": before["count"],
        "expected_cutover_count": len(before["expected_splits"]),
        "expected_count": expected_count,
        "actual_count": actual_count,
        "protected_snapshot_sha256": before["protected_sha256"],
        "protected_issues": protected_issues,
        "split_issues": split_issues,
        "ok": not protected_issues and not split_issues and actual_count == expected_count,
    }


def _legacy_v1_parity(db: sqlite3.Connection) -> dict[str, Any]:
    projection_mismatches = [
        int(row[0])
        for row in db.execute(
            "SELECT position.id FROM positions position "
            "LEFT JOIN position_versions version "
            "ON version.id=position.current_effective_version_id "
            "WHERE version.id IS NULL OR version.position_id<>position.id "
            "OR version.position_code_snapshot<>position.position_code "
            "OR version.name<>position.name "
            "OR version.description<>COALESCE(position.description,'') "
            "OR version.status<>CASE WHEN position.status='active' "
            "THEN 'published' ELSE 'retired' END ORDER BY position.id"
        ).fetchall()
    ]
    missing_in_v1 = [
        [int(row[0]), int(row[1])]
        for row in db.execute(
            "SELECT legacy.position_id,legacy.process_id FROM position_processes legacy "
            "EXCEPT SELECT version.position_id,mapping.process_id "
            "FROM position_version_processes mapping "
            "JOIN position_versions version ON version.id=mapping.position_version_id "
            "AND version.version=1 ORDER BY 1,2"
        ).fetchall()
    ]
    extra_in_v1 = [
        [int(row[0]), int(row[1])]
        for row in db.execute(
            "SELECT version.position_id,mapping.process_id "
            "FROM position_version_processes mapping "
            "JOIN position_versions version ON version.id=mapping.position_version_id "
            "AND version.version=1 "
            "EXCEPT SELECT position_id,process_id FROM position_processes ORDER BY 1,2"
        ).fetchall()
    ]
    position_count = int(db.execute("SELECT COUNT(*) FROM positions").fetchone()[0])
    baseline_count = int(
        db.execute(
            "SELECT COUNT(*) FROM position_versions "
            "WHERE version=1 AND legacy_baseline=1 AND prior_revision_unavailable=1"
        ).fetchone()[0]
    )
    return {
        "position_count": position_count,
        "legacy_v1_count": baseline_count,
        "projection_mismatch_ids": projection_mismatches,
        "missing_process_mappings": missing_in_v1,
        "extra_process_mappings": extra_in_v1,
        "ok": (
            position_count == baseline_count
            and not projection_mismatches
            and not missing_in_v1
            and not extra_in_v1
        ),
    }


def _database_checks(db: sqlite3.Connection) -> dict[str, Any]:
    return {
        "user_version": int(db.execute("PRAGMA user_version").fetchone()[0]),
        "integrity_check": str(db.execute("PRAGMA integrity_check").fetchone()[0]),
        "foreign_key_violations": [
            list(row) for row in db.execute("PRAGMA foreign_key_check").fetchall()
        ],
    }


def validate_replica(
    source_db: str | Path,
    replica_db: str | Path,
    *,
    recovery_manifest: str | Path | dict[str, Any] | None = None,
) -> dict[str, Any]:
    from modules.migration_position_versioning import m070_position_versioning
    from modules.migrations import LATEST_VERSION, run_migrations

    source = Path(source_db).resolve()
    replica = Path(replica_db).resolve()
    source_state = {"sha256": file_sha256(source), "size": source.stat().st_size}
    manifest = load_manifest(recovery_manifest)
    preflight_report = preflight(source, recovery_manifest=manifest)
    if not preflight_report["ready"]:
        raise RuntimeError("position V070 source preflight is blocked")
    if manifest.get("auto_restored"):
        expected_hash = str((manifest.get("current_database") or {}).get("sha256") or "")
        if expected_hash != source_state["sha256"]:
            raise RuntimeError("recovery manifest does not match the source database SHA-256")

    _online_backup(source, replica)
    db = sqlite3.connect(replica)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys=ON")
        applied_recovery = apply_exact_recovery_manifest(db, manifest) if manifest.get("auto_restored") else []
        db.commit()
        source_columns = {table: _columns(db, table) for table in EXACT_PROTECTED_TABLES}
        before_migration = _snapshot_tables(db, EXACT_PROTECTED_TABLES)
        assignment_before = _assignment_source_snapshot(db)

        executed = int(run_migrations(db))
        db.commit()
        after_migration = _snapshot_tables(
            db, EXACT_PROTECTED_TABLES, columns_by_table=source_columns
        )
        fact_baseline = _business_fact_baseline(
            before_migration, after_migration
        )
        protected_comparison = {
            table: {
                "source": before_migration[table],
                "candidate": after_migration[table],
                "equal": before_migration[table] == after_migration[table],
            }
            for table in EXACT_PROTECTED_TABLES
        }
        assignments = _validate_assignments(assignment_before, db)
        parity = _legacy_v1_parity(db)
        checks = _database_checks(db)
        first_snapshot = _logical_database_snapshot(db)

        m070_position_versioning(db)
        db.commit()
        m070_position_versioning(db)
        db.commit()
        replay_snapshot = _logical_database_snapshot(db)
        replay_checks = _database_checks(db)
    finally:
        db.close()

    source_after = {"sha256": file_sha256(source), "size": source.stat().st_size}
    source_unchanged = source_state == source_after
    failures = []
    if checks["user_version"] != LATEST_VERSION or LATEST_VERSION < 70:
        failures.append("schema version did not reach V070/latest")
    if checks["integrity_check"] != "ok" or checks["foreign_key_violations"]:
        failures.append("database integrity or foreign-key validation failed")
    if any(not item["equal"] for item in protected_comparison.values()):
        failures.append("migration changed a protected source table snapshot")
    if not fact_baseline["ok"]:
        failures.append("migration changed the dynamic business fact baseline")
    if not assignments["ok"]:
        failures.append("assignment cutover did not preserve source snapshots")
    if not parity["ok"]:
        failures.append("Legacy and V1 position projections differ")
    if first_snapshot != replay_snapshot or checks != replay_checks:
        failures.append("V070 migration replay was not logically idempotent")
    if not source_unchanged:
        failures.append("replica validation changed the source database")
    return {
        "status": "passed" if not failures else "failed",
        "source_database": {"name": source.name, **source_state},
        "replica_database": {
            "name": replica.name,
            "sha256": file_sha256(replica),
            "size": replica.stat().st_size,
        },
        "preflight": preflight_report,
        "recovery": {"applied": applied_recovery, "applied_count": len(applied_recovery)},
        "migration": {
            "executed_migrations": executed,
            "expected_version": LATEST_VERSION,
            "checks": checks,
        },
        "protected_comparison": protected_comparison,
        "business_fact_baseline": fact_baseline,
        "assignments": assignments,
        "legacy_v1_parity": parity,
        "idempotent_replay": {
            "ok": first_snapshot == replay_snapshot and checks == replay_checks,
            "snapshot_sha256": _digest(first_snapshot),
        },
        "source_unchanged": source_unchanged,
        "blocking_failures": failures,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Create, migrate and validate a disposable position V070 SQLite replica"
    )
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--replica-db", required=True)
    parser.add_argument("--recovery-manifest")
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-replica-validation", action="store_true")
    args = parser.parse_args(argv)
    if not args.apply or not args.confirm_replica_validation:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error": "replica creation requires --apply and --confirm-replica-validation",
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1
    try:
        report = validate_replica(
            args.source_db,
            args.replica_db,
            recovery_manifest=args.recovery_manifest,
        )
        evidence = Path(args.evidence).resolve()
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "status": report["status"],
                "evidence": {"path": str(evidence), "sha256": file_sha256(evidence)},
                "source_unchanged": report["source_unchanged"],
                "blocking_failure_count": len(report["blocking_failures"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
