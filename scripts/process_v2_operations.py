#!/usr/bin/env python3
"""Shared operations primitives for the process-master-data V2 cutover."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Any


os.environ.setdefault("SECRET_KEY", "offline-process-v2-operations")


PROCESS_FLAG_STAGES = (
    ("query", "PROCESS_VERSIONED_QUERY_ENABLED"),
    ("compat_audit", "PROCESS_VERSION_COMPAT_AUDIT_ENABLED"),
    ("versioned_write", "PROCESS_VERSIONED_WRITE_ENABLED"),
    ("legacy_block", "PROCESS_LEGACY_WRITE_BLOCKED"),
)
PROCESS_FLAG_NAMES = tuple(flag for _, flag in PROCESS_FLAG_STAGES)

SNAPSHOT_GROUPS = {
    "roots": ("processes", "process_routes"),
    "versions": (
        "process_versions",
        "process_route_versions",
        "process_version_migration_manifests",
        "process_price_binding_migration_events",
    ),
    "route_nodes": ("process_route_items", "process_route_version_items"),
    "prices": ("route_price_versions", "master_data_release_price_versions"),
    "orders": ("orders", "order_processes", "work_records"),
    "facts": (
        "material_consumptions",
        "order_completion_focus_events",
        "process_handoff_reviews",
        "process_quality_evaluation_tasks",
        "process_quality_evaluation_task_audits",
        "process_quality_evaluations",
        "quality_inspection_tasks",
        "quality_inspections",
        "quality_nonconformances",
        "rework_records",
        "scrap_records",
        "work_time_records",
        "work_time_standards",
        "payroll_detail_lines",
        "payroll_work_price_resolutions",
        "performance_quality_events",
        "performance_source_facts",
    ),
}

PROTECTED_TABLES = frozenset(
    {
        "processes",
        "process_routes",
        "process_route_items",
        "route_price_versions",
        "orders",
        "order_processes",
        "work_records",
        "payroll_work_price_resolutions",
        *SNAPSHOT_GROUPS["facts"],
    }
)

SUM_COLUMNS = (
    "quantity",
    "completed",
    "amount_cents",
    "normal_unit_price_micros",
    "reported_quantity",
    "normal_quantity",
    "rework_quantity",
)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def payload_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def database_sha256(path: str | Path) -> str:
    source = Path(path)
    if not source.is_file():
        raise RuntimeError(f"database does not exist: {source}")
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_sha256(path: str | Path) -> str:
    return database_sha256(path)


def _open_read_only(path: str | Path) -> sqlite3.Connection:
    source = Path(path).resolve()
    if not source.is_file():
        raise RuntimeError(f"database does not exist: {source}")
    uri = "file:" + source.as_posix() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("PRAGMA query_only=ON")
    return db


def _rows(db: sqlite3.Connection, sql: str, params=()) -> list[dict]:
    return [dict(row) for row in db.execute(sql, params).fetchall()]


def _scalar(db: sqlite3.Connection, sql: str, params=(), default=0):
    row = db.execute(sql, params).fetchone()
    return default if row is None or row[0] is None else row[0]


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
    return {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}


def database_checks(db: sqlite3.Connection) -> dict:
    return {
        "user_version": int(_scalar(db, "PRAGMA user_version")),
        "integrity_check": str(_scalar(db, "PRAGMA integrity_check", default="")),
        "foreign_key_violations": len(_rows(db, "PRAGMA foreign_key_check")),
        "query_only": int(_scalar(db, "PRAGMA query_only")),
    }


def _table_metric(db: sqlite3.Connection, table: str) -> dict:
    column_rows = (
        db.execute(f'PRAGMA table_info("{table}")').fetchall()
        if _table_exists(db, table)
        else []
    )
    ordered_columns = [row[1] for row in column_rows]
    columns = set(ordered_columns)
    if not columns:
        return {"exists": False, "count": 0}
    metric = {
        "exists": True,
        "count": int(_scalar(db, f'SELECT COUNT(*) FROM "{table}"')),
        "columns": ordered_columns,
    }
    if "id" in columns:
        metric["id_sum"] = int(
            _scalar(db, f'SELECT COALESCE(SUM(id),0) FROM "{table}"')
        )
    for column in SUM_COLUMNS:
        if column in columns:
            metric[column + "_sum"] = _scalar(
                db, f'SELECT COALESCE(SUM("{column}"),0) FROM "{table}"'
            )
    quoted_columns = ",".join(f'"{column}"' for column in ordered_columns)
    order_columns = ["id"] if "id" in columns else ordered_columns
    order_by = ",".join(f'"{column}"' for column in order_columns)
    digests = {column: hashlib.sha256() for column in ordered_columns}
    for row_number, row in enumerate(
        db.execute(f'SELECT {quoted_columns} FROM "{table}" ORDER BY {order_by}')
    ):
        for index, column in enumerate(ordered_columns):
            digests[column].update(
                canonical_json([row_number, row[index]]).encode("utf-8")
            )
    metric["column_sha256"] = {
        column: digests[column].hexdigest() for column in ordered_columns
    }
    return metric


def database_snapshot(path: str | Path) -> dict:
    db = _open_read_only(path)
    try:
        groups = {
            group: {table: _table_metric(db, table) for table in tables}
            for group, tables in SNAPSHOT_GROUPS.items()
        }
        checks = database_checks(db)
    finally:
        db.close()
    summary = {**groups, "summary": checks}
    summary["summary"]["database_sha256"] = database_sha256(path)
    return summary


def _duplicate_rows(db: sqlite3.Connection, table: str, fields: tuple[str, ...]):
    columns = _columns(db, table)
    if not set(fields) <= columns:
        return []
    expressions = [f"LOWER(TRIM(COALESCE(\"{field}\",'')))" for field in fields]
    select = ",".join(f'{expr} AS "{field}"' for expr, field in zip(expressions, fields))
    group = ",".join(expressions)
    return _rows(
        db,
        f'SELECT {select},COUNT(*) AS count,GROUP_CONCAT(id) AS ids FROM "{table}" '
        f"GROUP BY {group} HAVING COUNT(*)>1 ORDER BY {group}",
    )


def collect_duplicates(db: sqlite3.Connection) -> dict:
    return {
        "process_codes": _duplicate_rows(db, "processes", ("process_code",)),
        "route_codes": _duplicate_rows(db, "process_routes", ("route_code",)),
        "process_names": _duplicate_rows(db, "processes", ("category", "name")),
        "route_names": _duplicate_rows(db, "process_routes", ("category", "name")),
        "route_nodes": _duplicate_rows(
            db, "process_route_items", ("route_id", "process_id", "seq_order")
        ),
    }


def collect_category_mismatches(db: sqlite3.Connection) -> list[dict]:
    required = {
        "process_route_items": {"id", "route_id", "process_id"},
        "process_routes": {"id", "category"},
        "processes": {"id", "category"},
    }
    if any(not columns <= _columns(db, table) for table, columns in required.items()):
        return []
    return _rows(
        db,
        "SELECT item.id AS route_item_id,item.route_id,item.process_id,"
        "COALESCE(route.category,'') AS route_category,"
        "COALESCE(process.category,'') AS process_category "
        "FROM process_route_items item "
        "JOIN process_routes route ON route.id=item.route_id "
        "JOIN processes process ON process.id=item.process_id "
        "WHERE TRIM(COALESCE(route.category,''))<>'' "
        "AND TRIM(COALESCE(process.category,''))<>'' "
        "AND LOWER(TRIM(route.category))<>LOWER(TRIM(process.category)) "
        "ORDER BY item.id",
    )


def collect_reference_coverage(db: sqlite3.Connection) -> dict:
    from modules.master_data_references import (
        MASTER_DATA_REFERENCES,
        find_unregistered_reference_columns,
    )

    entries = []
    for spec in MASTER_DATA_REFERENCES:
        columns = _columns(db, spec.table)
        if not columns:
            continue
        for kind, names in (
            ("root", spec.root_columns),
            ("version", spec.version_columns),
            ("csv", spec.csv_columns),
        ):
            for column in names:
                if column not in columns:
                    entries.append(
                        {
                            "entity_type": spec.entity_type,
                            "table": spec.table,
                            "column": column,
                            "kind": kind,
                            "present": False,
                            "rows": 0,
                        }
                    )
                    continue
                entries.append(
                    {
                        "entity_type": spec.entity_type,
                        "table": spec.table,
                        "column": column,
                        "kind": kind,
                        "present": True,
                        "rows": int(
                            _scalar(
                                db,
                                f'SELECT COUNT(*) FROM "{spec.table}" '
                                f'WHERE "{column}" IS NOT NULL',
                            )
                        ),
                    }
                )

    price_columns = _columns(db, "route_price_versions")
    if {"route_id"} <= price_columns:
        price_route_references = {
            "rows": int(
                _scalar(
                    db,
                    "SELECT COUNT(*) FROM route_price_versions WHERE route_id IS NOT NULL",
                )
            ),
            "distinct_routes": int(
                _scalar(
                    db,
                    "SELECT COUNT(DISTINCT route_id) FROM route_price_versions "
                    "WHERE route_id IS NOT NULL",
                )
            ),
            "route_ids": [
                int(row[0])
                for row in db.execute(
                    "SELECT DISTINCT route_id FROM route_price_versions "
                    "WHERE route_id IS NOT NULL ORDER BY route_id"
                ).fetchall()
            ],
        }
    else:
        price_route_references = {"rows": 0, "distinct_routes": 0, "route_ids": []}

    return {
        "catalog_entries": entries,
        "cataloged_non_null_rows": sum(item["rows"] for item in entries),
        "unregistered_columns": [
            {"table": table, "column": column}
            for table, column in find_unregistered_reference_columns(db)
        ],
        "price_route_references": price_route_references,
    }


def _migration_exceptions(db: sqlite3.Connection) -> list[dict]:
    if not _table_exists(db, "process_version_migration_exceptions"):
        return []
    return _rows(
        db,
        "SELECT migration_key,entity_type,legacy_id,reason_code,blocking,"
        "source_summary_json,resolution_status "
        "FROM process_version_migration_exceptions "
        "WHERE resolution_status='open' ORDER BY migration_key,entity_type,legacy_id,id",
    )


def simulate_migrations(source: sqlite3.Connection) -> dict:
    from modules.migrations import LATEST_VERSION, run_migrations

    replica = sqlite3.connect(":memory:")
    replica.row_factory = sqlite3.Row
    source.backup(replica)
    before = int(_scalar(replica, "PRAGMA user_version"))
    error = ""
    executed = 0
    try:
        replica.execute("PRAGMA foreign_keys=ON")
        executed = int(run_migrations(replica))
    except Exception as exc:
        error = str(exc)
    after = int(_scalar(replica, "PRAGMA user_version"))
    result = {
        "status": "passed" if not error and after == LATEST_VERSION else "failed",
        "source_version": before,
        "target_version": LATEST_VERSION,
        "result_version": after,
        "executed_migrations": executed,
        "error": error,
        "exceptions": _migration_exceptions(replica),
    }
    replica.close()
    return result


def _preflight_counts(db: sqlite3.Connection) -> dict:
    return {
        "roots": {
            "processes": _table_metric(db, "processes")["count"],
            "routes": _table_metric(db, "process_routes")["count"],
        },
        "versions": {
            "processes": _table_metric(db, "process_versions")["count"],
            "routes": _table_metric(db, "process_route_versions")["count"],
        },
        "route_nodes": {
            "legacy": _table_metric(db, "process_route_items")["count"],
            "versioned": _table_metric(db, "process_route_version_items")["count"],
        },
        "prices": _table_metric(db, "route_price_versions")["count"],
        "orders": {
            "orders": _table_metric(db, "orders")["count"],
            "order_processes": _table_metric(db, "order_processes")["count"],
            "work_records": _table_metric(db, "work_records")["count"],
        },
        "facts": {
            table: _table_metric(db, table)["count"] for table in SNAPSHOT_GROUPS["facts"]
        },
    }


def run_preflight(path: str | Path) -> dict:
    source_path = Path(path).resolve()
    before_hash = database_sha256(source_path)
    db = _open_read_only(source_path)
    try:
        checks = database_checks(db)
        counts = _preflight_counts(db)
        duplicates = collect_duplicates(db)
        category_mismatches = collect_category_mismatches(db)
        reference_coverage = collect_reference_coverage(db)
        existing_exceptions = _migration_exceptions(db)
        migration_simulation = simulate_migrations(db)
    finally:
        db.close()
    after_hash = database_sha256(source_path)
    if before_hash != after_hash:
        raise RuntimeError("read-only preflight changed the source database")

    manual_review = []
    manual_review.extend(
        {"type": "category_mismatch", **item} for item in category_mismatches
    )
    manual_review.extend(
        {"type": "migration_exception", **item}
        for item in existing_exceptions + migration_simulation["exceptions"]
        if item.get("resolution_status") == "open"
    )
    for duplicate_type in ("process_names", "route_names", "route_nodes"):
        manual_review.extend(
            {"type": "duplicate_" + duplicate_type, **item}
            for item in duplicates[duplicate_type]
        )

    blockers = []
    if checks["integrity_check"] != "ok":
        blockers.append({"type": "integrity_check", "value": checks["integrity_check"]})
    if checks["foreign_key_violations"]:
        blockers.append(
            {"type": "foreign_key_violations", "count": checks["foreign_key_violations"]}
        )
    for duplicate_type in ("process_codes", "route_codes"):
        blockers.extend(
            {"type": "duplicate_" + duplicate_type, **item}
            for item in duplicates[duplicate_type]
        )
    if reference_coverage["unregistered_columns"]:
        blockers.append(
            {
                "type": "unregistered_reference_columns",
                "items": reference_coverage["unregistered_columns"],
            }
        )
    if migration_simulation["status"] != "passed":
        blockers.append(
            {
                "type": "migration_simulation_failed",
                "error": migration_simulation["error"],
                "result_version": migration_simulation["result_version"],
            }
        )

    logical_summary = {
        "source_version": checks["user_version"],
        "counts": counts,
        "duplicates": duplicates,
        "category_mismatches": category_mismatches,
        "reference_coverage": reference_coverage,
        "migration_simulation": migration_simulation,
        "manual_review": manual_review,
        "blocking_issues": blockers,
    }
    return {
        "status": "passed" if not blockers else "blocked",
        "mode": "read_only_preflight",
        "database": {**checks, "sha256": before_hash},
        "counts": counts,
        "duplicates": duplicates,
        "category_mismatches": category_mismatches,
        "reference_coverage": reference_coverage,
        "migration_simulation": migration_simulation,
        "manual_review": manual_review,
        "blocking_issues": blockers,
        "summary_sha256": payload_sha256(logical_summary),
        "source_unchanged": True,
    }


def online_backup(source_path: str | Path, target_path: str | Path) -> None:
    source_path = Path(source_path).resolve()
    target_path = Path(target_path).resolve()
    if target_path.exists():
        raise RuntimeError(f"backup destination already exists: {target_path}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    source = _open_read_only(source_path)
    target = sqlite3.connect(str(target_path))
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()


def migrate_database(
    path: str | Path, *, expected_preflight_sha256: str | None = None
) -> dict:
    from modules.migrations import LATEST_VERSION, run_migrations

    database_path = Path(path).resolve()
    preflight = run_preflight(database_path)
    if expected_preflight_sha256 and preflight["summary_sha256"] != expected_preflight_sha256:
        raise RuntimeError("preflight summary SHA-256 does not match the migration input")
    if preflight["status"] != "passed":
        raise RuntimeError("preflight has blocking issues; migration refused")
    before_sha256 = database_sha256(database_path)
    db = sqlite3.connect(str(database_path))
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        executed = int(run_migrations(db))
        checks = database_checks(db)
    finally:
        db.close()
    if checks["user_version"] != LATEST_VERSION:
        raise RuntimeError(f"migration stopped at v{checks['user_version']}, expected v{LATEST_VERSION}")
    if checks["integrity_check"] != "ok" or checks["foreign_key_violations"]:
        raise RuntimeError(f"post-migration database checks failed: {checks}")
    return {
        "status": "passed",
        "source_version": preflight["database"]["user_version"],
        "target_version": LATEST_VERSION,
        "executed_migrations": executed,
        "preflight_summary_sha256": preflight["summary_sha256"],
        "database_sha256_before": before_sha256,
        "database_sha256_after": database_sha256(database_path),
        "database": checks,
    }


def _flatten_differences(source: Any, candidate: Any, prefix="") -> list[dict]:
    if isinstance(source, dict) and isinstance(candidate, dict):
        differences = []
        for key in sorted(set(source) | set(candidate)):
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in source:
                differences.append({"path": path, "source": None, "candidate": candidate[key]})
            elif key not in candidate:
                differences.append({"path": path, "source": source[key], "candidate": None})
            else:
                differences.extend(_flatten_differences(source[key], candidate[key], path))
        return differences
    if source != candidate:
        return [{"path": prefix, "source": source, "candidate": candidate}]
    return []


def _authorized_price_resolution_comparison(
    source_path: str | Path, candidate_path: str | Path
) -> dict:
    from modules.process_v2_price_resolution_manifest import (
        load_price_binding_resolution_manifest,
        topology_sha256,
    )

    manifest = load_price_binding_resolution_manifest()
    source = _open_read_only(source_path)
    candidate = _open_read_only(candidate_path)
    try:
        actions = {
            int(item["source_price_version_id"]): ("fanout", item)
            for item in manifest.get("fanout_prices", [])
        }
        actions.update(
            {
                int(item["price_version_id"]): ("retire_unbound", item)
                for item in manifest.get("retire_unbound_prices", [])
            }
        )
        source_prices = {
            int(row["id"]): dict(row)
            for row in source.execute(
                "SELECT * FROM route_price_versions ORDER BY id"
            ).fetchall()
        }
        applicable = {
            price_id: action
            for price_id, action in actions.items()
            if price_id in source_prices
        }
        if not applicable:
            return {
                "status": "not_applicable",
                "authorized_tables": [],
                "authorized_price_ids": [],
                "clone_count": 0,
                "payroll_detail_rebind_count": 0,
                "price_resolution_rebind_count": 0,
            }

        candidate_prices = {
            int(row["id"]): dict(row)
            for row in candidate.execute(
                "SELECT * FROM route_price_versions ORDER BY id"
            ).fetchall()
        }
        source_columns = [
            row[1] for row in source.execute("PRAGMA table_info(route_price_versions)")
        ]
        retire_time = manifest["retire_effective_at"]
        for price_id, source_row in source_prices.items():
            candidate_row = candidate_prices.get(price_id)
            if candidate_row is None:
                raise RuntimeError(
                    f"authorized price migration removed source price {price_id}"
                )
            action = applicable.get(price_id)
            expected = {column: source_row[column] for column in source_columns}
            if action and action[0] == "retire_unbound":
                expected["status"] = "retired"
                expected["valid_to"] = retire_time
                expected["row_version"] = int(source_row["row_version"]) + 1
            for column, value in expected.items():
                if candidate_row[column] != value:
                    raise RuntimeError(
                        "authorized price migration changed an unexpected source field: "
                        f"price={price_id}, field={column}"
                    )

        event_rows = [
            dict(row)
            for row in candidate.execute(
                "SELECT * FROM process_price_binding_migration_events "
                "WHERE source_price_version_id IN ("
                + ",".join("?" for _ in applicable)
                + ") ORDER BY id",
                sorted(applicable),
            ).fetchall()
        ]
        events_by_source: dict[int, list[dict]] = {}
        for event in event_rows:
            events_by_source.setdefault(int(event["source_price_version_id"]), []).append(
                event
            )

        expected_clone_ids = set()
        family_by_source: dict[int, dict[int, int]] = {}
        authorization = manifest["authorization"]
        for price_id, (action, spec) in applicable.items():
            events = events_by_source.get(price_id, [])
            if action == "retire_unbound":
                if len(events) != 1 or events[0]["action"] != "retire_unbound":
                    raise RuntimeError(
                        f"authorized retirement event mismatch for price {price_id}"
                    )
                if int(events[0]["result_price_version_id"]) != price_id:
                    raise RuntimeError(
                        f"authorized retirement result mismatch for price {price_id}"
                    )
                continue

            expected_digests = set(spec["target_topology_sha256"])
            actual_digests = {event["topology_sha256"] for event in events}
            if actual_digests != expected_digests or len(events) != len(expected_digests):
                raise RuntimeError(
                    f"authorized fanout event topology mismatch for price {price_id}"
                )
            route_prices = {}
            for event in events:
                if (
                    event["approved_by_name"] != authorization["approved_by"]
                    or event["approved_at"] != authorization["approved_at"]
                ):
                    raise RuntimeError(
                        f"authorized fanout approval mismatch for price {price_id}"
                    )
                route_version_id = int(event["route_version_id"])
                route_row = candidate.execute(
                    "SELECT process_route_id FROM process_route_versions WHERE id=?",
                    (route_version_id,),
                ).fetchone()
                nodes = [
                    {
                        "process_id": int(row["process_id"]),
                        "is_required": int(row["is_required"]),
                        "required_audit": int(row["required_audit"]),
                    }
                    for row in candidate.execute(
                        "SELECT process_id,is_required,required_audit "
                        "FROM process_route_version_items WHERE route_version_id=? "
                        "ORDER BY seq_order,id",
                        (route_version_id,),
                    ).fetchall()
                ]
                if route_row is None or topology_sha256(route_row[0], nodes) != event[
                    "topology_sha256"
                ]:
                    raise RuntimeError(
                        f"authorized fanout route evidence mismatch for price {price_id}"
                    )
                result_price_id = int(event["result_price_version_id"])
                result_price = candidate_prices.get(result_price_id)
                if result_price is None:
                    raise RuntimeError(
                        f"authorized fanout result price missing: {result_price_id}"
                    )
                if (
                    int(result_price["route_version_id"]) != route_version_id
                    or int(result_price["process_version_id"])
                    != int(event["process_version_id"])
                ):
                    raise RuntimeError(
                        f"authorized fanout exact binding mismatch: {result_price_id}"
                    )
                route_prices[route_version_id] = result_price_id
                if event["action"] == "clone_binding":
                    expected_clone_ids.add(result_price_id)
                elif (
                    event["action"] != "bind_primary"
                    or result_price_id != price_id
                    or event["topology_sha256"] != spec["primary_topology_sha256"]
                ):
                    raise RuntimeError(
                        f"authorized fanout primary event mismatch for price {price_id}"
                    )
            family_by_source[price_id] = route_prices

        extra_price_ids = set(candidate_prices) - set(source_prices)
        if extra_price_ids != expected_clone_ids:
            raise RuntimeError("replica contains unauthorized extra price versions")
        for clone_id in expected_clone_ids:
            clone = candidate_prices[clone_id]
            event = next(
                item
                for item in event_rows
                if int(item["result_price_version_id"]) == clone_id
            )
            source_row = source_prices[int(event["source_price_version_id"])]
            for column in source_columns:
                if column == "id":
                    continue
                if column == "legacy_route_price_id":
                    if clone[column] is not None:
                        raise RuntimeError(
                            f"authorized clone retained a legacy price id: {clone_id}"
                        )
                    continue
                if column == "remark":
                    if "Exact-route migration clone:" not in clone[column]:
                        raise RuntimeError(
                            f"authorized clone lacks lineage remark: {clone_id}"
                        )
                    continue
                if clone[column] != source_row[column]:
                    raise RuntimeError(
                        "authorized clone changed an unexpected source field: "
                        f"price={clone_id}, field={column}"
                    )

        changed_details = 0
        detail_columns = [
            row[1] for row in source.execute("PRAGMA table_info(payroll_detail_lines)")
        ]
        source_details = {
            int(row["id"]): dict(row)
            for row in source.execute("SELECT * FROM payroll_detail_lines ORDER BY id")
        }
        candidate_details = {
            int(row["id"]): dict(row)
            for row in candidate.execute("SELECT * FROM payroll_detail_lines ORDER BY id")
        }
        if set(source_details) != set(candidate_details):
            raise RuntimeError("authorized price migration changed payroll detail identities")
        for detail_id, source_row in source_details.items():
            expected = {column: source_row[column] for column in detail_columns}
            family = family_by_source.get(source_row.get("price_version_id"))
            if family:
                route_version_id = candidate_details[detail_id].get("route_version_id")
                result_price_id = family.get(route_version_id)
                if result_price_id is None:
                    raise RuntimeError(
                        f"authorized payroll detail route is not covered: {detail_id}"
                    )
                expected["price_version_id"] = result_price_id
            for column, value in expected.items():
                if candidate_details[detail_id][column] != value:
                    raise RuntimeError(
                        "authorized price migration changed an unexpected payroll detail "
                        f"field: detail={detail_id}, field={column}"
                    )
            if expected["price_version_id"] != source_row.get("price_version_id"):
                changed_details += 1

        changed_resolutions = 0
        if _table_exists(source, "payroll_work_price_resolutions"):
            resolution_columns = [
                row[1]
                for row in source.execute(
                    "PRAGMA table_info(payroll_work_price_resolutions)"
                )
            ]
            source_resolutions = {
                int(row["id"]): dict(row)
                for row in source.execute(
                    "SELECT * FROM payroll_work_price_resolutions ORDER BY id"
                )
            }
            candidate_resolutions = {
                int(row["id"]): dict(row)
                for row in candidate.execute(
                    "SELECT * FROM payroll_work_price_resolutions ORDER BY id"
                )
            }
            if set(source_resolutions) != set(candidate_resolutions):
                raise RuntimeError(
                    "authorized price migration changed price resolution identities"
                )
            for resolution_id, source_row in source_resolutions.items():
                expected = {
                    column: source_row[column] for column in resolution_columns
                }
                family = family_by_source.get(source_row.get("price_version_id"))
                if family:
                    route_version = candidate.execute(
                        "SELECT COALESCE(work.route_version_id,order_row.route_version_id) "
                        "FROM work_records work LEFT JOIN orders order_row "
                        "ON order_row.id=work.order_id WHERE work.id=?",
                        (source_row["work_record_id"],),
                    ).fetchone()
                    result_price_id = family.get(route_version[0] if route_version else None)
                    if result_price_id is None:
                        raise RuntimeError(
                            "authorized payroll resolution route is not covered: "
                            + str(resolution_id)
                        )
                    expected["price_version_id"] = result_price_id
                for column, value in expected.items():
                    if candidate_resolutions[resolution_id][column] != value:
                        raise RuntimeError(
                            "authorized price migration changed an unexpected price "
                            f"resolution field: resolution={resolution_id}, field={column}"
                        )
                if expected["price_version_id"] != source_row.get("price_version_id"):
                    changed_resolutions += 1

        authorized_tables = ["route_price_versions"]
        if changed_details:
            authorized_tables.append("payroll_detail_lines")
        if changed_resolutions:
            authorized_tables.append("payroll_work_price_resolutions")
        return {
            "status": "passed",
            "authorized_tables": authorized_tables,
            "authorized_price_ids": sorted(applicable),
            "clone_count": len(expected_clone_ids),
            "payroll_detail_rebind_count": changed_details,
            "price_resolution_rebind_count": changed_resolutions,
        }
    finally:
        candidate.close()
        source.close()


def compare_snapshots(
    source: dict, candidate: dict, *, authorized_protected_tables=()
) -> dict:
    authorized_protected_tables = set(authorized_protected_tables)
    comparison = {}
    for group in (*SNAPSHOT_GROUPS, "summary"):
        left = source[group]
        right = candidate[group]
        comparison[group] = {
            "source": left,
            "candidate": right,
            "equal": left == right,
        }
    differences = _flatten_differences(source, candidate)
    blocking = []
    for group, tables in SNAPSHOT_GROUPS.items():
        for table in tables:
            if table not in PROTECTED_TABLES:
                continue
            left = source[group][table]
            right = candidate[group][table]
            source_columns = left.get("column_sha256", {})
            candidate_columns = right.get("column_sha256", {})
            protected_equal = (
                left.get("exists") == right.get("exists")
                and left.get("count") == right.get("count")
                and all(
                    candidate_columns.get(column) == digest
                    for column, digest in source_columns.items()
                )
            )
            if not protected_equal and table not in authorized_protected_tables:
                blocking.append(
                    {
                        "group": group,
                        "table": table,
                        "source": left,
                        "candidate": right,
                        "rule": "all source columns and rows must remain unchanged",
                    }
                )
    candidate_checks = candidate["summary"]
    if candidate_checks["integrity_check"] != "ok" or candidate_checks["foreign_key_violations"]:
        blocking.append({"group": "summary", "database": candidate_checks})
    return {
        "comparison": comparison,
        "differences": differences,
        "blocking_differences": blocking,
    }


def validate_replica(source_path: str | Path, replica_path: str | Path) -> dict:
    source_path = Path(source_path).resolve()
    replica_path = Path(replica_path).resolve()
    preflight = run_preflight(source_path)
    if preflight["status"] != "passed":
        raise RuntimeError("source preflight is blocked; replica migration refused")
    source_snapshot = database_snapshot(source_path)
    online_backup(source_path, replica_path)
    source_after_backup = database_snapshot(source_path)
    source_stability = compare_snapshots(source_snapshot, source_after_backup)
    if source_stability["blocking_differences"]:
        raise RuntimeError("source database changed while the replica was being created")
    migration = migrate_database(
        replica_path, expected_preflight_sha256=preflight["summary_sha256"]
    )
    candidate_snapshot = database_snapshot(replica_path)
    authorized_price_resolution = _authorized_price_resolution_comparison(
        source_path, replica_path
    )
    result = compare_snapshots(
        source_snapshot,
        candidate_snapshot,
        authorized_protected_tables=authorized_price_resolution["authorized_tables"],
    )
    if result["blocking_differences"]:
        raise RuntimeError("replica migration changed protected business totals")
    return {
        "status": "passed",
        "source_database_sha256": database_sha256(source_path),
        "replica_database_sha256": database_sha256(replica_path),
        "preflight_summary_sha256": preflight["summary_sha256"],
        "source_stability": source_stability,
        "migration": migration,
        "authorized_price_resolution": authorized_price_resolution,
        **result,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def export_review_diff(
    source_path: str | Path, candidate_path: str | Path, output_dir: str | Path
) -> dict:
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    source_before = database_sha256(source_path)
    candidate_before = database_sha256(candidate_path)
    source = database_snapshot(source_path)
    candidate = database_snapshot(candidate_path)
    authorized_price_resolution = _authorized_price_resolution_comparison(
        source_path, candidate_path
    )
    compared = compare_snapshots(
        source,
        candidate,
        authorized_protected_tables=authorized_price_resolution["authorized_tables"],
    )
    document = {
        "status": "review_required" if compared["differences"] else "no_difference",
        "mode": "review_only",
        "automatic_repairs_applied": False,
        "source_database_sha256": source_before,
        "candidate_database_sha256": candidate_before,
        "authorized_price_resolution": authorized_price_resolution,
        **compared,
    }
    json_path = output / "process-v2-review-diff.json"
    csv_path = output / "process-v2-review-diff.csv"
    _write_json(json_path, document)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("path", "source", "candidate"))
        writer.writeheader()
        for difference in compared["differences"]:
            writer.writerow(
                {
                    "path": difference["path"],
                    "source": canonical_json(difference["source"]),
                    "candidate": canonical_json(difference["candidate"]),
                }
            )
    if database_sha256(source_path) != source_before or database_sha256(candidate_path) != candidate_before:
        raise RuntimeError("review diff must not modify either database")
    return {
        "status": document["status"],
        "json": {"path": str(json_path), "sha256": file_sha256(json_path)},
        "csv": {"path": str(csv_path), "sha256": file_sha256(csv_path)},
        "difference_count": len(compared["differences"]),
        "blocking_difference_count": len(compared["blocking_differences"]),
    }


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_values(path: Path) -> tuple[list[str], dict[str, str]]:
    if not path.is_file():
        raise RuntimeError(f"environment file does not exist: {path}")
    lines = path.read_text(encoding="utf-8").splitlines()
    values: dict[str, str] = {}
    seen: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key in PROCESS_FLAG_NAMES:
            if key in seen:
                raise RuntimeError(f"duplicate process versioning flag: {key}")
            seen.add(key)
            values[key] = value.strip().strip("\"'")
    return lines, values


def read_process_flags(path: str | Path) -> dict[str, bool]:
    _, values = _env_values(Path(path))
    return {flag: _parse_bool(values.get(flag, "false")) for flag in PROCESS_FLAG_NAMES}


def _validate_flag_prefix(flags: dict[str, bool]) -> int:
    enabled = 0
    disabled_seen = False
    for _, flag in PROCESS_FLAG_STAGES:
        value = bool(flags[flag])
        if disabled_seen and value:
            raise RuntimeError("process versioning flags are not a valid stage prefix")
        if value:
            enabled += 1
        else:
            disabled_seen = True
    return enabled


def _atomic_set_env_flag(path: Path, flag: str) -> None:
    lines, _ = _env_values(path)
    rendered = []
    replaced = False
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key == flag:
                rendered.append(f"{flag}=true")
                replaced = True
                continue
        rendered.append(line)
    if not replaced:
        if rendered and rendered[-1] != "":
            rendered.append("")
        rendered.append(f"{flag}=true")
    content = "\n".join(rendered) + "\n"
    mode = path.stat().st_mode & 0o777
    descriptor, temporary = tempfile.mkstemp(prefix=".env.process-v2.", dir=str(path.parent))
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def advance_cutover_stage(
    env_path: str | Path, stage: str, *, apply: bool = False
) -> dict:
    path = Path(env_path).resolve()
    stage_names = [name for name, _ in PROCESS_FLAG_STAGES]
    if stage not in stage_names:
        raise RuntimeError(f"unknown cutover stage: {stage}")
    before = read_process_flags(path)
    enabled_count = _validate_flag_prefix(before)
    requested_index = stage_names.index(stage)
    if requested_index < enabled_count:
        return {
            "stage": stage,
            "changed": False,
            "idempotent_replay": True,
            "before": before,
            "after": before,
        }
    next_stage = stage_names[enabled_count] if enabled_count < len(stage_names) else "complete"
    if requested_index != enabled_count:
        raise RuntimeError(f"next allowed stage is {next_stage}; requested {stage}")
    if not apply:
        return {
            "stage": stage,
            "changed": False,
            "dry_run": True,
            "next_allowed_stage": next_stage,
            "before": before,
            "after": before,
        }
    flag = PROCESS_FLAG_STAGES[requested_index][1]
    _atomic_set_env_flag(path, flag)
    after = read_process_flags(path)
    _validate_flag_prefix(after)
    if not after[flag]:
        raise RuntimeError(f"failed to enable process versioning flag: {flag}")
    return {
        "stage": stage,
        "flag": flag,
        "changed": True,
        "idempotent_replay": False,
        "before": before,
        "after": after,
    }


def validate_cutover_authorization(
    *,
    expected_commit: str,
    actual_commit: str,
    expected_database_sha256: str,
    actual_database_sha256: str,
    operator: str,
    idempotency_key: str,
) -> dict:
    if not operator or not operator.strip():
        raise RuntimeError("operator is required")
    if not idempotency_key or len(idempotency_key.strip()) < 8:
        raise RuntimeError("idempotency key must contain at least 8 characters")
    if not expected_commit or expected_commit.strip() != actual_commit.strip():
        raise RuntimeError("target commit does not match the deployed worktree")
    if not expected_database_sha256 or expected_database_sha256.lower() != actual_database_sha256.lower():
        raise RuntimeError("database SHA-256 does not match the authorized input")
    return {
        "authorized": True,
        "target_commit": actual_commit.strip(),
        "database_sha256": actual_database_sha256.lower(),
        "operator": operator.strip(),
        "idempotency_key": idempotency_key.strip(),
    }


def missing_version_bindings(db: sqlite3.Connection) -> dict[str, int]:
    checks = {
        "orders": ("orders", "route_id", "route_version_id"),
        "order_processes": ("order_processes", "process_id", "process_version_id"),
        "work_records": ("work_records", "process_id", "process_version_id"),
    }
    result = {}
    for key, (table, root, version) in checks.items():
        columns = _columns(db, table)
        if {root, version} <= columns:
            result[key] = int(
                _scalar(
                    db,
                    f'SELECT COUNT(*) FROM "{table}" '
                    f'WHERE "{root}" IS NOT NULL AND "{version}" IS NULL',
                )
            )
        else:
            result[key] = -1
    return result


def evaluate_post_cutover(
    *, database: dict, flags: dict, health: dict, api_results: dict, missing_bindings: dict
) -> dict:
    failures = []
    if database.get("user_version") != 63:
        failures.append("database user_version must be 63")
    if database.get("integrity_check") != "ok":
        failures.append("database integrity_check must be ok")
    if database.get("foreign_key_violations") != 0:
        failures.append("foreign key violations must be zero")
    for flag in PROCESS_FLAG_NAMES:
        if flags.get(flag) is not True:
            failures.append(f"flag is not enabled: {flag}")
    if health.get("status") != "ok" or health.get("db") != "connected":
        failures.append("health endpoint is not ok/connected")
    expected_api = {
        "permissions": "passed",
        "legacy_get": 200,
        "legacy_write": 409,
        "v2_query": 200,
        "historical_snapshot": "passed",
    }
    for key, expected in expected_api.items():
        if api_results.get(key) != expected:
            failures.append(f"API gate failed: {key}={api_results.get(key)!r}")
    for key, count in missing_bindings.items():
        if count != 0:
            failures.append(f"missing version bindings: {key}={count}")
    return {
        "status": "passed" if not failures else "failed",
        "blocking_failures": failures,
        "database": database,
        "flags": flags,
        "health": health,
        "api_results": api_results,
        "missing_bindings": missing_bindings,
    }


__all__ = [
    "PROCESS_FLAG_NAMES",
    "PROCESS_FLAG_STAGES",
    "advance_cutover_stage",
    "canonical_json",
    "collect_reference_coverage",
    "compare_snapshots",
    "database_checks",
    "database_sha256",
    "database_snapshot",
    "evaluate_post_cutover",
    "export_review_diff",
    "file_sha256",
    "migrate_database",
    "missing_version_bindings",
    "online_backup",
    "payload_sha256",
    "read_process_flags",
    "run_preflight",
    "validate_cutover_authorization",
    "validate_replica",
]
