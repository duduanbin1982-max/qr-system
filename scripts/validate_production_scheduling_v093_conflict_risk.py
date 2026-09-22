#!/usr/bin/env python3
"""Validate V093 conflict detection and delivery-risk evidence on a DB copy."""

from collections import Counter
from datetime import datetime
import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("SECRET_KEY", "task5-v093-local-validation-only")

from modules.domain.production_node_scheduling import NodeSchedulingError  # noqa: E402
from modules.domain.schedule_deadline_risk import ScheduleDeadlineRiskPolicy  # noqa: E402
from modules.migration_production_nodes import (  # noqa: E402
    m093_schedule_conflict_risk_evidence,
)
from modules.repositories.schedule_capacity_repository import (  # noqa: E402
    ScheduleCapacityRepository,
)
from modules.services.schedule_capacity_service import ScheduleCapacityService  # noqa: E402


def _risk_report(db, limit=1000):
    conflicts = [
        dict(row) for row in ScheduleCapacityRepository.list_schedule_conflicts(db=db)
    ]
    conflicts_by_order = {}
    for conflict in conflicts:
        for field in ("first_order_id", "second_order_id"):
            order_id = conflict.get(field)
            if order_id not in (None, ""):
                conflicts_by_order.setdefault(int(order_id), []).append(conflict)

    risk_counts = Counter()
    risk_orders = []
    for raw in ScheduleCapacityRepository.list_schedule_risk_inputs(
        limit=limit, db=db
    ):
        row = dict(raw)
        quantity = int(row.get("quantity") or 0)
        completed = int(row.get("completed") or 0)
        risk = ScheduleDeadlineRiskPolicy.evaluate(
            deadline_text=row.get("deadline") or "",
            projected_completion_at=row.get("projected_completion_at") or "",
            plan_end=row.get("plan_end") or "",
            now=datetime(2026, 9, 22, 12, 0),
            completed=row.get("order_status") == "completed"
            or (quantity > 0 and completed >= quantity),
            blocked_count=row.get("blocked_count") or 0,
            blocked_reasons=tuple(
                item.strip()
                for item in str(row.get("blocked_reasons") or "").split("；")
                if item.strip()
            ),
            conflict_count=row.get("conflict_count") or 0,
            conflict_details=conflicts_by_order.get(int(row["order_id"]), ()),
        )
        risk_counts[risk["level"]] += 1
        if risk["level"] != "none":
            risk_orders.append(
                {
                    "order_id": row["order_id"],
                    "order_no": row["order_no"],
                    **risk,
                }
            )
    risk_orders.sort(
        key=lambda item: (
            {"overdue": 0, "high": 1, "medium": 2, "low": 3}.get(
                item["level"], 4
            ),
            -int(item.get("delay_minutes") or 0),
            item.get("order_no") or "",
        )
    )
    return conflicts, dict(sorted(risk_counts.items())), risk_orders


def _validate_gate_with_temporary_downtime(db):
    fixture = db.execute(
        "SELECT i.revision_id,i.production_node_id,i.process_line_id,"
        "i.planned_start_at,i.planned_end_at,n.legacy_process_line_id "
        "FROM schedule_revision_items i "
        "JOIN schedule_revisions r ON r.id=i.revision_id "
        "LEFT JOIN production_nodes n ON n.id=i.production_node_id "
        "WHERE r.status='published' AND i.status<>'blocked' "
        "AND i.production_node_id IS NOT NULL "
        "AND COALESCE(i.planned_start_at,'')<>'' "
        "AND COALESCE(i.planned_end_at,'')<>'' "
        "ORDER BY r.id,i.seq_order,i.id LIMIT 1"
    ).fetchone()
    if fixture is None:
        return {"status": "not_applicable", "reason": "没有可验证的已发布节点排程"}

    line_id = fixture["process_line_id"] or fixture["legacy_process_line_id"]
    if line_id is None:
        return {"status": "not_applicable", "reason": "验证节点缺少 Legacy 外键映射"}
    db.execute("SAVEPOINT v093_gate_validation")
    try:
        downtime_id = db.execute(
            "INSERT INTO schedule_downtime_events "
            "(process_line_id,production_node_id,start_at,end_at,reason,status,source_type) "
            "VALUES (?,?,?,?,?,'active','v093_validation')",
            (
                line_id,
                fixture["production_node_id"],
                fixture["planned_start_at"],
                fixture["planned_end_at"],
                "V093 disposable-copy conflict gate validation",
            ),
        ).lastrowid
        try:
            ScheduleCapacityService._assert_revision_conflict_gate(
                fixture["revision_id"], "replica_validation", db
            )
        except NodeSchedulingError as exc:
            result = {
                "status": "passed",
                "code": exc.code,
                "revision_id": fixture["revision_id"],
                "production_node_id": fixture["production_node_id"],
                "temporary_downtime_id": downtime_id,
                "blocking_count": exc.details.get("blocking_count"),
                "conflict_types": sorted(
                    {
                        item.get("conflict_type")
                        for item in exc.details.get("conflicts", [])
                    }
                ),
            }
        else:
            raise RuntimeError("V093 conflict gate did not reject overlapping downtime")
    finally:
        db.execute("ROLLBACK TO v093_gate_validation")
        db.execute("RELEASE v093_gate_validation")
    return result


def validate(source_db, output_db):
    source = Path(source_db).resolve()
    output = Path(output_db).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, output)

    db = sqlite3.connect(output)
    db.row_factory = sqlite3.Row
    try:
        before_version = db.execute("PRAGMA user_version").fetchone()[0]
        if before_version == 92:
            m093_schedule_conflict_risk_evidence(db)
            db.execute("PRAGMA user_version=93")
            db.commit()
        elif before_version != 93:
            raise RuntimeError(
                f"V093 validator requires a V092 or V093 source, got V{before_version}"
            )
        after_version = db.execute("PRAGMA user_version").fetchone()[0]
        if after_version != 93:
            raise RuntimeError(f"V093 migration incomplete: {after_version} != 93")

        conflicts, risk_counts, risk_orders = _risk_report(db)
        effective_count = db.execute(
            "SELECT COUNT(*) FROM schedule_effective_capacity_intervals"
        ).fetchone()[0]
        segment_count = db.execute(
            "SELECT COUNT(*) FROM schedule_effective_capacity_intervals "
            "WHERE fact_type='segment'"
        ).fetchone()[0]
        fallback_count = db.execute(
            "SELECT COUNT(*) FROM schedule_effective_capacity_intervals "
            "WHERE fact_type='schedule'"
        ).fetchone()[0]
        locked_count = db.execute(
            "SELECT COUNT(*) FROM schedule_effective_capacity_intervals "
            "WHERE fact_type='locked_revision_item'"
        ).fetchone()[0]
        external_capacity_count = db.execute(
            "SELECT COUNT(*) FROM order_process_schedules s "
            "JOIN schedule_effective_capacity_intervals f ON f.schedule_id=s.id "
            "WHERE s.execution_mode IN ('outsourced','non_scheduled')"
        ).fetchone()[0]
        duplicate_fallback_count = db.execute(
            "SELECT COUNT(*) FROM schedule_effective_capacity_intervals f "
            "WHERE f.fact_type='schedule' AND EXISTS ("
            "SELECT 1 FROM order_process_schedule_segments ss "
            "WHERE ss.schedule_id=f.schedule_id)"
        ).fetchone()[0]
        gate = _validate_gate_with_temporary_downtime(db)

        quick_check = db.execute("PRAGMA quick_check").fetchone()[0]
        foreign_key_count = len(db.execute("PRAGMA foreign_key_check").fetchall())
        report = {
            "source_db": str(source),
            "output_db": str(output),
            "before_version": before_version,
            "after_version": after_version,
            "effective_capacity_intervals": effective_count,
            "segment_intervals": segment_count,
            "fallback_intervals": fallback_count,
            "locked_candidate_intervals": locked_count,
            "external_capacity_intervals": external_capacity_count,
            "duplicate_segment_fallback_intervals": duplicate_fallback_count,
            "formal_node_conflicts": len(conflicts),
            "risk_counts": risk_counts,
            "risk_order_count": len(risk_orders),
            "delayed_order_count": sum(
                1 for item in risk_orders if int(item.get("delay_minutes") or 0) > 0
            ),
            "max_delay_minutes": max(
                (int(item.get("delay_minutes") or 0) for item in risk_orders),
                default=0,
            ),
            "top_risk_orders": risk_orders[:20],
            "conflict_gate_validation": gate,
            "quick_check": quick_check,
            "foreign_key_violations": foreign_key_count,
        }
        if external_capacity_count or duplicate_fallback_count:
            raise RuntimeError("V093 effective capacity projection contains invalid facts")
        if gate.get("status") != "passed":
            raise RuntimeError(f"V093 conflict gate validation incomplete: {gate}")
        if quick_check != "ok" or foreign_key_count:
            raise RuntimeError("V093 replica integrity validation failed")
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
