#!/usr/bin/env python3
"""Run isolated production-node shadow scheduling against a V091 replica.

The validator writes only to the supplied replica.  It records one immutable
shadow run per active order, verifies that formal scheduling facts are
unchanged, and emits a JSON report suitable for release evidence.
"""

from __future__ import annotations

import argparse
import collections
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

from modules.domain.production_node_scheduling import NodeSchedulingError
from modules.repositories.schedule_capacity_repository import (
    ScheduleCapacityRepository,
)
from modules.services.schedule_capacity_service import ScheduleCapacityService


FORMAL_TABLES = (
    "order_process_schedules",
    "order_process_schedule_segments",
    "production_node_schedule_allocations",
    "schedule_runs",
    "schedule_revisions",
    "schedule_revision_items",
)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Writable V091 replica")
    parser.add_argument("--report", required=True, help="JSON report path")
    parser.add_argument("--run-key-prefix", required=True)
    parser.add_argument("--actor-username", default="1000")
    parser.add_argument(
        "--start-date",
        help="Optional YYYY-MM-DD override; defaults to each order plan_start",
    )
    return parser.parse_args(argv)


def _table_counts(db):
    return {
        table: int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in FORMAL_TABLES
    }


def _active_orders(db):
    return db.execute(
        "SELECT id,order_no,status,plan_start,deadline,quantity "
        "FROM orders WHERE deleted_at IS NULL "
        "AND status IN ('pending','producing') ORDER BY id"
    ).fetchall()


def _formal_digests(db, orders):
    return {
        str(int(order["id"])): ScheduleCapacityRepository.formal_schedule_digest(
            int(order["id"]), db=db
        )
        for order in orders
    }


def _map_digest(values):
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _actor(db, username):
    actor = db.execute(
        "SELECT id,username,name FROM users WHERE username=? "
        "AND status='active' AND deleted_at IS NULL ORDER BY id LIMIT 1",
        (str(username),),
    ).fetchone()
    if actor is None:
        raise RuntimeError(f"active actor not found: {username}")
    return actor


def _scoped_shadow_metrics(db, run_ids):
    if not run_ids:
        return {
            "run_count": 0,
            "item_count": 0,
            "segment_count": 0,
            "allocation_count": 0,
            "exclusive_cross_run_conflict_count": 0,
            "quantity_conservation_violation_count": 0,
            "conflicts_by_node": [],
            "quantity_conservation_violations": [],
        }
    placeholders = ",".join("?" for _ in run_ids)
    params = tuple(run_ids)
    table_counts = {}
    for label, table, column in (
        ("run_count", "production_node_shadow_runs", "id"),
        ("item_count", "production_node_shadow_items", "shadow_run_id"),
    ):
        table_counts[label] = int(
            db.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {column} IN ({placeholders})",
                params,
            ).fetchone()[0]
        )
    for label, table in (
        ("segment_count", "production_node_shadow_segments"),
        ("allocation_count", "production_node_shadow_allocations"),
    ):
        table_counts[label] = int(
            db.execute(
                f"SELECT COUNT(*) FROM {table} fact "
                "JOIN production_node_shadow_items item "
                "ON item.id=fact.shadow_item_id "
                f"WHERE item.shadow_run_id IN ({placeholders})",
                params,
            ).fetchone()[0]
        )
    conflict_params = params + params
    conflict_count = int(
        db.execute(
            "SELECT COUNT(*) FROM production_node_shadow_segments a "
            "JOIN production_node_shadow_items ai ON ai.id=a.shadow_item_id "
            "JOIN production_node_shadow_segments b ON a.id<b.id "
            "AND a.production_node_id=b.production_node_id "
            "AND a.segment_start_at<b.segment_end_at "
            "AND b.segment_start_at<a.segment_end_at "
            "JOIN production_node_shadow_items bi ON bi.id=b.shadow_item_id "
            "JOIN production_nodes n ON n.id=a.production_node_id "
            "WHERE n.capacity_mode='exclusive' "
            "AND ai.shadow_run_id<>bi.shadow_run_id "
            f"AND ai.shadow_run_id IN ({placeholders}) "
            f"AND bi.shadow_run_id IN ({placeholders})",
            conflict_params,
        ).fetchone()[0]
    )
    quantity_violations = int(
        db.execute(
            "SELECT COUNT(*) FROM ("
            "SELECT item.id,item.quantity,COALESCE(SUM(allocation.quantity),0) "
            "AS allocated FROM production_node_shadow_items item "
            "LEFT JOIN production_node_shadow_allocations allocation "
            "ON allocation.shadow_item_id=item.id "
            "WHERE item.status='planned' "
            "AND COALESCE(json_extract(item.payload_json,'$.execution_mode'),"
            "'internal') NOT IN ('outsourced','non_scheduled') "
            f"AND item.shadow_run_id IN ({placeholders}) "
            "GROUP BY item.id,item.quantity HAVING allocated<>item.quantity)",
            params,
        ).fetchone()[0]
    )
    conflict_rows = [
        dict(row)
        for row in db.execute(
            "SELECT n.id AS production_node_id,n.node_code,n.node_name,"
            "process.name AS process_name,COUNT(*) AS conflict_count,"
            "COUNT(DISTINCT ai.shadow_run_id) AS affected_run_count "
            "FROM production_node_shadow_segments a "
            "JOIN production_node_shadow_items ai ON ai.id=a.shadow_item_id "
            "JOIN production_node_shadow_segments b ON a.id<b.id "
            "AND a.production_node_id=b.production_node_id "
            "AND a.segment_start_at<b.segment_end_at "
            "AND b.segment_start_at<a.segment_end_at "
            "JOIN production_node_shadow_items bi ON bi.id=b.shadow_item_id "
            "JOIN production_nodes n ON n.id=a.production_node_id "
            "JOIN processes process ON process.id=n.process_id "
            "WHERE n.capacity_mode='exclusive' "
            "AND ai.shadow_run_id<>bi.shadow_run_id "
            f"AND ai.shadow_run_id IN ({placeholders}) "
            f"AND bi.shadow_run_id IN ({placeholders}) "
            "GROUP BY n.id,n.node_code,n.node_name,process.name "
            "ORDER BY conflict_count DESC,n.id",
            conflict_params,
        ).fetchall()
    ]
    quantity_rows = [
        dict(row)
        for row in db.execute(
            "SELECT run.order_id,orders.order_no,item.id AS shadow_item_id,"
            "item.order_process_id,item.process_id,process.name AS process_name,"
            "item.quantity,COALESCE(SUM(allocation.quantity),0) AS allocated_quantity,"
            "COUNT(allocation.id) AS allocation_count "
            "FROM production_node_shadow_items item "
            "JOIN production_node_shadow_runs run ON run.id=item.shadow_run_id "
            "JOIN orders ON orders.id=run.order_id "
            "JOIN processes process ON process.id=item.process_id "
            "LEFT JOIN production_node_shadow_allocations allocation "
            "ON allocation.shadow_item_id=item.id "
            "WHERE item.status='planned' "
            "AND COALESCE(json_extract(item.payload_json,'$.execution_mode'),"
            "'internal') NOT IN ('outsourced','non_scheduled') "
            f"AND item.shadow_run_id IN ({placeholders}) "
            "GROUP BY run.order_id,orders.order_no,item.id,item.order_process_id,"
            "item.process_id,process.name,item.quantity "
            "HAVING allocated_quantity<>item.quantity "
            "ORDER BY run.order_id,item.id",
            params,
        ).fetchall()
    ]
    return {
        **table_counts,
        "exclusive_cross_run_conflict_count": conflict_count,
        "quantity_conservation_violation_count": quantity_violations,
        "conflicts_by_node": conflict_rows,
        "quantity_conservation_violations": quantity_rows,
    }


def run(args):
    db_path = Path(args.db).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve()
    if not db_path.is_file():
        raise RuntimeError(f"replica does not exist: {db_path}")
    if len(args.run_key_prefix.strip()) < 8:
        raise RuntimeError("run-key-prefix must contain at least 8 characters")

    db = sqlite3.connect(str(db_path), timeout=60)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=60000")
    try:
        version = int(db.execute("PRAGMA user_version").fetchone()[0])
        if version != 91:
            raise RuntimeError(f"V091 replica required; observed V{version}")
        actor = _actor(db, args.actor_username)
        orders = _active_orders(db)
        before_counts = _table_counts(db)
        before_digests = _formal_digests(db, orders)
        results = []
        run_ids = []
        blocked_codes = collections.Counter()
        exception_codes = collections.Counter()

        for index, order in enumerate(orders, start=1):
            order_id = int(order["id"])
            entry = {
                "order_id": order_id,
                "order_no": order["order_no"] or "",
                "order_status": order["status"] or "",
                "plan_start": order["plan_start"] or "",
                "deadline": order["deadline"] or "",
            }
            try:
                result = ScheduleCapacityService.generate_shadow_order_schedule(
                    order_id,
                    f"{args.run_key_prefix}-order-{order_id}",
                    start_date=args.start_date,
                    actor_id=int(actor["id"]),
                    db=db,
                )
                run_ids.append(int(result["shadow_run_id"]))
                operations = result.get("operations") or []
                blocked = [
                    operation
                    for operation in operations
                    if operation.get("status") == "blocked"
                ]
                planned = [
                    operation
                    for operation in operations
                    if operation.get("status") == "planned"
                ]
                completed = [
                    operation
                    for operation in operations
                    if operation.get("status") == "completed"
                ]
                for operation in blocked:
                    blocked_codes[
                        operation.get("blocked_code") or "UNSPECIFIED"
                    ] += 1
                entry.update(
                    {
                        "result": "blocked" if blocked else "success",
                        "shadow_run_id": result["shadow_run_id"],
                        "operation_count": len(operations),
                        "planned_operation_count": len(planned),
                        "blocked_operation_count": len(blocked),
                        "completed_operation_count": len(completed),
                        "blocked": [
                            {
                                "order_process_id": operation.get(
                                    "order_process_id"
                                ),
                                "process_id": operation.get("process_id"),
                                "process_name": operation.get("process_name")
                                or operation.get("process_name_snapshot")
                                or "",
                                "blocked_code": operation.get("blocked_code")
                                or "",
                                "blocked_reason": operation.get("blocked_reason")
                                or operation.get("reason")
                                or "",
                            }
                            for operation in blocked
                        ],
                    }
                )
            except NodeSchedulingError as exc:
                exception_codes[exc.code] += 1
                entry.update(
                    {
                        "result": "failed",
                        "error_code": exc.code,
                        "error": exc.message,
                        "details": exc.details,
                    }
                )
            except Exception as exc:  # release evidence must retain each failure
                code = type(exc).__name__
                exception_codes[code] += 1
                entry.update(
                    {"result": "failed", "error_code": code, "error": str(exc)}
                )
            results.append(entry)
            if index % 10 == 0 or index == len(orders):
                print(f"processed={index}/{len(orders)}", file=sys.stderr)

        after_counts = _table_counts(db)
        after_digests = _formal_digests(db, orders)
        changed_order_ids = [
            int(order_id)
            for order_id, before in before_digests.items()
            if before != after_digests[order_id]
        ]
        shadow = _scoped_shadow_metrics(db, sorted(set(run_ids)))
        quick_check = db.execute("PRAGMA quick_check").fetchone()[0]
        foreign_key_violations = len(
            db.execute("PRAGMA foreign_key_check").fetchall()
        )
        result_counts = collections.Counter(row["result"] for row in results)
        formal_unchanged = before_counts == after_counts and not changed_order_ids
        acceptance = {
            "database_integrity_ok": quick_check == "ok",
            "foreign_keys_ok": foreign_key_violations == 0,
            "formal_schedule_unchanged": formal_unchanged,
            "quantity_conservation_ok": (
                shadow["quantity_conservation_violation_count"] == 0
            ),
            # Each run is an independent what-if scenario.  Cross-run overlap
            # is diagnostic only; the batch-replica validator verifies the
            # capacity-sharing global queue.
            "independent_shadow_runs_created": (
                shadow["run_count"] == len(orders)
            ),
            "unexpected_failures_zero": result_counts.get("failed", 0) == 0,
        }
        report = {
            "schema": "qr-system-v091-replica-shadow-replay/v1",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "ok": all(acceptance.values()),
            "database": {
                "path": str(db_path),
                "user_version": version,
                "quick_check": quick_check,
                "foreign_key_violations": foreign_key_violations,
            },
            "actor": {
                "id": int(actor["id"]),
                "username": actor["username"] or "",
                "name": actor["name"] or "",
            },
            "active_order_count": len(orders),
            "result_counts": dict(result_counts),
            "blocked_operation_codes": dict(blocked_codes),
            "exception_codes": dict(exception_codes),
            "formal_schedule": {
                "before_counts": before_counts,
                "after_counts": after_counts,
                "before_digest": _map_digest(before_digests),
                "after_digest": _map_digest(after_digests),
                "changed_order_ids": changed_order_ids,
                "unchanged": formal_unchanged,
            },
            "shadow": shadow,
            "acceptance": acceptance,
            "orders": results,
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return report
    finally:
        db.close()


def main(argv=None):
    args = _parse_args(argv)
    try:
        report = run(args)
        print(
            json.dumps(
                {
                    key: report[key]
                    for key in (
                        "ok",
                        "active_order_count",
                        "result_counts",
                        "blocked_operation_codes",
                        "exception_codes",
                        "formal_schedule",
                        "shadow",
                        "acceptance",
                    )
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if report["ok"] else 2
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
