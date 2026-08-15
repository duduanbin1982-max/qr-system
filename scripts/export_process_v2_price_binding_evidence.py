#!/usr/bin/env python3
"""Export read-only evidence for legacy prices missing from route V1.

The exporter simulates v060 and v061 in memory, correlates payroll lines with
the reconstructed order-route revisions, and optionally scans SQLite backups
for route topologies which no longer exist in the live database.  It never
modifies the source database or any backup.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from modules.migration_process_versioning import (  # noqa: E402
    m060_process_master_versioning,
    m061_bind_order_versions,
)
from scripts.process_v2_operations import (  # noqa: E402
    canonical_json,
    database_sha256,
    file_sha256,
)


def _open_read_only(path: Path) -> sqlite3.Connection:
    uri = "file:" + path.resolve().as_posix() + "?mode=ro"
    db = sqlite3.connect(uri, uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    db.execute("PRAGMA busy_timeout=10000")
    return db


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}


def _table_exists(db: sqlite3.Connection, table: str) -> bool:
    return (
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )


def _digest(route_id: int, nodes: list[dict]) -> str:
    normalized = {
        "route_id": int(route_id),
        "nodes": [
            {
                "process_id": int(node["process_id"]),
                "is_required": int(node.get("is_required", 1)),
                "required_audit": int(node.get("required_audit", 0)),
            }
            for node in nodes
        ],
    }
    return hashlib.sha256(canonical_json(normalized).encode("utf-8")).hexdigest()


def _legacy_route_nodes(db: sqlite3.Connection, route_id: int) -> list[dict]:
    columns = _columns(db, "process_route_items")
    if not {"id", "route_id", "process_id", "seq_order"} <= columns:
        return []
    required = "COALESCE(is_required,1)" if "is_required" in columns else "1"
    audit = "COALESCE(required_audit,0)" if "required_audit" in columns else "0"
    rows = db.execute(
        "SELECT id,process_id,seq_order,"
        + required
        + " AS is_required,"
        + audit
        + " AS required_audit FROM process_route_items "
        "WHERE route_id=? ORDER BY seq_order,id",
        (route_id,),
    ).fetchall()
    return [
        {
            "source_item_id": int(row["id"]),
            "source_seq_order": int(row["seq_order"] or 0),
            "dense_seq_order": index,
            "process_id": int(row["process_id"]),
            "is_required": int(row["is_required"]),
            "required_audit": int(row["required_audit"]),
        }
        for index, row in enumerate(rows, start=1)
    ]


def _simulated_route_versions(db: sqlite3.Connection, route_id: int) -> list[dict]:
    versions = []
    for row in db.execute(
        "SELECT id,version,status,idempotency_key FROM process_route_versions "
        "WHERE process_route_id=? ORDER BY version,id",
        (route_id,),
    ).fetchall():
        nodes = [
            {
                "dense_seq_order": int(item["seq_order"]),
                "process_id": int(item["process_id"]),
                "process_version_id": int(item["process_version_id"]),
                "is_required": int(item["is_required"]),
                "required_audit": int(item["required_audit"]),
            }
            for item in db.execute(
                "SELECT process_id,process_version_id,seq_order,is_required,required_audit "
                "FROM process_route_version_items WHERE route_version_id=? "
                "ORDER BY seq_order,id",
                (row["id"],),
            ).fetchall()
        ]
        orders = [
            int(item[0])
            for item in db.execute(
                "SELECT id FROM orders WHERE route_version_id=? ORDER BY id", (row["id"],)
            ).fetchall()
        ]
        event = db.execute(
            "SELECT payload_json FROM process_route_version_events "
            "WHERE version_id=? AND event_type='legacy_baseline_created' "
            "ORDER BY id LIMIT 1",
            (row["id"],),
        ).fetchone()
        payload = json.loads(event[0]) if event is not None else {}
        versions.append(
            {
                "route_version_id": int(row["id"]),
                "version": int(row["version"]),
                "status": row["status"],
                "idempotency_key": row["idempotency_key"],
                "topology_sha256": _digest(route_id, nodes),
                "nodes": nodes,
                "bound_order_ids": orders,
                "source_order_ids": payload.get("source_order_ids", []),
                "source_signature_sha256": payload.get("source_signature_sha256", ""),
            }
        )
    return versions


def _scan_backups(backup_dir: Path, route_ids: set[int]) -> tuple[list[dict], list[dict]]:
    grouped: dict[tuple[int, str], dict] = {}
    skipped = []
    for path in sorted(backup_dir.glob("*.db")):
        try:
            db = _open_read_only(path)
            try:
                if not _table_exists(db, "process_route_items"):
                    skipped.append({"backup": path.name, "reason": "missing_route_items"})
                    continue
                user_version = int(db.execute("PRAGMA user_version").fetchone()[0])
                for route_id in route_ids:
                    nodes = _legacy_route_nodes(db, route_id)
                    if not nodes:
                        continue
                    digest = _digest(route_id, nodes)
                    key = (route_id, digest)
                    stat = path.stat()
                    observed_at = datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat()
                    item = grouped.setdefault(
                        key,
                        {
                            "route_id": route_id,
                            "topology_sha256": digest,
                            "nodes": nodes,
                            "backup_count": 0,
                            "first_backup": path.name,
                            "first_observed_at": observed_at,
                            "last_backup": path.name,
                            "last_observed_at": observed_at,
                            "_first_mtime": stat.st_mtime,
                            "_last_mtime": stat.st_mtime,
                            "representative_backup": path.name,
                            "representative_backup_sha256": "",
                            "user_versions": set(),
                        },
                    )
                    item["backup_count"] += 1
                    if stat.st_mtime < item["_first_mtime"]:
                        item["_first_mtime"] = stat.st_mtime
                        item["first_backup"] = path.name
                        item["first_observed_at"] = observed_at
                        item["representative_backup"] = path.name
                    if stat.st_mtime > item["_last_mtime"]:
                        item["_last_mtime"] = stat.st_mtime
                        item["last_backup"] = path.name
                        item["last_observed_at"] = observed_at
                    item["user_versions"].add(user_version)
            finally:
                db.close()
        except (OSError, sqlite3.DatabaseError) as exc:
            skipped.append({"backup": path.name, "reason": str(exc)})

    topologies = []
    for item in grouped.values():
        representative = backup_dir / item["representative_backup"]
        item["representative_backup_sha256"] = file_sha256(representative)
        item["user_versions"] = sorted(item["user_versions"])
        item.pop("_first_mtime")
        item.pop("_last_mtime")
        topologies.append(item)
    topologies.sort(key=lambda item: (item["route_id"], item["first_backup"]))
    return topologies, skipped


def classify_price_binding(
    payroll_route_version_ids: list[int],
    order_candidates: list[dict],
    backup_candidates: list[dict],
) -> str:
    payroll_ids = sorted(set(payroll_route_version_ids))
    if len(payroll_ids) > 1:
        return "split_by_payroll_route_revision"
    if len(payroll_ids) == 1:
        return "bind_to_payroll_route_revision"
    if len(order_candidates) == 1:
        return "bind_to_order_route_revision"
    if len(order_candidates) > 1:
        return "manual_order_revision_choice"
    if len(backup_candidates) == 1:
        return "create_backup_route_revision_and_bind"
    if len(backup_candidates) > 1:
        return "manual_backup_topology_choice"
    return "manual_no_route_evidence"


def collect_evidence(source_path: Path, backup_dir: Path | None) -> dict:
    before_sha256 = database_sha256(source_path)
    source = _open_read_only(source_path)
    source_user_version = int(source.execute("PRAGMA user_version").fetchone()[0])
    simulation = sqlite3.connect(":memory:")
    simulation.row_factory = sqlite3.Row
    source.backup(simulation)
    simulation.execute("PRAGMA foreign_keys=ON")
    m060_process_master_versioning(simulation)
    m061_bind_order_versions(simulation)

    orphan_rows = simulation.execute(
        "SELECT price.*,route.name AS route_name,process.name AS process_name "
        "FROM route_price_versions price "
        "JOIN process_routes route ON route.id=price.route_id "
        "JOIN processes process ON process.id=price.process_id "
        "LEFT JOIN process_route_versions version "
        "ON version.process_route_id=price.route_id AND version.version=1 "
        "LEFT JOIN process_route_version_items item "
        "ON item.route_version_id=version.id AND item.process_id=price.process_id "
        "WHERE item.id IS NULL ORDER BY price.id"
    ).fetchall()
    route_ids = {int(row["route_id"]) for row in orphan_rows}
    backup_topologies, skipped_backups = (
        _scan_backups(backup_dir, route_ids)
        if backup_dir is not None
        else ([], [])
    )
    backup_by_route: dict[int, list[dict]] = {}
    for topology in backup_topologies:
        backup_by_route.setdefault(topology["route_id"], []).append(topology)

    prices = []
    for row in orphan_rows:
        price_id = int(row["id"])
        route_id = int(row["route_id"])
        process_id = int(row["process_id"])
        route_versions = _simulated_route_versions(simulation, route_id)
        candidates = [
            item
            for item in route_versions
            if any(node["process_id"] == process_id for node in item["nodes"])
        ]
        payroll_groups = [
            {
                "route_version_id": int(usage["route_version_id"]),
                "order_id": int(usage["order_id"]),
                "detail_count": int(usage["detail_count"]),
                "quantity": int(usage["quantity"]),
                "amount_cents": int(usage["amount_cents"]),
            }
            for usage in simulation.execute(
                "SELECT order_row.route_version_id,detail.order_id,COUNT(*) AS detail_count,"
                "COALESCE(SUM(detail.quantity),0) AS quantity,"
                "COALESCE(SUM(detail.amount_cents),0) AS amount_cents "
                "FROM payroll_detail_lines detail JOIN orders order_row "
                "ON order_row.id=detail.order_id WHERE detail.price_version_id=? "
                "GROUP BY order_row.route_version_id,detail.order_id "
                "ORDER BY order_row.route_version_id,detail.order_id",
                (price_id,),
            ).fetchall()
        ]
        payroll_route_version_ids = [
            item["route_version_id"] for item in payroll_groups
        ]
        backup_candidates = [
            item
            for item in backup_by_route.get(route_id, [])
            if any(node["process_id"] == process_id for node in item["nodes"])
        ]
        classification = classify_price_binding(
            payroll_route_version_ids, candidates, backup_candidates
        )
        prices.append(
            {
                "price_version_id": price_id,
                "legacy_route_price_id": row["legacy_route_price_id"],
                "route_id": route_id,
                "route_name": row["route_name"],
                "process_id": process_id,
                "process_name": row["process_name"],
                "status": row["status"],
                "normal_unit_price_micros": int(row["normal_unit_price_micros"]),
                "valid_from": row["valid_from"],
                "valid_to": row["valid_to"],
                "payroll": {
                    "detail_count": sum(item["detail_count"] for item in payroll_groups),
                    "quantity": sum(item["quantity"] for item in payroll_groups),
                    "amount_cents": sum(item["amount_cents"] for item in payroll_groups),
                    "groups": payroll_groups,
                },
                "simulated_order_route_candidates": candidates,
                "backup_route_candidates": backup_candidates,
                "classification": classification,
                "automatic": classification
                in {
                    "bind_to_payroll_route_revision",
                    "bind_to_order_route_revision",
                    "create_backup_route_revision_and_bind",
                },
            }
        )

    source.close()
    simulation.close()
    after_sha256 = database_sha256(source_path)
    if before_sha256 != after_sha256:
        raise RuntimeError("price binding evidence export changed the source database")
    summary = {
        "price_count": len(prices),
        "classification_counts": {
            classification: sum(
                item["classification"] == classification for item in prices
            )
            for classification in sorted({item["classification"] for item in prices})
        },
        "automatic_count": sum(item["automatic"] for item in prices),
        "manual_count": sum(not item["automatic"] for item in prices),
    }
    report = {
        "status": "review_required" if summary["manual_count"] else "passed",
        "mode": "read_only_price_binding_evidence",
        "source_database": {
            "path": str(source_path.resolve()),
            "user_version": source_user_version,
            "sha256": before_sha256,
            "unchanged": True,
        },
        "backup_scan": {
            "directory": str(backup_dir.resolve()) if backup_dir else "",
            "topology_count": len(backup_topologies),
            "skipped": skipped_backups,
        },
        "summary": summary,
        "prices": prices,
    }
    report["summary_sha256"] = hashlib.sha256(
        canonical_json(report).encode("utf-8")
    ).hexdigest()
    return report


def _write_csv(path: Path, report: dict) -> None:
    fields = (
        "price_version_id",
        "route_id",
        "route_name",
        "process_id",
        "process_name",
        "status",
        "normal_unit_price_micros",
        "payroll_detail_count",
        "payroll_quantity",
        "payroll_amount_cents",
        "payroll_order_ids",
        "candidate_route_versions",
        "backup_candidate_count",
        "classification",
        "automatic",
    )
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in report["prices"]:
            writer.writerow(
                {
                    "price_version_id": item["price_version_id"],
                    "route_id": item["route_id"],
                    "route_name": item["route_name"],
                    "process_id": item["process_id"],
                    "process_name": item["process_name"],
                    "status": item["status"],
                    "normal_unit_price_micros": item["normal_unit_price_micros"],
                    "payroll_detail_count": item["payroll"]["detail_count"],
                    "payroll_quantity": item["payroll"]["quantity"],
                    "payroll_amount_cents": item["payroll"]["amount_cents"],
                    "payroll_order_ids": ",".join(
                        str(row["order_id"]) for row in item["payroll"]["groups"]
                    ),
                    "candidate_route_versions": ",".join(
                        str(row["version"])
                        for row in item["simulated_order_route_candidates"]
                    ),
                    "backup_candidate_count": len(item["backup_route_candidates"]),
                    "classification": item["classification"],
                    "automatic": int(item["automatic"]),
                }
            )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export read-only evidence for historical process price bindings"
    )
    parser.add_argument("--db", required=True)
    parser.add_argument("--backup-dir")
    parser.add_argument("--output-dir", required=True)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    output = Path(args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = collect_evidence(
        Path(args.db), Path(args.backup_dir) if args.backup_dir else None
    )
    json_path = output / "process-v2-price-binding-evidence.json"
    csv_path = output / "process-v2-price-binding-evidence.csv"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_csv(csv_path, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "summary": report["summary"],
                "manual_decisions": [
                    {
                        "price_version_id": item["price_version_id"],
                        "route_id": item["route_id"],
                        "process_id": item["process_id"],
                        "classification": item["classification"],
                        "payroll_groups": item["payroll"]["groups"],
                        "order_candidates": [
                            {
                                "version": candidate["version"],
                                "route_version_id": candidate["route_version_id"],
                                "bound_order_ids": candidate["bound_order_ids"],
                                "topology_sha256": candidate["topology_sha256"],
                                "process_ids": [
                                    node["process_id"] for node in candidate["nodes"]
                                ],
                            }
                            for candidate in item["simulated_order_route_candidates"]
                        ],
                        "backup_candidates": [
                            {
                                "topology_sha256": candidate["topology_sha256"],
                                "backup_count": candidate["backup_count"],
                                "first_backup": candidate["first_backup"],
                                "last_backup": candidate["last_backup"],
                                "representative_backup_sha256": candidate[
                                    "representative_backup_sha256"
                                ],
                                "process_ids": [
                                    node["process_id"] for node in candidate["nodes"]
                                ],
                            }
                            for candidate in item["backup_route_candidates"]
                        ],
                    }
                    for item in report["prices"]
                    if not item["automatic"]
                ],
                "backup_revision_inputs": [
                    {
                        "price_version_id": item["price_version_id"],
                        "route_id": item["route_id"],
                        "process_id": item["process_id"],
                        "classification": item["classification"],
                        "candidates": item["backup_route_candidates"],
                    }
                    for item in report["prices"]
                    if item["backup_route_candidates"]
                    and not item["simulated_order_route_candidates"]
                ],
                "summary_sha256": report["summary_sha256"],
                "json": {"path": str(json_path), "sha256": file_sha256(json_path)},
                "csv": {"path": str(csv_path), "sha256": file_sha256(csv_path)},
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
