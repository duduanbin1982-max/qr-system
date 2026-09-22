#!/usr/bin/env python3
"""Run a priority-ordered, capacity-sharing automatic plan on a V091 replica.

Unlike independent per-order shadow runs, this disposable-replica simulation
keeps each earlier candidate schedule visible while planning later orders.  It
therefore verifies the global queue for node conflicts and quantity loss
without touching the production database.
"""

from __future__ import annotations

import argparse
import collections
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from modules.repositories.schedule_capacity_repository import (
    ScheduleCapacityRepository,
)
from modules.migration_production_nodes import APPROVED_PRODUCTION_NODE_COUNTS
import modules.services.schedule_capacity_service as schedule_service_module
from modules.services.schedule_capacity_service import ScheduleCapacityService


FOCUS_MULTI_NODE_COUNTS = {
    name: APPROVED_PRODUCTION_NODE_COUNTS[name]
    for name in ("铆接", "焊接", "镗孔", "喷漆")
}


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Disposable writable V091 replica")
    parser.add_argument("--report", required=True)
    parser.add_argument("--auto-plan-key", required=True)
    parser.add_argument("--actor-username", default="1000")
    parser.add_argument("--start-date", required=True)
    parser.add_argument(
        "--planning-now",
        required=True,
        help="Deterministic local timestamp, for example 2026-09-21T12:00:00",
    )
    return parser.parse_args(argv)


def _digest_rows(db, sql, params=()):
    rows = [tuple(row) for row in db.execute(sql, params).fetchall()]
    encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _execution_fingerprint(db):
    return {
        "order_process_progress": _digest_rows(
            db,
            "SELECT id,order_id,completed,scrapped,rework,status "
            "FROM order_processes ORDER BY id",
        ),
        "work_records": _digest_rows(
            db,
            "SELECT id,order_id,process_id,user_id,type,status,quantity "
            "FROM work_records ORDER BY id",
        ),
    }


def _actor(db, username):
    actor = db.execute(
        "SELECT id,username,name FROM users WHERE username=? "
        "AND status='active' AND deleted_at IS NULL ORDER BY id LIMIT 1",
        (str(username),),
    ).fetchone()
    if actor is None:
        raise RuntimeError(f"active actor not found: {username}")
    return actor


def _conflict_metrics(db, prefix):
    like = f"{prefix}:%"
    internal = int(
        db.execute(
            "SELECT COUNT(*) FROM order_process_schedule_segments a "
            "JOIN order_process_schedules sa ON sa.id=a.schedule_id "
            "JOIN order_process_schedule_segments b ON a.id<b.id "
            "AND a.production_node_id=b.production_node_id "
            "AND a.segment_start_at<b.segment_end_at "
            "AND b.segment_start_at<a.segment_end_at "
            "JOIN order_process_schedules sb ON sb.id=b.schedule_id "
            "JOIN production_nodes node ON node.id=a.production_node_id "
            "WHERE node.capacity_mode='exclusive' "
            "AND sa.schedule_run_key LIKE ? AND sb.schedule_run_key LIKE ?",
            (like, like),
        ).fetchone()[0]
    )
    existing = int(
        db.execute(
            "SELECT COUNT(*) FROM order_process_schedule_segments a "
            "JOIN order_process_schedules sa ON sa.id=a.schedule_id "
            "JOIN order_process_schedule_segments b ON a.id<b.id "
            "AND a.production_node_id=b.production_node_id "
            "AND a.segment_start_at<b.segment_end_at "
            "AND b.segment_start_at<a.segment_end_at "
            "JOIN order_process_schedules sb ON sb.id=b.schedule_id "
            "JOIN production_nodes node ON node.id=a.production_node_id "
            "WHERE node.capacity_mode='exclusive' AND ("
            "(sa.schedule_run_key LIKE ? AND sb.schedule_run_key NOT LIKE ?) OR "
            "(sb.schedule_run_key LIKE ? AND sa.schedule_run_key NOT LIKE ?))",
            (like, like, like, like),
        ).fetchone()[0]
    )
    by_node = [
        dict(row)
        for row in db.execute(
            "SELECT node.id AS production_node_id,node.node_code,node.node_name,"
            "process.name AS process_name,COUNT(*) AS conflict_count "
            "FROM order_process_schedule_segments a "
            "JOIN order_process_schedules sa ON sa.id=a.schedule_id "
            "JOIN order_process_schedule_segments b ON a.id<b.id "
            "AND a.production_node_id=b.production_node_id "
            "AND a.segment_start_at<b.segment_end_at "
            "AND b.segment_start_at<a.segment_end_at "
            "JOIN order_process_schedules sb ON sb.id=b.schedule_id "
            "JOIN production_nodes node ON node.id=a.production_node_id "
            "JOIN processes process ON process.id=node.process_id "
            "WHERE node.capacity_mode='exclusive' "
            "AND sa.schedule_run_key LIKE ? AND sb.schedule_run_key LIKE ? "
            "GROUP BY node.id,node.node_code,node.node_name,process.name "
            "ORDER BY conflict_count DESC,node.id",
            (like, like),
        ).fetchall()
    ]
    return {
        "batch_internal_conflict_count": internal,
        "batch_to_existing_conflict_count": existing,
        "conflicts_by_node": by_node,
    }


def _node_capacity_metrics(db, prefix):
    like = f"{prefix}:%"
    configured = db.execute(
        "SELECT process.name AS process_name,node.id AS production_node_id,"
        "node.node_code,node.node_name,node.capacity_mode "
        "FROM production_nodes node "
        "JOIN processes process ON process.id=node.process_id "
        "WHERE node.status='active' ORDER BY process.name,node.id"
    ).fetchall()
    allocation_rows = db.execute(
        "SELECT process.name AS process_name,node.id AS production_node_id,"
        "COUNT(allocation.id) AS allocation_count,"
        "COUNT(DISTINCT schedule.id) AS operation_count,"
        "COALESCE(SUM(allocation.quantity),0) AS allocated_quantity "
        "FROM production_node_schedule_allocations allocation "
        "JOIN order_process_schedules schedule ON schedule.id=allocation.schedule_id "
        "JOIN production_nodes node ON node.id=allocation.production_node_id "
        "JOIN processes process ON process.id=node.process_id "
        "WHERE schedule.schedule_run_key LIKE ? "
        "GROUP BY process.name,node.id ORDER BY process.name,node.id",
        (like,),
    ).fetchall()
    segment_rows = db.execute(
        "SELECT process.name AS process_name,node.id AS production_node_id,"
        "COUNT(segment.id) AS segment_count,"
        "COALESCE(SUM(segment.occupied_minutes),0) AS occupied_minutes "
        "FROM order_process_schedule_segments segment "
        "JOIN order_process_schedules schedule ON schedule.id=segment.schedule_id "
        "JOIN production_nodes node ON node.id=segment.production_node_id "
        "JOIN processes process ON process.id=node.process_id "
        "WHERE schedule.schedule_run_key LIKE ? "
        "GROUP BY process.name,node.id ORDER BY process.name,node.id",
        (like,),
    ).fetchall()
    split_rows = db.execute(
        "SELECT process_name,COUNT(*) AS operation_count FROM ("
        "SELECT process.name AS process_name,schedule.id "
        "FROM production_node_schedule_allocations allocation "
        "JOIN order_process_schedules schedule ON schedule.id=allocation.schedule_id "
        "JOIN processes process ON process.id=schedule.process_id "
        "WHERE schedule.schedule_run_key LIKE ? "
        "GROUP BY process.name,schedule.id "
        "HAVING COUNT(DISTINCT allocation.production_node_id)>1"
        ") split GROUP BY process_name ORDER BY process_name",
        (like,),
    ).fetchall()

    allocation_by_node = {
        int(row["production_node_id"]): dict(row) for row in allocation_rows
    }
    segment_by_node = {
        int(row["production_node_id"]): dict(row) for row in segment_rows
    }
    split_by_process = {
        row["process_name"]: int(row["operation_count"] or 0)
        for row in split_rows
    }
    processes = {}
    for process_name, expected_count in FOCUS_MULTI_NODE_COUNTS.items():
        nodes = []
        for row in configured:
            if row["process_name"] != process_name:
                continue
            node_id = int(row["production_node_id"])
            allocation = allocation_by_node.get(node_id, {})
            segment = segment_by_node.get(node_id, {})
            nodes.append(
                {
                    "production_node_id": node_id,
                    "node_code": row["node_code"] or "",
                    "node_name": row["node_name"] or "",
                    "capacity_mode": row["capacity_mode"] or "",
                    "operation_count": int(allocation.get("operation_count") or 0),
                    "allocation_count": int(allocation.get("allocation_count") or 0),
                    "allocated_quantity": int(allocation.get("allocated_quantity") or 0),
                    "segment_count": int(segment.get("segment_count") or 0),
                    "occupied_minutes": float(segment.get("occupied_minutes") or 0),
                }
            )
        used_nodes = [node for node in nodes if node["allocation_count"] > 0]
        processes[process_name] = {
            "expected_active_node_count": expected_count,
            "actual_active_node_count": len(nodes),
            "used_node_count": len(used_nodes),
            "multi_node_operation_count": split_by_process.get(process_name, 0),
            "allocated_quantity": sum(node["allocated_quantity"] for node in nodes),
            "occupied_minutes": sum(node["occupied_minutes"] for node in nodes),
            "configured_count_ok": len(nodes) == expected_count,
            "all_configured_nodes_exercised": len(used_nodes) == expected_count,
            "multi_node_split_exercised": split_by_process.get(process_name, 0) > 0,
            "nodes": nodes,
        }
    return {
        "focus_processes": processes,
        "configured_counts_ok": all(
            row["configured_count_ok"] for row in processes.values()
        ),
        "all_configured_nodes_exercised": all(
            row["all_configured_nodes_exercised"] for row in processes.values()
        ),
        "multi_node_splits_exercised": all(
            row["multi_node_split_exercised"] for row in processes.values()
        ),
    }


def _calendar_metrics(results):
    planned_internal = []
    for order in results:
        for operation in order.get("operations") or []:
            if operation.get("status") != "planned":
                continue
            if operation.get("execution_mode", "internal") in {
                "outsourced",
                "non_scheduled",
            }:
                continue
            planned_internal.append(operation)

    cross_shift = 0
    cross_day = 0
    weekend_spanning = 0
    weekend_segments = []
    invalid_segments = []
    segment_count = 0
    for operation in planned_internal:
        segments = operation.get("segments") or []
        segment_count += len(segments)
        node_slots = collections.defaultdict(set)
        for segment in segments:
            try:
                start = datetime.fromisoformat(str(segment["start_at"]).replace("T", " "))
                end = datetime.fromisoformat(str(segment["end_at"]).replace("T", " "))
            except (KeyError, TypeError, ValueError):
                invalid_segments.append(
                    {
                        "order_process_id": operation.get("order_process_id"),
                        "reason": "invalid timestamp",
                    }
                )
                continue
            if end <= start or start.date() != end.date():
                invalid_segments.append(
                    {
                        "order_process_id": operation.get("order_process_id"),
                        "start_at": segment.get("start_at"),
                        "end_at": segment.get("end_at"),
                        "reason": "segment must stay within one positive calendar slot",
                    }
                )
            node_slots[int(segment["production_node_id"])].add(
                (start.date().isoformat(), segment.get("shift_id"))
            )
            if start.weekday() >= 5 or end.weekday() >= 5:
                weekend_segments.append(
                    {
                        "order_process_id": operation.get("order_process_id"),
                        "production_node_id": segment.get("production_node_id"),
                        "start_at": segment.get("start_at"),
                        "end_at": segment.get("end_at"),
                    }
                )
        if any(len(slots) > 1 for slots in node_slots.values()):
            cross_shift += 1

        start = datetime.fromisoformat(
            str(operation["planned_start_at"]).replace("T", " ")
        )
        end = datetime.fromisoformat(
            str(operation["planned_end_at"]).replace("T", " ")
        )
        if start.date() != end.date():
            cross_day += 1
        cursor = start.date()
        while cursor <= end.date():
            if cursor.weekday() >= 5:
                weekend_spanning += 1
                break
            cursor += timedelta(days=1)
    return {
        "planned_internal_operation_count": len(planned_internal),
        "segment_count": segment_count,
        "cross_shift_operation_count": cross_shift,
        "cross_day_operation_count": cross_day,
        "weekend_spanning_operation_count": weekend_spanning,
        "weekend_segment_count": len(weekend_segments),
        "weekend_segments": weekend_segments,
        "invalid_segment_count": len(invalid_segments),
        "invalid_segments": invalid_segments,
    }


def _external_capacity_metrics(results):
    external = []
    violations = []
    for order in results:
        for operation in order.get("operations") or []:
            if operation.get("execution_mode") not in {
                "outsourced",
                "non_scheduled",
            }:
                continue
            row = {
                "order_id": order.get("order_id"),
                "order_no": order.get("order_no") or "",
                "order_process_id": operation.get("order_process_id"),
                "process_name": operation.get("process_name")
                or operation.get("process_name_snapshot")
                or "",
                "execution_mode": operation.get("execution_mode"),
                "quantity": int(operation.get("quantity") or 0),
                "occupied_minutes": float(operation.get("occupied_minutes") or 0),
                "production_node_id": operation.get("production_node_id"),
                "process_line_id": operation.get("process_line_id"),
                "segment_count": len(operation.get("segments") or []),
                "allocation_count": len(operation.get("allocations") or []),
            }
            external.append(row)
            if (
                row["occupied_minutes"] != 0
                or row["production_node_id"] is not None
                or row["process_line_id"] is not None
                or row["segment_count"] != 0
                or row["allocation_count"] != 0
            ):
                violations.append(row)
    return {
        "external_operation_count": len(external),
        "capacity_violation_count": len(violations),
        "operations": external,
        "violations": violations,
    }


def _operation_metrics(results):
    order_counts = collections.Counter()
    blocked_codes = collections.Counter()
    quantity_violations = []
    serial_nodes = {}
    operation_count = 0
    planned_internal_count = 0
    for order in results:
        operations = order.get("operations") or []
        operation_count += len(operations)
        blocked = [op for op in operations if op.get("status") == "blocked"]
        if order.get("status") == "failed" or not order.get("ok", False):
            order_counts["failed"] += 1
        elif blocked:
            order_counts["blocked"] += 1
        else:
            order_counts["success"] += 1
        for operation in blocked:
            blocked_codes[operation.get("blocked_code") or "UNSPECIFIED"] += 1
        for operation in operations:
            if operation.get("status") != "planned":
                continue
            if operation.get("execution_mode", "internal") in {
                "outsourced",
                "non_scheduled",
            }:
                continue
            planned_internal_count += 1
            allocations = operation.get("allocations") or []
            allocated = sum(int(row.get("quantity") or 0) for row in allocations)
            expected = int(operation.get("quantity") or 0)
            if allocated != expected:
                quantity_violations.append(
                    {
                        "order_id": order.get("order_id"),
                        "order_no": order.get("order_no") or "",
                        "order_process_id": operation.get("order_process_id"),
                        "process_id": operation.get("process_id"),
                        "process_name": operation.get("process_name")
                        or operation.get("process_name_snapshot")
                        or "",
                        "expected_quantity": expected,
                        "allocated_quantity": allocated,
                    }
                )
            for allocation in allocations:
                serial_id = str(allocation.get("serial_id") or "").strip()
                if serial_id:
                    key = (operation.get("order_process_id"), serial_id)
                    serial_nodes.setdefault(key, set()).add(
                        int(allocation["production_node_id"])
                    )
    serial_splits = [
        {"order_process_id": key[0], "serial_id": key[1]}
        for key, nodes in serial_nodes.items()
        if len(nodes) > 1
    ]
    return {
        "order_result_counts": dict(order_counts),
        "operation_count": operation_count,
        "planned_internal_operation_count": planned_internal_count,
        "blocked_operation_codes": dict(blocked_codes),
        "quantity_conservation_violation_count": len(quantity_violations),
        "quantity_conservation_violations": quantity_violations,
        "serial_split_violation_count": len(serial_splits),
        "serial_split_violations": serial_splits,
    }


def _deadline_metrics(queue, results):
    deadlines = {
        int(order["id"]): str(order.get("deadline") or "").strip()
        for order in queue
    }
    late_orders = []
    latest_end = None
    for order in results:
        ends = []
        for operation in order.get("operations") or []:
            value = operation.get("planned_end_at")
            if not value:
                continue
            try:
                ends.append(datetime.fromisoformat(str(value).replace("T", " ")))
            except ValueError:
                continue
        if not ends:
            continue
        planned_end = max(ends)
        if latest_end is None or planned_end > latest_end:
            latest_end = planned_end
        deadline = deadlines.get(int(order["order_id"]), "")
        if not deadline:
            continue
        due = datetime.strptime(deadline + " 23:59:59", "%Y-%m-%d %H:%M:%S")
        if planned_end <= due:
            continue
        late_orders.append(
            {
                "order_id": int(order["order_id"]),
                "order_no": order.get("order_no") or "",
                "deadline": deadline,
                "planned_end_at": planned_end.isoformat(sep=" "),
                "late_minutes": int((planned_end - due).total_seconds() // 60),
            }
        )
    late_orders.sort(key=lambda row: (-row["late_minutes"], row["order_id"]))
    return {
        "max_planned_end_at": latest_end.isoformat(sep=" ") if latest_end else "",
        "late_order_count": len(late_orders),
        "maximum_late_minutes": max(
            (row["late_minutes"] for row in late_orders), default=0
        ),
        "late_orders": late_orders,
    }


def run(args):
    db_path = Path(args.db).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve()
    planning_now = datetime.fromisoformat(args.planning_now)
    if not db_path.is_file():
        raise RuntimeError(f"replica does not exist: {db_path}")

    db = sqlite3.connect(str(db_path), timeout=60)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=60000")
    try:
        version = int(db.execute("PRAGMA user_version").fetchone()[0])
        if version != 91:
            raise RuntimeError(f"V091 replica required; observed V{version}")
        actor = _actor(db, args.actor_username)
        queue_before = ScheduleCapacityRepository.list_schedulable_orders(
            1000, db=db, now=planning_now
        )
        execution_before = _execution_fingerprint(db)

        real_datetime = schedule_service_module.datetime

        class FixedDateTime(real_datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return cls.fromtimestamp(planning_now.timestamp())
                return cls.fromtimestamp(planning_now.timestamp(), tz)

        schedule_service_module.datetime = FixedDateTime
        real_node_engine_enabled = schedule_service_module.config.PRODUCTION_NODE_ENGINE_ENABLED
        # This validator exists specifically to exercise the production-node
        # engine on a disposable replica.  Do not inherit the workstation or
        # production feature-flag state, otherwise a disabled flag silently
        # exercises the Legacy line planner and produces no node allocations.
        schedule_service_module.config.PRODUCTION_NODE_ENGINE_ENABLED = True
        try:
            result = ScheduleCapacityService.auto_plan_orders(
                start_date=args.start_date,
                auto_plan_key=args.auto_plan_key,
                limit=1000,
                actor_id=int(actor["id"]),
                db=db,
            )
        finally:
            schedule_service_module.config.PRODUCTION_NODE_ENGINE_ENABLED = (
                real_node_engine_enabled
            )
            schedule_service_module.datetime = real_datetime

        execution_after = _execution_fingerprint(db)
        order_results = result.get("orders") or []
        operation_metrics = _operation_metrics(order_results)
        conflict_metrics = _conflict_metrics(db, args.auto_plan_key)
        node_capacity_metrics = _node_capacity_metrics(db, args.auto_plan_key)
        calendar_metrics = _calendar_metrics(order_results)
        external_capacity_metrics = _external_capacity_metrics(order_results)
        deadline_metrics = _deadline_metrics(
            queue_before, order_results
        )
        quick_check = db.execute("PRAGMA quick_check").fetchone()[0]
        foreign_key_violations = len(
            db.execute("PRAGMA foreign_key_check").fetchall()
        )
        active_count = int(
            db.execute(
                "SELECT COUNT(*) FROM orders WHERE deleted_at IS NULL "
                "AND status IN ('pending','producing')"
            ).fetchone()[0]
        )
        acceptance = {
            "database_integrity_ok": quick_check == "ok",
            "foreign_keys_ok": foreign_key_violations == 0,
            "all_active_orders_in_queue": (
                len(queue_before) == active_count == int(result.get("queue_count") or 0)
            ),
            "unexpected_failures_zero": (
                operation_metrics["order_result_counts"].get("failed", 0) == 0
            ),
            "blocked_orders_zero": (
                operation_metrics["order_result_counts"].get("blocked", 0) == 0
            ),
            "quantity_conservation_ok": (
                operation_metrics["quantity_conservation_violation_count"] == 0
            ),
            "serial_splits_zero": (
                operation_metrics["serial_split_violation_count"] == 0
            ),
            "batch_internal_conflicts_zero": (
                conflict_metrics["batch_internal_conflict_count"] == 0
            ),
            "batch_to_existing_conflicts_zero": (
                conflict_metrics["batch_to_existing_conflict_count"] == 0
            ),
            "focus_node_counts_ok": node_capacity_metrics["configured_counts_ok"],
            "focus_nodes_all_exercised": node_capacity_metrics[
                "all_configured_nodes_exercised"
            ],
            "focus_multi_node_splits_exercised": node_capacity_metrics[
                "multi_node_splits_exercised"
            ],
            "cross_shift_exercised": (
                calendar_metrics["cross_shift_operation_count"] > 0
            ),
            "cross_day_exercised": (
                calendar_metrics["cross_day_operation_count"] > 0
            ),
            "weekend_skip_exercised": (
                calendar_metrics["weekend_spanning_operation_count"] > 0
                and calendar_metrics["weekend_segment_count"] == 0
            ),
            "calendar_segments_valid": (
                calendar_metrics["invalid_segment_count"] == 0
            ),
            "external_capacity_violations_zero": (
                external_capacity_metrics["external_operation_count"] > 0
                and external_capacity_metrics["capacity_violation_count"] == 0
            ),
            "execution_progress_unchanged": execution_before == execution_after,
        }
        report = {
            "schema": "qr-system-v091-batch-replica-plan/v2",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "ok": all(acceptance.values()),
            "replica_only": True,
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
            "planning_now": args.planning_now,
            "start_date": args.start_date,
            "auto_plan_key": args.auto_plan_key,
            "active_order_count": active_count,
            "queue_count": len(queue_before),
            "queue": [
                {
                    "position": index,
                    "order_id": int(order["id"]),
                    "order_no": order.get("order_no") or "",
                    "effective_priority_level": int(
                        order.get("effective_priority_level") or 3
                    ),
                    "effective_is_expedited": int(
                        order.get("effective_is_expedited") or 0
                    ),
                    "deadline": order.get("deadline") or "",
                }
                for index, order in enumerate(queue_before, start=1)
            ],
            "operation_metrics": operation_metrics,
            "conflict_metrics": conflict_metrics,
            "node_capacity_metrics": node_capacity_metrics,
            "calendar_metrics": calendar_metrics,
            "external_capacity_metrics": external_capacity_metrics,
            "deadline_metrics": deadline_metrics,
            "execution_fingerprint": {
                "before": execution_before,
                "after": execution_after,
                "unchanged": execution_before == execution_after,
            },
            "acceptance": acceptance,
            "orders": order_results,
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
                    "ok": report["ok"],
                    "active_order_count": report["active_order_count"],
                    "queue_count": report["queue_count"],
                    "operation_metrics": report["operation_metrics"],
                    "conflict_metrics": report["conflict_metrics"],
                    "node_capacity_metrics": report["node_capacity_metrics"],
                    "calendar_metrics": {
                        key: value
                        for key, value in report["calendar_metrics"].items()
                        if key not in {"weekend_segments", "invalid_segments"}
                    },
                    "external_capacity_metrics": {
                        key: value
                        for key, value in report["external_capacity_metrics"].items()
                        if key not in {"operations", "violations"}
                    },
                    "deadline_metrics": {
                        key: value
                        for key, value in report["deadline_metrics"].items()
                        if key != "late_orders"
                    },
                    "execution_fingerprint": report["execution_fingerprint"],
                    "acceptance": report["acceptance"],
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
