#!/usr/bin/env python3
"""Run the position V070 release gate against an explicit read-only database."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.recover_position_processes import (  # noqa: E402
    file_sha256,
    load_manifest,
    open_read_only,
    unresolved_manual_items,
)


PRECHECK_THRESHOLDS = {
    "invalid_position_status": 0,
    "duplicate_position_name": 0,
    "missing_position_process": 0,
    "duplicate_position_process": 0,
    "active_user_missing_position": 0,
    "overlapping_open_assignment": 0,
    "unresolved_recovery_items": 0,
    "foreign_key_violations": 0,
}


REQUIRED_SCHEMA = {
    "positions": {"id", "name", "status"},
    "position_processes": {"id", "position_id", "process_id"},
    "processes": {"id"},
    "users": {"id", "position_id", "status"},
    "performance_assignment_history": {"id", "user_id", "valid_to"},
}


def _table_exists(db: sqlite3.Connection, table: str) -> bool:
    return (
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(db, table):
        return set()
    return {str(row[1]) for row in db.execute(f'PRAGMA table_info("{table}")')}


def _rows(db: sqlite3.Connection, sql: str, params=()) -> list[dict[str, Any]]:
    return [dict(row) for row in db.execute(sql, params).fetchall()]


def _schema_issues(db: sqlite3.Connection) -> list[dict[str, str]]:
    issues = []
    for table, required in REQUIRED_SCHEMA.items():
        actual = _columns(db, table)
        if not actual:
            issues.append({"table": table, "issue": "missing_table"})
            continue
        for column in sorted(required - actual):
            issues.append(
                {"table": table, "column": column, "issue": "missing_column"}
            )
    return issues


def _collect_details(db: sqlite3.Connection, schema_issues: list[dict[str, str]]) -> dict:
    unavailable = {item["table"] for item in schema_issues}
    details: dict[str, list[dict[str, Any]]] = {
        key: [] for key in PRECHECK_THRESHOLDS if key != "unresolved_recovery_items"
    }
    if "positions" not in unavailable:
        details["invalid_position_status"] = _rows(
            db,
            "SELECT id,status FROM positions "
            "WHERE COALESCE(status,'') NOT IN ('active','inactive') ORDER BY id",
        )
        details["duplicate_position_name"] = _rows(
            db,
            "SELECT LOWER(TRIM(name)) AS normalized_name,COUNT(*) AS count,"
            "GROUP_CONCAT(id) AS ids FROM positions GROUP BY LOWER(TRIM(name)) "
            "HAVING COUNT(*)>1 ORDER BY LOWER(TRIM(name))",
        )
    if not ({"positions", "processes", "position_processes"} & unavailable):
        details["missing_position_process"] = _rows(
            db,
            "SELECT mapping.id,mapping.position_id,mapping.process_id,"
            "CASE WHEN position.id IS NULL THEN 'missing_position' "
            "ELSE 'missing_process' END AS reason "
            "FROM position_processes mapping "
            "LEFT JOIN positions position ON position.id=mapping.position_id "
            "LEFT JOIN processes process ON process.id=mapping.process_id "
            "WHERE position.id IS NULL OR process.id IS NULL ORDER BY mapping.id",
        )
        details["duplicate_position_process"] = _rows(
            db,
            "SELECT position_id,process_id,COUNT(*) AS count,GROUP_CONCAT(id) AS ids "
            "FROM position_processes GROUP BY position_id,process_id "
            "HAVING COUNT(*)>1 ORDER BY position_id,process_id",
        )
    if not ({"positions", "users"} & unavailable):
        details["active_user_missing_position"] = _rows(
            db,
            "SELECT user.id,user.position_id FROM users user "
            "LEFT JOIN positions position ON position.id=user.position_id "
            "WHERE user.status='active' AND user.position_id IS NOT NULL "
            "AND position.id IS NULL ORDER BY user.id",
        )
    if "performance_assignment_history" not in unavailable:
        details["overlapping_open_assignment"] = _rows(
            db,
            "SELECT user_id,COUNT(*) AS count,GROUP_CONCAT(id) AS ids "
            "FROM performance_assignment_history WHERE COALESCE(valid_to,'')='' "
            "GROUP BY user_id HAVING COUNT(*)>1 ORDER BY user_id",
        )
    try:
        details["foreign_key_violations"] = [
            {
                "table": row[0],
                "rowid": row[1],
                "parent": row[2],
                "foreign_key_index": row[3],
            }
            for row in db.execute("PRAGMA foreign_key_check").fetchall()
        ]
    except sqlite3.DatabaseError as exc:
        details["foreign_key_violations"] = [{"error": str(exc)}]
    return details


def preflight(
    db_path: str | Path,
    *,
    recovery_manifest: str | Path | dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = Path(db_path).resolve()
    if not source.is_file():
        raise RuntimeError(f"database does not exist: {source}")
    before = {"sha256": file_sha256(source), "size": source.stat().st_size}
    manifest = load_manifest(recovery_manifest)
    unresolved = unresolved_manual_items(manifest)
    db = open_read_only(source)
    try:
        query_only = int(db.execute("PRAGMA query_only").fetchone()[0])
        schema_version = int(db.execute("PRAGMA user_version").fetchone()[0])
        schema_issues = _schema_issues(db)
        details = _collect_details(db, schema_issues)
        integrity_check = str(db.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        db.close()

    checks = {
        key: len(details.get(key, []))
        for key in PRECHECK_THRESHOLDS
        if key != "unresolved_recovery_items"
    }
    checks["unresolved_recovery_items"] = len(unresolved)
    checks = {key: checks[key] for key in PRECHECK_THRESHOLDS}
    threshold_results = {
        key: {
            "value": checks[key],
            "maximum": maximum,
            "ok": checks[key] <= maximum,
        }
        for key, maximum in PRECHECK_THRESHOLDS.items()
    }
    after = {"sha256": file_sha256(source), "size": source.stat().st_size}
    source_unchanged = before == after
    ready = (
        not schema_issues
        and integrity_check == "ok"
        and query_only == 1
        and source_unchanged
        and all(item["ok"] for item in threshold_results.values())
    )
    return {
        "status": "passed" if ready else "blocked",
        "ready": ready,
        "mode": "read_only_preflight",
        "schema_version": schema_version,
        "database": {
            "name": source.name,
            **before,
            "query_only": query_only,
            "integrity_check": integrity_check,
        },
        "checks": checks,
        "thresholds": PRECHECK_THRESHOLDS.copy(),
        "threshold_results": threshold_results,
        "details": {**details, "unresolved_recovery_items": unresolved},
        "schema_issues": schema_issues,
        "source_unchanged": source_unchanged,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only position V070 preflight")
    parser.add_argument("--db", required=True)
    parser.add_argument("--recovery-manifest")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        report = preflight(args.db, recovery_manifest=args.recovery_manifest)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        destination = Path(args.output).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
