#!/usr/bin/env python3
"""Run Task 8 real-order planning, historical replay and final acceptance."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import statistics
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("SECRET_KEY", "task8-v094-final-acceptance-only")

from modules.migrations import LATEST_VERSION, run_migrations  # noqa: E402
from modules.repositories.schedule_capacity_repository import (  # noqa: E402
    ScheduleCapacityRepository,
)
import modules.services.schedule_capacity_service as schedule_service_module  # noqa: E402
from modules.services.schedule_capacity_service import (  # noqa: E402
    ScheduleCapacityService,
)
from scripts.validate_production_scheduling_v091_batch_replica import (  # noqa: E402
    _calendar_metrics,
    _conflict_metrics,
    _deadline_metrics,
    _execution_fingerprint,
    _external_capacity_metrics,
    _node_capacity_metrics,
    _operation_metrics,
)


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--output-db", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--actor-username", default="1000")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--planning-now", required=True)
    parser.add_argument("--auto-plan-key", required=True)
    parser.add_argument("--historical-limit", type=int, default=20)
    return parser.parse_args(argv)


def _file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _actor(db, username):
    row = db.execute(
        "SELECT id,username,name FROM users WHERE username=? "
        "AND status='active' AND deleted_at IS NULL ORDER BY id LIMIT 1",
        (str(username),),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"active actor not found: {username}")
    return dict(row)


def _historical_candidates(db, limit):
    return [
        dict(row)
        for row in db.execute(
            "SELECT o.id,o.order_no,o.quantity,o.route_id,o.route_version_id,"
            "o.plan_start,o.deadline,MIN(w.created_at) AS actual_start_at,"
            "MAX(w.created_at) AS actual_end_at,COUNT(DISTINCT w.process_id) AS reported_processes,"
            "COUNT(w.id) AS work_record_count "
            "FROM orders o JOIN work_records w ON w.order_id=o.id "
            "WHERE o.deleted_at IS NULL AND w.status='approved' "
            "AND (o.status='completed' OR (o.quantity>0 AND o.completed>=o.quantity)) "
            "AND o.route_id IS NOT NULL AND o.route_version_id IS NOT NULL "
            "AND EXISTS (SELECT 1 FROM order_processes op WHERE op.order_id=o.id "
            "AND op.process_version_id IS NOT NULL) "
            "GROUP BY o.id,o.order_no,o.quantity,o.route_id,o.route_version_id,"
            "o.plan_start,o.deadline "
            "ORDER BY actual_end_at DESC,o.id DESC LIMIT ?",
            (max(min(int(limit or 20), 100), 1),),
        ).fetchall()
    ]


def _actual_operation_windows(db, order_id):
    return [
        dict(row)
        for row in db.execute(
            "SELECT op.id AS order_process_id,op.process_id,p.name AS process_name,"
            "op.seq_order,MIN(w.created_at) AS actual_first_report_at,"
            "MAX(w.created_at) AS actual_last_report_at,"
            "COALESCE(SUM(CASE WHEN w.status='approved' THEN w.quantity ELSE 0 END),0) "
            "AS approved_quantity "
            "FROM order_processes op JOIN processes p ON p.id=op.process_id "
            "LEFT JOIN work_records w ON w.order_id=op.order_id "
            "AND w.process_id=op.process_id AND w.status='approved' "
            "WHERE op.order_id=? GROUP BY op.id,op.process_id,p.name,op.seq_order "
            "ORDER BY op.seq_order,op.id",
            (int(order_id),),
        ).fetchall()
    ]


def _timestamp(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("T", " "))
    except ValueError:
        return None


def _historical_replay(db, order, actor_id, index):
    order_id = int(order["id"])
    actual_operations = _actual_operation_windows(db, order_id)
    actual_by_process = {
        int(row["process_id"]): row for row in actual_operations
    }
    start_at = _timestamp(order.get("actual_start_at"))
    end_at = _timestamp(order.get("actual_end_at"))
    start_date = (
        (start_at or _timestamp(order.get("plan_start")) or datetime(2026, 9, 22))
        .date().isoformat()
    )
    savepoint = f"task8_history_{index}"
    db.execute(f"SAVEPOINT {savepoint}")
    try:
        db.execute(
            "UPDATE orders SET status='pending',completed=0,current_schedule_revision_id=NULL,"
            "plan_start=?,plan_end='' WHERE id=?",
            (start_date, order_id),
        )
        db.execute(
            "UPDATE order_processes SET completed=0,scrapped=0,rework=0,status='pending' "
            "WHERE order_id=?",
            (order_id,),
        )
        result = ScheduleCapacityService.generate_order_schedule(
            order_id,
            start_date=start_date,
            schedule_run_key=f"task8-history-{order_id}-{index}",
            actor_id=actor_id,
            db=db,
            use_node_engine_override=True,
        )
        operations = result.get("operations") or []
        planned = [row for row in operations if row.get("status") == "planned"]
        blocked = [row for row in operations if row.get("status") == "blocked"]
        planned_end_values = [
            _timestamp(row.get("planned_end_at")) for row in planned
            if _timestamp(row.get("planned_end_at")) is not None
        ]
        projected_end = max(planned_end_values) if planned_end_values else None
        planned_minutes = sum(float(row.get("occupied_minutes") or 0) for row in planned)
        actual_span_minutes = (
            max((end_at - start_at).total_seconds() / 60, 0)
            if start_at and end_at else None
        )
        quantity_violations = []
        replay_processes = []
        for operation in operations:
            expected = int(operation.get("quantity") or 0)
            allocations = operation.get("allocations") or []
            allocated = sum(int(row.get("quantity") or 0) for row in allocations)
            execution_mode = operation.get("execution_mode", "internal")
            if (
                operation.get("status") == "planned"
                and execution_mode not in {"outsourced", "non_scheduled"}
                and allocated != expected
            ):
                quantity_violations.append({
                    "order_process_id": operation.get("order_process_id"),
                    "expected": expected,
                    "allocated": allocated,
                })
            actual = actual_by_process.get(int(operation.get("process_id") or 0), {})
            replay_processes.append({
                "order_process_id": operation.get("order_process_id"),
                "process_id": operation.get("process_id"),
                "process_name": operation.get("process_name")
                or operation.get("process_name_snapshot") or "",
                "status": operation.get("status"),
                "blocked_code": operation.get("blocked_code") or "",
                "standard_match_scope": operation.get("standard_match_scope") or "",
                "planned_start_at": operation.get("planned_start_at") or "",
                "planned_end_at": operation.get("planned_end_at") or "",
                "occupied_minutes": float(operation.get("occupied_minutes") or 0),
                "production_node_count": len({
                    int(row["production_node_id"])
                    for row in operation.get("allocations") or []
                    if row.get("production_node_id") not in (None, "")
                }),
                "actual_first_report_at": actual.get("actual_first_report_at") or "",
                "actual_last_report_at": actual.get("actual_last_report_at") or "",
                "actual_approved_quantity": int(actual.get("approved_quantity") or 0),
            })
        return {
            "order_id": order_id,
            "order_no": order.get("order_no") or "",
            "quantity": int(order.get("quantity") or 0),
            "start_date": start_date,
            "actual_start_at": order.get("actual_start_at") or "",
            "actual_end_at": order.get("actual_end_at") or "",
            "actual_span_minutes": actual_span_minutes,
            "projected_end_at": projected_end.isoformat(sep=" ") if projected_end else "",
            "planned_minutes": round(planned_minutes, 2),
            "calendar_span_ratio": (
                round(planned_minutes / actual_span_minutes, 4)
                if actual_span_minutes and actual_span_minutes > 0 else None
            ),
            "operation_count": len(operations),
            "planned_operation_count": len(planned),
            "blocked_operation_count": len(blocked),
            "blocked_codes": dict(Counter(
                row.get("blocked_code") or "UNSPECIFIED" for row in blocked
            )),
            "quantity_conservation_violation_count": len(quantity_violations),
            "quantity_conservation_violations": quantity_violations,
            "conflict_count": len(result.get("conflicts") or []),
            "deadline": order.get("deadline") or "",
            "actual_deadline_met": bool(
                end_at and order.get("deadline")
                and end_at.date().isoformat() <= str(order["deadline"])
            ),
            "projected_deadline_met": bool(
                projected_end and order.get("deadline")
                and projected_end.date().isoformat() <= str(order["deadline"])
            ),
            "processes": replay_processes,
            "ok": not blocked and not quantity_violations and not result.get("conflicts"),
        }
    except Exception as exc:
        return {
            "order_id": order_id,
            "order_no": order.get("order_no") or "",
            "ok": False,
            "error": str(exc),
            "operation_count": 0,
            "blocked_operation_count": 0,
            "quantity_conservation_violation_count": 0,
            "conflict_count": 0,
            "processes": [],
        }
    finally:
        db.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        db.execute(f"RELEASE SAVEPOINT {savepoint}")


def summarize_historical_replays(replays):
    ratios = [
        float(row["calendar_span_ratio"])
        for row in replays if row.get("calendar_span_ratio") is not None
    ]
    errors = Counter()
    for row in replays:
        for code, count in (row.get("blocked_codes") or {}).items():
            errors[code] += int(count)
        if row.get("error"):
            errors["REPLAY_ERROR"] += 1
    return {
        "selected_order_count": len(replays),
        "successful_order_count": sum(1 for row in replays if row.get("ok")),
        "failed_order_count": sum(1 for row in replays if not row.get("ok")),
        "operation_count": sum(int(row.get("operation_count") or 0) for row in replays),
        "blocked_operation_count": sum(
            int(row.get("blocked_operation_count") or 0) for row in replays
        ),
        "quantity_conservation_violation_count": sum(
            int(row.get("quantity_conservation_violation_count") or 0)
            for row in replays
        ),
        "conflict_count": sum(int(row.get("conflict_count") or 0) for row in replays),
        "blocked_codes": dict(sorted(errors.items())),
        "actual_deadline_met_count": sum(
            1 for row in replays if row.get("actual_deadline_met")
        ),
        "projected_deadline_met_count": sum(
            1 for row in replays if row.get("projected_deadline_met")
        ),
        "calendar_span_ratio_sample_count": len(ratios),
        "median_planned_to_actual_calendar_span_ratio": (
            round(statistics.median(ratios), 4) if ratios else None
        ),
    }


def build_acceptance(
    *,
    source_replica_unchanged,
    quick_check,
    foreign_key_violations,
    after_version,
    active_count,
    queue_count,
    batch_queue_count,
    operation_metrics,
    conflict_metrics,
    node_metrics,
    calendar_metrics,
    external_metrics,
    execution_facts_unchanged,
    historical_metrics,
    latest_compat_mismatches,
):
    """Return the explicit Task 8 production-acceptance gates."""

    return {
        "source_replica_unchanged": bool(source_replica_unchanged),
        "database_integrity_ok": quick_check == "ok",
        "foreign_keys_ok": int(foreign_key_violations) == 0,
        "schema_is_v094": int(after_version) == 94,
        "all_active_orders_in_queue": (
            int(queue_count) == int(active_count) == int(batch_queue_count)
        ),
        "active_orders_all_succeeded": (
            operation_metrics["order_result_counts"].get("success", 0)
            == int(active_count)
        ),
        "active_orders_blocked_zero": (
            operation_metrics["order_result_counts"].get("blocked", 0) == 0
        ),
        "active_orders_failed_zero": (
            operation_metrics["order_result_counts"].get("failed", 0) == 0
        ),
        "quantity_conservation_ok": (
            operation_metrics["quantity_conservation_violation_count"] == 0
        ),
        "serial_splits_zero": (
            operation_metrics["serial_split_violation_count"] == 0
        ),
        "node_conflicts_zero": (
            conflict_metrics["batch_internal_conflict_count"] == 0
            and conflict_metrics["batch_to_existing_conflict_count"] == 0
        ),
        "node_counts_ok": node_metrics["configured_counts_ok"],
        "all_focus_nodes_exercised": node_metrics["all_configured_nodes_exercised"],
        "multi_node_splits_exercised": node_metrics["multi_node_splits_exercised"],
        "cross_shift_exercised": calendar_metrics["cross_shift_operation_count"] > 0,
        "cross_day_exercised": calendar_metrics["cross_day_operation_count"] > 0,
        "weekend_skip_ok": (
            calendar_metrics["weekend_spanning_operation_count"] > 0
            and calendar_metrics["weekend_segment_count"] == 0
        ),
        "calendar_segments_valid": calendar_metrics["invalid_segment_count"] == 0,
        "external_capacity_ok": (
            external_metrics["external_operation_count"] > 0
            and external_metrics["capacity_violation_count"] == 0
        ),
        "execution_facts_unchanged": bool(execution_facts_unchanged),
        "historical_sample_available": historical_metrics["selected_order_count"] > 0,
        "historical_replays_all_succeeded": (
            historical_metrics["failed_order_count"] == 0
        ),
        "historical_quantity_conservation_ok": (
            historical_metrics["quantity_conservation_violation_count"] == 0
        ),
        "historical_conflicts_zero": historical_metrics["conflict_count"] == 0,
        "compatibility_mismatches_zero": int(latest_compat_mismatches) == 0,
    }


def run(args):
    source = Path(args.source_db).resolve()
    output = Path(args.output_db).resolve()
    report_path = Path(args.report).resolve()
    if not source.is_file():
        raise RuntimeError(f"source replica does not exist: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    source_before_digest = _file_digest(source)
    shutil.copy2(source, output)

    planning_now = datetime.fromisoformat(args.planning_now)
    db = sqlite3.connect(str(output), timeout=120)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=120000")
    try:
        before_version = int(db.execute("PRAGMA user_version").fetchone()[0])
        run_migrations(db)
        after_version = int(db.execute("PRAGMA user_version").fetchone()[0])
        if after_version != LATEST_VERSION or after_version != 94:
            raise RuntimeError(f"V094 required; observed V{after_version}")

        actor = _actor(db, args.actor_username)
        queue_before = ScheduleCapacityRepository.list_schedulable_orders(
            1000, db=db, now=planning_now
        )
        active_count = int(db.execute(
            "SELECT COUNT(*) FROM orders WHERE deleted_at IS NULL "
            "AND status IN ('pending','producing')"
        ).fetchone()[0])
        execution_before = _execution_fingerprint(db)

        real_datetime = schedule_service_module.datetime
        original_flags = {
            "PRODUCTION_NODE_QUERY_ENABLED": getattr(
                schedule_service_module.config,
                "PRODUCTION_NODE_QUERY_ENABLED", False,
            ),
            "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED": getattr(
                schedule_service_module.config,
                "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", False,
            ),
            "PRODUCTION_NODE_WRITE_ENABLED": getattr(
                schedule_service_module.config,
                "PRODUCTION_NODE_WRITE_ENABLED", False,
            ),
            "PRODUCTION_NODE_ENGINE_ENABLED": getattr(
                schedule_service_module.config,
                "PRODUCTION_NODE_ENGINE_ENABLED", False,
            ),
        }

        class FixedDateTime(real_datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return cls.fromtimestamp(planning_now.timestamp())
                return cls.fromtimestamp(planning_now.timestamp(), tz)

        schedule_service_module.datetime = FixedDateTime
        schedule_service_module.config.PRODUCTION_NODE_QUERY_ENABLED = True
        schedule_service_module.config.PRODUCTION_NODE_COMPAT_AUDIT_ENABLED = True
        schedule_service_module.config.PRODUCTION_NODE_WRITE_ENABLED = True
        schedule_service_module.config.PRODUCTION_NODE_ENGINE_ENABLED = True
        try:
            batch = ScheduleCapacityService.auto_plan_orders(
                start_date=args.start_date,
                auto_plan_key=args.auto_plan_key,
                limit=1000,
                actor_id=int(actor["id"]),
                db=db,
            )
            historical_candidates = _historical_candidates(
                db, args.historical_limit
            )
            historical_replays = [
                _historical_replay(db, row, int(actor["id"]), index)
                for index, row in enumerate(historical_candidates, start=1)
            ]
        finally:
            schedule_service_module.datetime = real_datetime
            for name, value in original_flags.items():
                setattr(schedule_service_module.config, name, value)

        execution_after = _execution_fingerprint(db)
        order_results = batch.get("orders") or []
        operation_metrics = _operation_metrics(order_results)
        conflict_metrics = _conflict_metrics(db, args.auto_plan_key)
        node_metrics = _node_capacity_metrics(db, args.auto_plan_key)
        calendar_metrics = _calendar_metrics(order_results)
        external_metrics = _external_capacity_metrics(order_results)
        deadline_metrics = _deadline_metrics(queue_before, order_results)
        historical_metrics = summarize_historical_replays(historical_replays)
        latest_compat_mismatches = int(db.execute(
            "SELECT COUNT(*) FROM (SELECT mismatch,ROW_NUMBER() OVER ("
            "PARTITION BY scope,source_id ORDER BY observed_at DESC,id DESC) AS rn "
            "FROM production_node_compatibility_observations) "
            "WHERE rn=1 AND mismatch=1"
        ).fetchone()[0])
        quick_check = db.execute("PRAGMA quick_check").fetchone()[0]
        foreign_keys = len(db.execute("PRAGMA foreign_key_check").fetchall())
        source_after_digest = _file_digest(source)

        acceptance = build_acceptance(
            source_replica_unchanged=source_before_digest == source_after_digest,
            quick_check=quick_check,
            foreign_key_violations=foreign_keys,
            after_version=after_version,
            active_count=active_count,
            queue_count=len(queue_before),
            batch_queue_count=int(batch.get("queue_count") or 0),
            operation_metrics=operation_metrics,
            conflict_metrics=conflict_metrics,
            node_metrics=node_metrics,
            calendar_metrics=calendar_metrics,
            external_metrics=external_metrics,
            execution_facts_unchanged=execution_before == execution_after,
            historical_metrics=historical_metrics,
            latest_compat_mismatches=latest_compat_mismatches,
        )
        report = {
            "schema": "qr-system-v094-final-scheduling-acceptance/v1",
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "ok": all(acceptance.values()),
            "replica_only": True,
            "source_db": str(source),
            "output_db": str(output),
            "source_sha256": source_before_digest,
            "before_version": before_version,
            "after_version": after_version,
            "planning_now": args.planning_now,
            "start_date": args.start_date,
            "auto_plan_key": args.auto_plan_key,
            "actor": actor,
            "active_order_count": active_count,
            "queue_count": len(queue_before),
            "batch_status": batch.get("status"),
            "operation_metrics": operation_metrics,
            "conflict_metrics": conflict_metrics,
            "node_capacity_metrics": node_metrics,
            "calendar_metrics": calendar_metrics,
            "external_capacity_metrics": external_metrics,
            "deadline_metrics": deadline_metrics,
            "historical_metrics": historical_metrics,
            "historical_replays": historical_replays,
            "latest_compatibility_mismatch_count": latest_compat_mismatches,
            "execution_fingerprint": {
                "before": execution_before,
                "after": execution_after,
                "unchanged": execution_before == execution_after,
            },
            "database": {
                "quick_check": quick_check,
                "foreign_key_violations": foreign_keys,
            },
            "acceptance": acceptance,
        }
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
        printable = {
            "ok": report["ok"],
            "before_version": report["before_version"],
            "after_version": report["after_version"],
            "active_order_count": report["active_order_count"],
            "queue_count": report["queue_count"],
            "operation_metrics": report["operation_metrics"],
            "conflict_metrics": {
                key: value for key, value in report["conflict_metrics"].items()
                if key != "conflicts_by_node"
            },
            "calendar_metrics": {
                key: value for key, value in report["calendar_metrics"].items()
                if key not in {"weekend_segments", "invalid_segments"}
            },
            "external_capacity_metrics": {
                key: value
                for key, value in report["external_capacity_metrics"].items()
                if key not in {"operations", "violations"}
            },
            "deadline_metrics": {
                key: value for key, value in report["deadline_metrics"].items()
                if key != "late_orders"
            },
            "historical_metrics": report["historical_metrics"],
            "latest_compatibility_mismatch_count": report[
                "latest_compatibility_mismatch_count"
            ],
            "acceptance": report["acceptance"],
        }
        print(json.dumps(printable, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 2
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
