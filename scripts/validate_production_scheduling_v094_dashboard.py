#!/usr/bin/env python3
"""Validate the Task 7 dashboard contract on a disposable production replica."""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("SECRET_KEY", "task7-v094-dashboard-validation-only")

from modules.migrations import LATEST_VERSION, run_migrations  # noqa: E402
from modules.repositories.production_node_repository import (  # noqa: E402
    ProductionNodeRepository,
)
from modules.repositories.schedule_capacity_repository import (  # noqa: E402
    ScheduleCapacityRepository,
)


FORMAL_TABLES = (
    "orders",
    "order_processes",
    "order_process_schedules",
    "order_process_schedule_segments",
    "production_node_schedule_allocations",
    "schedule_revisions",
    "schedule_revision_items",
    "work_records",
    "scrap_records",
    "rework_records",
)


def _rows(db, sql, params=()):
    return [dict(row) for row in db.execute(sql, params).fetchall()]


def _table_exists(db, table):
    return db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _formal_digest(db):
    snapshot = {}
    for table in FORMAL_TABLES:
        if _table_exists(db, table):
            snapshot[table] = _rows(db, f"SELECT * FROM {table} ORDER BY id")
    payload = json.dumps(
        snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _candidate_items(db):
    rows = []
    for item in ScheduleCapacityRepository.list_latest_candidate_revision_items(
        limit=1000, db=db
    ):
        normalized = dict(item)
        try:
            payload = json.loads(normalized.get("payload_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            payload = {}
        rows.append({**payload, **normalized, "candidate_revision": True})
    return rows


def _formal_operations(db):
    operations = [
        {**dict(row), "candidate_revision": False}
        for row in ScheduleCapacityRepository.list_scheduled_operations(1000, db=db)
    ]
    schedule_ids = [row.get("id") for row in operations]
    segments = {}
    for row in ScheduleCapacityRepository.list_schedule_segments(schedule_ids, db=db):
        segment = dict(row)
        segments.setdefault(segment["schedule_id"], []).append(segment)
    allocations = {}
    for row in ScheduleCapacityRepository.list_schedule_allocations(schedule_ids, db=db):
        allocation = dict(row)
        allocations.setdefault(allocation["schedule_id"], []).append(allocation)
    for operation in operations:
        operation["segments"] = segments.get(operation.get("id"), [])
        operation["allocations"] = allocations.get(operation.get("id"), [])
    return operations


def _intervals(operations):
    result = []
    for operation in operations:
        if operation.get("status") == "blocked":
            continue
        segments = operation.get("segments") or []
        if segments:
            for segment in segments:
                result.append({
                    "order_id": operation.get("order_id"),
                    "order_no": operation.get("order_no"),
                    "process_id": operation.get("process_id"),
                    "process_name": operation.get("process_name"),
                    "production_node_id": segment.get("production_node_id")
                    or operation.get("production_node_id"),
                    "start_at": segment.get("segment_start_at"),
                    "end_at": segment.get("segment_end_at"),
                    "occupied_minutes": segment.get("occupied_minutes") or 0,
                    "source": "segment",
                })
            continue
        start_at = operation.get("planned_start_at") or operation.get("plan_start")
        end_at = operation.get("planned_end_at") or operation.get("plan_end")
        if start_at and end_at:
            result.append({
                "order_id": operation.get("order_id"),
                "order_no": operation.get("order_no"),
                "process_id": operation.get("process_id"),
                "process_name": operation.get("process_name"),
                "production_node_id": operation.get("production_node_id"),
                "start_at": start_at,
                "end_at": end_at,
                "occupied_minutes": operation.get("occupied_minutes") or 0,
                "source": "operation",
            })
    return result


def validate(source_db, output_db):
    source = Path(source_db).resolve()
    output = Path(output_db).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, output)

    db = sqlite3.connect(output)
    db.row_factory = sqlite3.Row
    try:
        before_version = int(db.execute("PRAGMA user_version").fetchone()[0])
        run_migrations(db)
        after_version = int(db.execute("PRAGMA user_version").fetchone()[0])
        if after_version != LATEST_VERSION or after_version != 94:
            raise RuntimeError(
                f"dashboard replica migration incomplete: {after_version}"
            )

        before_digest = _formal_digest(db)
        formal_operations = _formal_operations(db)
        candidate_operations = _candidate_items(db)
        candidate_keys = {
            (row.get("order_id"), row.get("order_process_id"))
            for row in candidate_operations
        }
        display_operations = [
            row for row in formal_operations
            if (row.get("order_id"), row.get("order_process_id"))
            not in candidate_keys
        ] + candidate_operations
        intervals = _intervals(display_operations)
        nodes = ProductionNodeRepository.list_nodes(db=db, full=True)
        calendars = ScheduleCapacityRepository.list_calendars(db=db)
        unavailable = [
            dict(row)
            for row in ScheduleCapacityRepository.list_capacity_unavailability(db=db)
        ]
        overrides = [
            dict(row)
            for row in ScheduleCapacityRepository.list_capacity_overrides(db=db)
        ]
        risks = [
            dict(row)
            for row in ScheduleCapacityRepository.list_schedule_risk_inputs(
                limit=1000, db=db
            )
        ]
        replan_orders = _rows(
            db,
            "SELECT id,order_no,schedule_replan_reason FROM orders "
            "WHERE deleted_at IS NULL AND schedule_replan_required=1 ORDER BY order_no",
        )
        locks = _rows(
            db,
            "SELECT l.id,l.revision_item_id,l.production_node_id,r.order_id "
            "FROM schedule_node_task_locks l "
            "JOIN schedule_revision_items i ON i.id=l.revision_item_id "
            "JOIN schedule_revisions r ON r.id=i.revision_id "
            "WHERE l.status='active' ORDER BY l.id",
        )
        revision_statuses = Counter(
            f"{row['status']}:{row['approval_status']}"
            for row in db.execute(
                "SELECT status,approval_status FROM schedule_revisions"
            ).fetchall()
        )

        missing_start_or_end = [
            row for row in intervals if not row.get("start_at") or not row.get("end_at")
        ]
        node_ids = {int(row["id"]) for row in nodes}
        missing_node_intervals = [
            row for row in intervals
            if row.get("production_node_id") in (None, "")
            or int(row["production_node_id"]) not in node_ids
        ]
        group_counts = {
            "production_nodes": len({
                row.get("production_node_id") for row in intervals
                if row.get("production_node_id") not in (None, "")
            }),
            "processes": len({row.get("process_id") for row in intervals}),
            "orders": len({row.get("order_id") for row in intervals}),
        }
        capacity_minutes = sum(float(row.get("capacity_minutes") or 0) for row in nodes)
        occupied_minutes = sum(
            float(row.get("occupied_minutes") or 0) for row in intervals
        )
        after_digest = _formal_digest(db)
        quick_check = db.execute("PRAGMA quick_check").fetchone()[0]
        foreign_key_count = len(db.execute("PRAGMA foreign_key_check").fetchall())

        report = {
            "source_db": str(source),
            "output_db": str(output),
            "before_version": before_version,
            "after_version": after_version,
            "formal_operations": len(formal_operations),
            "candidate_operations": len(candidate_operations),
            "display_operations": len(display_operations),
            "minute_intervals": len(intervals),
            "segment_intervals": sum(
                1 for row in intervals if row.get("source") == "segment"
            ),
            "fallback_operation_intervals": sum(
                1 for row in intervals if row.get("source") == "operation"
            ),
            "timeline_group_counts": group_counts,
            "production_nodes": len(nodes),
            "active_calendars": len(calendars),
            "calendar_unavailability": len(unavailable),
            "calendar_overrides": len(overrides),
            "overtime_overrides": sum(
                1 for row in overrides if row.get("override_type") == "overtime"
            ),
            "daily_node_capacity_minutes": round(capacity_minutes, 2),
            "scheduled_interval_minutes": round(occupied_minutes, 2),
            "risk_input_orders": len(risks),
            "pending_replan_orders": len(replan_orders),
            "locked_tasks": len(locks),
            "revision_status_counts": dict(sorted(revision_statuses.items())),
            "missing_time_intervals": len(missing_start_or_end),
            "missing_node_intervals": len(missing_node_intervals),
            "formal_digest_unchanged": before_digest == after_digest,
            "quick_check": quick_check,
            "foreign_key_violations": foreign_key_count,
        }
        if not intervals or not group_counts["orders"]:
            raise RuntimeError("production replica has no timeline facts")
        if missing_start_or_end:
            raise RuntimeError("dashboard timeline contains incomplete intervals")
        if not nodes or capacity_minutes <= 0:
            raise RuntimeError("production-node capacity facts are missing")
        if not report["formal_digest_unchanged"]:
            raise RuntimeError("read-only dashboard validation modified formal facts")
        if quick_check != "ok" or foreign_key_count:
            raise RuntimeError("dashboard replica integrity validation failed")
        return report
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--output-db", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    report = validate(args.source_db, args.output_db)
    report_path = Path(args.report).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
