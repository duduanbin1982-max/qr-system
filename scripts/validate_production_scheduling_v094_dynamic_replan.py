#!/usr/bin/env python3
"""Validate V094 production-fact dynamic replanning on a disposable DB copy."""

import argparse
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
os.environ.setdefault("SECRET_KEY", "task6-v094-local-validation-only")

from modules import config  # noqa: E402
from modules.migrations import LATEST_VERSION, run_migrations  # noqa: E402
from modules.repositories.schedule_capacity_repository import (  # noqa: E402
    ScheduleCapacityRepository,
)
from modules.services.rework_service import ReworkService  # noqa: E402
from modules.services.schedule_capacity_service import ScheduleCapacityService  # noqa: E402


def _rows(db, sql, params=()):
    return [dict(row) for row in db.execute(sql, params).fetchall()]


def _digest(value):
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _formal_projection(db, order_id):
    return {
        "order": _rows(
            db,
            "SELECT id,current_schedule_revision_id,plan_start,plan_end,schedule_version "
            "FROM orders WHERE id=?",
            (order_id,),
        ),
        "schedules": _rows(
            db,
            "SELECT * FROM order_process_schedules WHERE order_id=? ORDER BY id",
            (order_id,),
        ),
        "segments": _rows(
            db,
            "SELECT ss.* FROM order_process_schedule_segments ss "
            "JOIN order_process_schedules s ON s.id=ss.schedule_id "
            "WHERE s.order_id=? ORDER BY ss.id",
            (order_id,),
        ),
        "allocations": _rows(
            db,
            "SELECT a.* FROM production_node_schedule_allocations a "
            "JOIN order_process_schedules s ON s.id=a.schedule_id "
            "WHERE s.order_id=? ORDER BY a.id",
            (order_id,),
        ),
    }


def _execution_facts(db, order_id):
    return {
        "order_processes": _rows(
            db,
            "SELECT * FROM order_processes WHERE order_id=? ORDER BY id",
            (order_id,),
        ),
        "work_records": _rows(
            db,
            "SELECT * FROM work_records WHERE order_id=? ORDER BY id",
            (order_id,),
        ),
        "scrap_records": _rows(
            db,
            "SELECT * FROM scrap_records WHERE order_id=? ORDER BY id",
            (order_id,),
        ),
        "rework_records": _rows(
            db,
            "SELECT * FROM rework_records WHERE order_id=? ORDER BY id",
            (order_id,),
        ),
    }


def _select_fixture(db):
    return db.execute(
        "SELECT o.id AS order_id,o.order_no,o.quantity,o.current_schedule_revision_id,"
        "op.id AS order_process_id,op.process_id,op.completed,"
        "i.production_node_id,i.planned_start_at,i.planned_end_at "
        "FROM orders o "
        "JOIN schedule_revisions r ON r.id=o.current_schedule_revision_id "
        "JOIN schedule_revision_items i ON i.revision_id=r.id "
        "JOIN order_processes op ON op.id=i.order_process_id "
        "WHERE o.deleted_at IS NULL AND o.status IN ('pending','producing') "
        "AND r.status='published' AND i.status<>'blocked' "
        "AND i.production_node_id IS NOT NULL "
        "AND COALESCE(i.planned_start_at,'')<>'' "
        "AND COALESCE(i.planned_end_at,'')<>'' "
        "AND COALESCE(op.completed,0)<o.quantity "
        "ORDER BY o.id,i.seq_order,i.id LIMIT 1"
    ).fetchone()


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
                f"V094 migration incomplete: {after_version} != {LATEST_VERSION}"
            )

        fixture = _select_fixture(db)
        if fixture is None:
            raise RuntimeError("没有可用于 V094 动态重排演练的已发布未完工节点任务")
        fixture = dict(fixture)
        actor = db.execute(
            "SELECT id FROM users WHERE status='active' ORDER BY id LIMIT 1"
        ).fetchone()
        if actor is None:
            raise RuntimeError("生产副本没有可用于验收的活动用户")
        actor_id = int(actor["id"])

        config.PRODUCTION_NODE_QUERY_ENABLED = True
        config.PRODUCTION_NODE_COMPAT_AUDIT_ENABLED = True
        config.PRODUCTION_NODE_WRITE_ENABLED = True
        config.PRODUCTION_NODE_ENGINE_ENABLED = True

        formal_before = _formal_projection(db, fixture["order_id"])
        rework_id = ReworkService.create_rework(
            fixture["order_id"],
            fixture["process_id"],
            actor_id,
            1,
            "V094 生产只读副本动态重排演练",
            db=db,
        )
        downtime = ScheduleCapacityService.create_downtime_event(
            fixture["production_node_id"],
            fixture["planned_start_at"],
            fixture["planned_end_at"],
            "V094 生产只读副本停机演练",
            created_by=actor_id,
            db=db,
        )
        execution_before_replan = _execution_facts(db, fixture["order_id"])

        run_key = f"task6-v094-replica-{fixture['order_id']}"
        result = ScheduleCapacityService.dynamic_replan_order(
            fixture["order_id"],
            start_at=fixture["planned_start_at"],
            schedule_run_key=run_key,
            reason="生产只读副本：报工、返工、停机和节点占用变化演练",
            actor_id=actor_id,
            db=db,
        )

        formal_after = _formal_projection(db, fixture["order_id"])
        execution_after_replan = _execution_facts(db, fixture["order_id"])
        formal_unchanged = _digest(formal_before) == _digest(formal_after)
        execution_unchanged = (
            _digest(execution_before_replan) == _digest(execution_after_replan)
        )
        revision_id = int(result["schedule_revision_id"])
        summary, differences = ScheduleCapacityRepository.get_replan_evidence(
            revision_id, db=db
        )
        triggers = [
            dict(row) for row in ScheduleCapacityRepository.list_replan_triggers(
                fixture["order_id"], db=db
            )
        ]
        trigger_types = sorted({item["trigger_type"] for item in triggers})
        input_snapshot = result["input_snapshot"]
        run = db.execute(
            "SELECT * FROM schedule_runs WHERE schedule_run_key=?", (run_key,)
        ).fetchone()
        order = db.execute(
            "SELECT schedule_replan_required,schedule_replan_reason,"
            "current_schedule_revision_id FROM orders WHERE id=?",
            (fixture["order_id"],),
        ).fetchone()
        quick_check = db.execute("PRAGMA quick_check").fetchone()[0]
        foreign_key_count = len(db.execute("PRAGMA foreign_key_check").fetchall())

        report = {
            "source_db": str(source),
            "output_db": str(output),
            "before_version": before_version,
            "after_version": after_version,
            "fixture": fixture,
            "injected_rework_id": rework_id,
            "injected_downtime_id": downtime["event"]["id"],
            "downtime_affected_order_ids": downtime["affected_order_ids"],
            "trigger_types": trigger_types,
            "input_snapshot_counts": {
                "work_reports": len(input_snapshot.get("work_reports") or []),
                "scrap_records": len(input_snapshot.get("scrap_records") or []),
                "rework_records": len(input_snapshot.get("rework_records") or []),
                "downtime": len(input_snapshot.get("downtime") or []),
                "occupancy": len(input_snapshot.get("occupancy") or []),
                "locked_tasks": len(input_snapshot.get("locked_tasks") or []),
            },
            "run_status": run["status"],
            "candidate_revision_id": revision_id,
            "candidate_revision_status": result["revision_status"],
            "formal_projection_unchanged": formal_unchanged,
            "execution_facts_unchanged_during_replan": execution_unchanged,
            "current_revision_unchanged": (
                int(order["current_schedule_revision_id"])
                == int(fixture["current_schedule_revision_id"])
            ),
            "schedule_replan_required": int(order["schedule_replan_required"]),
            "schedule_replan_reason": order["schedule_replan_reason"],
            "difference_count": len(differences),
            "changed_operation_count": int(summary["changed_operation_count"]),
            "node_change_count": int(summary["node_change_count"]),
            "risk_change": summary["risk_change"],
            "before_risk_level": summary["before_risk_level"],
            "after_risk_level": summary["after_risk_level"],
            "before_delay_minutes": int(summary["before_delay_minutes"]),
            "after_delay_minutes": int(summary["after_delay_minutes"]),
            "blocking_conflict_count": len(result.get("revision_conflicts") or []),
            "quick_check": quick_check,
            "foreign_key_violations": foreign_key_count,
        }
        if not {"rework_created", "downtime_created"}.issubset(trigger_types):
            raise RuntimeError(f"V094 trigger evidence incomplete: {trigger_types}")
        if not formal_unchanged or not execution_unchanged:
            raise RuntimeError("V094 draft replan modified formal execution facts")
        if not report["current_revision_unchanged"]:
            raise RuntimeError("V094 draft replan replaced the published revision")
        if result["revision_status"] != "draft" or run["status"] != "completed":
            raise RuntimeError("V094 dynamic replan did not produce a completed draft")
        if int(order["schedule_replan_required"]) != 1:
            raise RuntimeError("V094 draft incorrectly cleared the pending replan marker")
        if not differences or summary is None:
            raise RuntimeError("V094 immutable replan difference evidence is missing")
        if quick_check != "ok" or foreign_key_count:
            raise RuntimeError("V094 replica integrity validation failed")
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
