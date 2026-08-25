#!/usr/bin/env python3
"""Read-only V074/V075 preflight and disposable replica validation controls."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


SOURCE_VERSION = 73
# V075 repairs the legacy empty process/route content digests required by the
# V074 exact pending-route price API. Keep this runbook's replica validation
# inclusive of both migrations so it cannot report a partially repaired DB as
# production-ready.
TARGET_VERSION = 75
PRICE_STATUSES = ("draft", "approved", "retired", "voided")
PENDING_PRICE_FLAGS = (
    "ROUTE_PRICE_PENDING_REFERENCE_ENABLED",
    "ROUTE_PRICE_PENDING_COMPAT_AUDIT_ENABLED",
    "ROUTE_PRICE_PENDING_WRITE_ENABLED",
)
PENDING_PRICE_FLAG_STAGES = (
    ("closed", (False, False, False)),
    ("observe", (True, True, False)),
    ("write", (True, True, True)),
)
REQUIRED_TABLES = (
    "route_price_versions",
    "process_routes",
    "process_route_versions",
    "process_route_version_items",
    "processes",
    "process_versions",
    "master_data_release_batches",
    "master_data_release_process_versions",
    "master_data_release_route_versions",
    "master_data_release_price_versions",
    "payroll_detail_lines",
    "payroll_work_price_resolutions",
)


def database_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _open_read_only(path: str | Path) -> sqlite3.Connection:
    source = Path(path).resolve()
    if not source.is_file():
        raise RuntimeError(f"database does not exist: {source}")
    db = sqlite3.connect("file:" + source.as_posix() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA query_only=ON")
    return db


def _table_names(db: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    }


def _foreign_key_violations(db: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        {
            "table": row[0],
            "rowid": row[1],
            "parent": row[2],
            "foreign_key_index": row[3],
        }
        for row in db.execute("PRAGMA foreign_key_check").fetchall()
    ]


def database_health(db: sqlite3.Connection) -> dict[str, Any]:
    tables = _table_names(db)
    return {
        "user_version": int(db.execute("PRAGMA user_version").fetchone()[0]),
        "query_only": int(db.execute("PRAGMA query_only").fetchone()[0]),
        "integrity_check": str(db.execute("PRAGMA integrity_check").fetchone()[0]),
        "foreign_key_check": _foreign_key_violations(db),
        "page_count": int(db.execute("PRAGMA page_count").fetchone()[0]),
        "missing_tables": sorted(set(REQUIRED_TABLES) - tables),
    }


def price_aggregates(db: sqlite3.Connection) -> dict[str, Any]:
    by_status = {
        status: {
            "rows": 0,
            "normal_unit_price_micros": 0,
            "exact_binding_rows": 0,
            "distinct_exact_bindings": 0,
        }
        for status in PRICE_STATUSES
    }
    for row in db.execute(
        "SELECT status,COUNT(*) AS rows,"
        "COALESCE(SUM(normal_unit_price_micros),0) AS normal_unit_price_micros,"
        "SUM(CASE WHEN route_version_id IS NOT NULL AND process_version_id IS NOT NULL "
        "THEN 1 ELSE 0 END) AS exact_binding_rows,"
        "COUNT(DISTINCT CASE WHEN route_version_id IS NOT NULL "
        "AND process_version_id IS NOT NULL THEN "
        "CAST(route_version_id AS TEXT)||':'||CAST(process_version_id AS TEXT) END) "
        "AS distinct_exact_bindings "
        "FROM route_price_versions GROUP BY status ORDER BY status"
    ).fetchall():
        by_status[str(row["status"])] = {
            "rows": int(row["rows"]),
            "normal_unit_price_micros": int(row["normal_unit_price_micros"]),
            "exact_binding_rows": int(row["exact_binding_rows"]),
            "distinct_exact_bindings": int(row["distinct_exact_bindings"]),
        }
    draft_bindings = [
        dict(row)
        for row in db.execute(
            "SELECT price.id AS price_version_id,price.route_id,price.route_version_id,"
            "route_version.status AS route_version_status,price.process_id,"
            "price.process_version_id,process_version.status AS process_version_status,"
            "price.normal_unit_price_micros,price.valid_from,price.valid_to "
            "FROM route_price_versions price "
            "LEFT JOIN process_route_versions route_version "
            "ON route_version.id=price.route_version_id "
            "LEFT JOIN process_versions process_version "
            "ON process_version.id=price.process_version_id "
            "WHERE price.status='draft' ORDER BY price.id"
        ).fetchall()
    ]
    preserved_legacy_unbound_rows = int(
        db.execute(
            "SELECT COUNT(*) FROM route_price_versions price "
            "WHERE price.status='retired' "
            "AND price.legacy_binding_unavailable=1 "
            "AND price.route_version_id IS NULL "
            "AND price.process_version_id IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM payroll_detail_lines detail "
            "WHERE detail.price_version_id=price.id) "
            "AND NOT EXISTS (SELECT 1 FROM payroll_work_price_resolutions resolution "
            "WHERE resolution.price_version_id=price.id)"
        ).fetchone()[0]
    )
    return {
        "by_status": by_status,
        "total": {
            "rows": sum(item["rows"] for item in by_status.values()),
            "normal_unit_price_micros": sum(
                item["normal_unit_price_micros"] for item in by_status.values()
            ),
            "preserved_legacy_unbound_rows": preserved_legacy_unbound_rows,
        },
        "draft_bindings": draft_bindings,
    }


def blocking_price_differences(db: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    empty_bindings = [
        dict(row)
        for row in db.execute(
            "SELECT id AS price_version_id,status,route_id,route_version_id,"
            "process_id,process_version_id,legacy_binding_unavailable "
            "FROM route_price_versions price WHERE (route_version_id IS NULL "
            "OR process_version_id IS NULL) AND NOT (status='retired' "
            "AND legacy_binding_unavailable=1 AND route_version_id IS NULL "
            "AND process_version_id IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM payroll_detail_lines detail "
            "WHERE detail.price_version_id=price.id) "
            "AND NOT EXISTS (SELECT 1 FROM payroll_work_price_resolutions resolution "
            "WHERE resolution.price_version_id=price.id)) ORDER BY id"
        ).fetchall()
    ]
    binding_mismatches = [
        dict(row)
        for row in db.execute(
            "SELECT price.id AS price_version_id,price.status,price.route_id,"
            "price.route_version_id,price.process_id,price.process_version_id,"
            "CASE WHEN route_version.id IS NULL THEN 'missing_route_version' "
            "WHEN process_version.id IS NULL THEN 'missing_process_version' "
            "WHEN route_version.process_route_id<>price.route_id THEN 'route_root_mismatch' "
            "WHEN process_version.process_id<>price.process_id THEN 'process_root_mismatch' "
            "WHEN item.id IS NULL THEN 'route_node_mismatch' END AS reason "
            "FROM route_price_versions price "
            "LEFT JOIN process_route_versions route_version "
            "ON route_version.id=price.route_version_id "
            "LEFT JOIN process_versions process_version "
            "ON process_version.id=price.process_version_id "
            "LEFT JOIN process_route_version_items item "
            "ON item.route_version_id=price.route_version_id "
            "AND item.process_id=price.process_id "
            "AND item.process_version_id=price.process_version_id "
            "WHERE price.route_version_id IS NOT NULL "
            "AND price.process_version_id IS NOT NULL AND ("
            "route_version.id IS NULL OR process_version.id IS NULL "
            "OR route_version.process_route_id<>price.route_id "
            "OR process_version.process_id<>price.process_id OR item.id IS NULL) "
            "ORDER BY price.id"
        ).fetchall()
    ]
    duplicate_pending_drafts = []
    rows = db.execute(
        "SELECT price.route_version_id,price.process_version_id,COUNT(*) AS rows,"
        "GROUP_CONCAT(price.id) AS price_version_ids "
        "FROM route_price_versions price "
        "JOIN process_route_versions route_version "
        "ON route_version.id=price.route_version_id "
        "JOIN process_versions process_version "
        "ON process_version.id=price.process_version_id "
        "WHERE price.status='draft' AND route_version.status='pending_approval' "
        "AND process_version.status IN ('published','pending_approval') "
        "GROUP BY price.route_version_id,price.process_version_id "
        "HAVING COUNT(*)>1 ORDER BY price.route_version_id,price.process_version_id"
    ).fetchall()
    for row in rows:
        duplicate_pending_drafts.append(
            {
                "route_version_id": int(row["route_version_id"]),
                "process_version_id": int(row["process_version_id"]),
                "rows": int(row["rows"]),
                "price_version_ids": sorted(
                    int(value) for value in str(row["price_version_ids"]).split(",")
                ),
            }
        )
    return {
        "empty_bindings": empty_bindings,
        "binding_mismatches": binding_mismatches,
        "duplicate_pending_drafts": duplicate_pending_drafts,
    }


def _member_ids(
    db: sqlite3.Connection, table: str, id_column: str, batch_id: int
) -> list[int]:
    return [
        int(row[0])
        for row in db.execute(
            f"SELECT {id_column} FROM {table} WHERE batch_id=? ORDER BY {id_column}",
            (batch_id,),
        ).fetchall()
    ]


def release_batch_summary(db: sqlite3.Connection) -> dict[str, Any]:
    status_counts = {
        str(row["status"]): int(row["rows"])
        for row in db.execute(
            "SELECT status,COUNT(*) AS rows FROM master_data_release_batches "
            "GROUP BY status ORDER BY status"
        ).fetchall()
    }
    active_batches = []
    for row in db.execute(
        "SELECT id,release_no,status,impact_digest,row_version,created_at "
        "FROM master_data_release_batches "
        "WHERE status IN ('draft','pending_approval') ORDER BY id"
    ).fetchall():
        batch_id = int(row["id"])
        price_members = [
            dict(member)
            for member in db.execute(
                "SELECT member.price_version_id,price.status,price.route_version_id,"
                "price.process_version_id,price.normal_unit_price_micros "
                "FROM master_data_release_price_versions member "
                "JOIN route_price_versions price ON price.id=member.price_version_id "
                "WHERE member.batch_id=? ORDER BY member.price_version_id",
                (batch_id,),
            ).fetchall()
        ]
        active_batches.append(
            {
                **dict(row),
                "process_version_ids": _member_ids(
                    db,
                    "master_data_release_process_versions",
                    "process_version_id",
                    batch_id,
                ),
                "route_version_ids": _member_ids(
                    db,
                    "master_data_release_route_versions",
                    "route_version_id",
                    batch_id,
                ),
                "price_members": price_members,
            }
        )
    return {"status_counts": status_counts, "active_batches": active_batches}


def payroll_price_reference_summary(db: sqlite3.Connection) -> dict[str, Any]:
    def totals(table: str) -> dict[str, int]:
        row = db.execute(
            f"SELECT COUNT(*) AS rows,COUNT(DISTINCT price_version_id) AS prices "
            f"FROM {table} WHERE price_version_id IS NOT NULL"
        ).fetchone()
        return {
            "rows": int(row["rows"]),
            "distinct_price_versions": int(row["prices"]),
        }

    by_price_status = {
        status: {"detail_lines": 0, "work_price_resolutions": 0}
        for status in PRICE_STATUSES
    }
    for label, table in (
        ("detail_lines", "payroll_detail_lines"),
        ("work_price_resolutions", "payroll_work_price_resolutions"),
    ):
        for row in db.execute(
            f"SELECT price.status,COUNT(*) AS rows FROM {table} reference "
            "JOIN route_price_versions price ON price.id=reference.price_version_id "
            "WHERE reference.price_version_id IS NOT NULL "
            "GROUP BY price.status ORDER BY price.status"
        ).fetchall():
            by_price_status.setdefault(
                str(row["status"]),
                {"detail_lines": 0, "work_price_resolutions": 0},
            )[label] = int(row["rows"])
    return {
        "detail_lines": totals("payroll_detail_lines"),
        "work_price_resolutions": totals("payroll_work_price_resolutions"),
        "by_price_status": by_price_status,
    }


def _health_failures(health: dict[str, Any]) -> list[dict[str, Any]]:
    failures = []
    if health["user_version"] not in {SOURCE_VERSION, TARGET_VERSION}:
        failures.append(
            {
                "type": "unexpected_user_version",
                "expected": [SOURCE_VERSION, TARGET_VERSION],
                "actual": health["user_version"],
            }
        )
    if health["query_only"] != 1:
        failures.append({"type": "database_not_query_only"})
    if health["integrity_check"] != "ok":
        failures.append(
            {"type": "integrity_check", "value": health["integrity_check"]}
        )
    if health["foreign_key_check"]:
        failures.append(
            {
                "type": "foreign_key_check",
                "rows": health["foreign_key_check"],
            }
        )
    if health["missing_tables"]:
        failures.append(
            {"type": "missing_tables", "tables": health["missing_tables"]}
        )
    return failures


def run_preflight(path: str | Path) -> dict[str, Any]:
    source = Path(path).resolve()
    if not source.is_file():
        raise RuntimeError(f"database does not exist: {source}")
    before = {"sha256": database_sha256(source), "size": source.stat().st_size}
    db = _open_read_only(source)
    try:
        health = database_health(db)
        aggregates = price_aggregates(db)
        blocking = blocking_price_differences(db)
        batches = release_batch_summary(db)
        payroll = payroll_price_reference_summary(db)
    finally:
        db.close()
    after = {"sha256": database_sha256(source), "size": source.stat().st_size}
    if before != after:
        raise RuntimeError("read-only preflight changed the source database")
    blocking_failures = _health_failures(health)
    blocking_failures.extend(
        {"type": key, "rows": len(items)}
        for key, items in blocking.items()
        if items
    )
    report = {
        "status": "passed" if not blocking_failures else "blocked",
        "mode": "read_only_preflight",
        "database": {**health, **before},
        "price_aggregates": aggregates,
        "blocking": blocking,
        "blocking_failures": blocking_failures,
        "release_batches": batches,
        "payroll_references": payroll,
        "source_unchanged": True,
    }
    report["summary_sha256"] = canonical_sha256(report)
    return report


def _online_backup(source_path: Path, replica_path: Path) -> None:
    if source_path == replica_path:
        raise RuntimeError("replica database cannot overwrite the source database")
    if replica_path.exists():
        raise RuntimeError(f"replica destination already exists: {replica_path}")
    replica_path.parent.mkdir(parents=True, exist_ok=True)
    source = _open_read_only(source_path)
    target = sqlite3.connect(replica_path)
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()


def _failed_replica_report(
    source: dict[str, Any], differences: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "status": "blocked",
        "source": source,
        "replica": None,
        "source_unchanged": source.get("source_unchanged", False),
        "migration": None,
        "aggregate_comparison": {},
        "release_batches_equal": False,
        "payroll_references_equal": False,
        "blocking_differences": differences,
    }


def validate_replica(
    source_path: str | Path, replica_path: str | Path
) -> dict[str, Any]:
    from modules.migrations import run_migrations

    source_path = Path(source_path).resolve()
    replica_path = Path(replica_path).resolve()
    source_before = {
        "sha256": database_sha256(source_path),
        "size": source_path.stat().st_size,
    }
    source = run_preflight(source_path)
    source_blocking = list(source["blocking_failures"])
    if source["database"]["user_version"] != SOURCE_VERSION:
        source_blocking.append(
            {
                "type": "replica_source_version",
                "expected": SOURCE_VERSION,
                "actual": source["database"]["user_version"],
            }
        )
    if source_blocking:
        return _failed_replica_report(source, source_blocking)

    _online_backup(source_path, replica_path)
    source_after_backup = {
        "sha256": database_sha256(source_path),
        "size": source_path.stat().st_size,
    }
    if source_before != source_after_backup:
        return _failed_replica_report(
            source, [{"type": "source_changed_during_replica_copy"}]
        )

    replica_db = sqlite3.connect(replica_path)
    replica_db.row_factory = sqlite3.Row
    replica_db.execute("PRAGMA foreign_keys=ON")
    try:
        executed = int(run_migrations(replica_db))
        target_version = int(replica_db.execute("PRAGMA user_version").fetchone()[0])
    finally:
        replica_db.close()

    replica = run_preflight(replica_path)
    source_after = {
        "sha256": database_sha256(source_path),
        "size": source_path.stat().st_size,
    }
    source_unchanged = source_before == source_after
    aggregate_comparison = {}
    for status in ("approved", "retired"):
        before = source["price_aggregates"]["by_status"][status]
        after = replica["price_aggregates"]["by_status"][status]
        aggregate_comparison[status] = {
            "source": before,
            "replica": after,
            "equal": before == after,
        }
    release_batches_equal = (
        source["release_batches"] == replica["release_batches"]
    )
    payroll_references_equal = (
        source["payroll_references"] == replica["payroll_references"]
    )
    differences = []
    if not source_unchanged:
        differences.append({"type": "source_database_changed"})
    if target_version != TARGET_VERSION:
        differences.append(
            {
                "type": "target_user_version",
                "expected": TARGET_VERSION,
                "actual": target_version,
            }
        )
    differences.extend(
        {**item, "type": f"replica_{item['type']}"}
        for item in replica["blocking_failures"]
    )
    for status, comparison in aggregate_comparison.items():
        if not comparison["equal"]:
            differences.append(
                {"type": "price_aggregate_changed", "status": status, **comparison}
            )
    if not release_batches_equal:
        differences.append(
            {
                "type": "release_batch_summary_changed",
                "source": source["release_batches"],
                "replica": replica["release_batches"],
            }
        )
    if not payroll_references_equal:
        differences.append(
            {
                "type": "payroll_price_references_changed",
                "source": source["payroll_references"],
                "replica": replica["payroll_references"],
            }
        )
    return {
        "status": "passed" if not differences else "failed",
        "source": source,
        "replica": replica,
        "source_unchanged": source_unchanged,
        "migration": {
            "source_version": source["database"]["user_version"],
            "target_version": target_version,
            "executed_migrations": executed,
        },
        "aggregate_comparison": aggregate_comparison,
        "release_batches_equal": release_batches_equal,
        "payroll_references_equal": payroll_references_equal,
        "blocking_differences": differences,
    }


def _parse_bool(value: str, flag: str) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise RuntimeError(f"invalid boolean value for {flag}: {value}")


def _flag_stage(flags: dict[str, bool]) -> tuple[int, str]:
    actual = tuple(bool(flags.get(flag, False)) for flag in PENDING_PRICE_FLAGS)
    for index, (stage, values) in enumerate(PENDING_PRICE_FLAG_STAGES):
        if actual == values:
            return index, stage
    raise RuntimeError(
        "pending route price flags must match the approved staged states: "
        "closed, observe, or write"
    )


def read_pending_price_flags(path: str | Path) -> dict[str, bool]:
    env_path = Path(path).resolve()
    if not env_path.is_file():
        raise RuntimeError(f"environment file does not exist: {env_path}")
    values: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key not in PENDING_PRICE_FLAGS:
            continue
        if key in values:
            raise RuntimeError(f"duplicate pending route price flag: {key}")
        values[key] = value.strip().strip("\"'")
    result = {
        flag: _parse_bool(values.get(flag, "false"), flag)
        for flag in PENDING_PRICE_FLAGS
    }
    _flag_stage(result)
    return result


def validate_pending_price_flag_transition(
    current: dict[str, bool], requested: dict[str, bool]
) -> dict[str, Any]:
    current_index, current_stage = _flag_stage(current)
    requested_index, requested_stage = _flag_stage(requested)
    if requested_index < current_index:
        raise RuntimeError("pending route price flags cannot move backward without rollback")
    if requested_index > current_index + 1:
        raise RuntimeError("pending route price flags cannot skip an approved stage")
    return {
        "current_stage": current_stage,
        "stage": requested_stage,
        "changed": requested_index != current_index,
        "current": {flag: bool(current.get(flag, False)) for flag in PENDING_PRICE_FLAGS},
        "requested": {
            flag: bool(requested.get(flag, False)) for flag in PENDING_PRICE_FLAGS
        },
    }


def _migration_plan(path: str | Path) -> dict[str, Any]:
    from modules.migrations import pending_migrations

    source = Path(path).resolve()
    before = database_sha256(source)
    db = _open_read_only(source)
    try:
        version = int(db.execute("PRAGMA user_version").fetchone()[0])
        plan = [
            {"version": migration_version, "description": description}
            for migration_version, description, _ in pending_migrations(version)
        ]
    finally:
        db.close()
    if database_sha256(source) != before:
        raise RuntimeError("migration plan inspection changed the source database")
    return {"source_version": version, "pending_migrations": plan, "sha256": before}


def _write_report(path: str | Path, report: dict[str, Any]) -> None:
    output = Path(path).resolve()
    if output.exists():
        raise RuntimeError(f"evidence output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _emit(report: dict[str, Any], output: str | None) -> None:
    if output:
        _write_report(output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Pending route price V074 controls")
    subparsers = parser.add_subparsers(dest="command", required=True)

    preflight_parser = subparsers.add_parser("preflight")
    preflight_parser.add_argument("--db", required=True)
    preflight_parser.add_argument("--output")

    replica_parser = subparsers.add_parser("validate-replica")
    replica_parser.add_argument("--source-db", required=True)
    replica_parser.add_argument("--replica-db", required=True)
    replica_parser.add_argument("--output")

    flags_parser = subparsers.add_parser("flags")
    flags_parser.add_argument("--env", required=True)
    flags_parser.add_argument("--output")

    transition_parser = subparsers.add_parser("validate-flag-transition")
    transition_parser.add_argument("--current-env", required=True)
    transition_parser.add_argument("--candidate-env", required=True)
    transition_parser.add_argument("--output")

    plan_parser = subparsers.add_parser("migration-plan")
    plan_parser.add_argument("--db", required=True)
    plan_parser.add_argument("--output")

    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            report = run_preflight(args.db)
            _emit(report, args.output)
            return 0 if report["status"] == "passed" else 1
        if args.command == "validate-replica":
            report = validate_replica(args.source_db, args.replica_db)
            _emit(report, args.output)
            return 0 if report["status"] == "passed" else 1
        if args.command == "flags":
            flags = read_pending_price_flags(args.env)
            _, stage = _flag_stage(flags)
            _emit({"status": "passed", "stage": stage, "flags": flags}, args.output)
            return 0
        if args.command == "validate-flag-transition":
            report = validate_pending_price_flag_transition(
                read_pending_price_flags(args.current_env),
                read_pending_price_flags(args.candidate_env),
            )
            _emit({"status": "passed", **report}, args.output)
            return 0
        report = _migration_plan(args.db)
        _emit({"status": "passed", **report}, args.output)
        return 0
    except Exception as exc:
        print(
            json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2


__all__ = [
    "blocking_price_differences",
    "canonical_sha256",
    "database_health",
    "database_sha256",
    "payroll_price_reference_summary",
    "price_aggregates",
    "read_pending_price_flags",
    "release_batch_summary",
    "run_preflight",
    "validate_pending_price_flag_transition",
    "validate_replica",
]


if __name__ == "__main__":
    raise SystemExit(main())
