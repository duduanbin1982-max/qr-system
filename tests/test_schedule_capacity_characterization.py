"""Characterization baseline for the production scheduling orchestration.

These tests intentionally exercise the current public service facade before the
large scheduling methods are split.  The summaries exclude generated database
identifiers and audit timestamps, but retain business facts that must not drift
during the refactor: version bindings, work-time snapshots, node allocation,
calendar segmentation, blocking, idempotency, replan evidence, and publication.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from factories import (
    TEST_HASH,
    bind_order_process_versions,
    create_order,
    create_process_route,
    ensure_user,
)
from modules import config
from modules.db import get_db
from modules.repositories.schedule_capacity_repository import (
    ScheduleCapacityRepository,
)
from modules.services.schedule_capacity_service import ScheduleCapacityService


BASELINE_PATH = Path(__file__).with_name("schedule_capacity_behavior_v1.json")
BASELINE = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _number(value):
    if value in (None, ""):
        return 0
    number = float(value)
    return int(number) if number.is_integer() else number


def _canonical_json(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _digest(value):
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _resource_tokens(operations):
    resource_ids = set()
    for operation in operations:
        for item in [operation, *operation.get("segments", []), *operation.get("allocations", [])]:
            resource_id = item.get("production_node_id") or item.get("process_line_id")
            if resource_id is not None:
                resource_ids.add(int(resource_id))
    return {
        resource_id: f"resource-{index}"
        for index, resource_id in enumerate(sorted(resource_ids), start=1)
    }


def _operation_summary(operation, resource_tokens):
    segment_rows = []
    for item in operation.get("segments", []):
        resource_id = item.get("production_node_id") or item.get("process_line_id")
        segment_rows.append(
            {
                "resource": resource_tokens.get(int(resource_id)) if resource_id is not None else None,
                "start_at": item.get("start_at") or "",
                "end_at": item.get("end_at") or "",
                "occupied_minutes": _number(item.get("occupied_minutes")),
                "quantity": int(item.get("quantity") or 0),
            }
        )
    segment_rows.sort(
        key=lambda item: (
            item["start_at"],
            item["end_at"],
            item["resource"] or "",
            item["quantity"],
        )
    )
    allocation_rows = []
    for item in operation.get("allocations", []):
        resource_id = item.get("production_node_id") or item.get("process_line_id")
        allocation_rows.append(
            {
                "resource": resource_tokens.get(int(resource_id)) if resource_id is not None else None,
                "quantity": int(item.get("quantity") or 0),
                "serial_id": item.get("serial_id") or "",
                "has_batch_key": bool(item.get("batch_key")),
            }
        )
    allocation_rows.sort(
        key=lambda item: (
            item["resource"] or "",
            item["serial_id"],
            item["quantity"],
        )
    )
    resource_rollups = []
    for resource in sorted(
        {
            item["resource"]
            for item in [*segment_rows, *allocation_rows]
            if item["resource"] is not None
        }
    ):
        segments = [item for item in segment_rows if item["resource"] == resource]
        allocations = [item for item in allocation_rows if item["resource"] == resource]
        resource_rollups.append(
            {
                "resource": resource,
                "segment_count": len(segments),
                "occupied_minutes": sum(item["occupied_minutes"] for item in segments),
                "segment_quantity": sum(item["quantity"] for item in segments),
                "allocation_count": len(allocations),
                "allocated_quantity": sum(item["quantity"] for item in allocations),
                "first_start_at": min(
                    (item["start_at"] for item in segments), default=""
                ),
                "last_end_at": max(
                    (item["end_at"] for item in segments), default=""
                ),
                "calendar_days": sorted(
                    {
                        item["start_at"].split(" ", 1)[0]
                        for item in segments
                        if item["start_at"]
                    }
                ),
                "has_batch_keys": bool(allocations)
                and all(item["has_batch_key"] for item in allocations),
                "serial_ids": [
                    item["serial_id"] for item in allocations if item["serial_id"]
                ],
            }
        )
    resource_id = operation.get("production_node_id") or operation.get("process_line_id")
    return {
        "seq_order": int(operation.get("seq_order") or 0),
        "process_name": operation.get("process_name") or operation.get("process_name_snapshot") or "",
        "status": operation.get("status") or "",
        "blocked_code": operation.get("blocked_code") or "",
        "blocked_reason": operation.get("blocked_reason") or operation.get("reason") or "",
        "execution_mode": operation.get("execution_mode") or "internal",
        "quantity": int(operation.get("quantity") or 0),
        "completed_quantity": int(operation.get("completed_quantity_snapshot") or 0),
        "rework_quantity": int(operation.get("rework_quantity_snapshot") or 0),
        "remaining_quantity": int(operation.get("remaining_quantity_snapshot") or 0),
        "route_version_bound": bool(operation.get("route_version_id")),
        "process_version_bound": bool(operation.get("process_version_id")),
        "standard_bound": bool(operation.get("standard_id")),
        "standard_match_scope": operation.get("standard_match_scope") or "",
        "standard_version": int(operation.get("standard_version") or 0),
        "unit_minutes": _number(operation.get("standard_minutes_per_unit")),
        "setup_minutes": _number(operation.get("setup_minutes")),
        "difficulty_factor": _number(operation.get("difficulty_factor") or 1),
        "planned_minutes": _number(operation.get("planned_minutes")),
        "occupied_minutes": _number(operation.get("occupied_minutes")),
        "plan_start": operation.get("plan_start") or "",
        "plan_end": operation.get("plan_end") or "",
        "planned_start_at": operation.get("planned_start_at") or "",
        "planned_end_at": operation.get("planned_end_at") or "",
        "primary_resource": resource_tokens.get(int(resource_id)) if resource_id is not None else None,
        "resource_count": len(
            {
                item["resource"]
                for item in [*segment_rows, *allocation_rows]
                if item["resource"] is not None
            }
        ),
        "locked": bool(operation.get("locked")),
        "segment_count": len(segment_rows),
        "segment_quantity": sum(item["quantity"] for item in segment_rows),
        "allocation_count": len(allocation_rows),
        "allocated_quantity": sum(item["quantity"] for item in allocation_rows),
        "resource_rollups": resource_rollups,
    }


def _schedule_summary(result):
    operations = result.get("operations") or []
    tokens = _resource_tokens(operations)
    risk = result.get("risk") or {}
    replan = result.get("replan_summary") or {}
    summary = {
        "ok": bool(result.get("ok")),
        "status": result.get("status") or "",
        "idempotent_replay": bool(result.get("idempotent_replay")),
        "revision_status": result.get("revision_status") or "",
        "operations": [_operation_summary(item, tokens) for item in operations],
    }
    conflict_codes = sorted(
            item.get("code") or item.get("conflict_type") or "unknown"
            for item in result.get("conflicts") or []
    )
    if conflict_codes:
        summary["conflict_codes"] = conflict_codes
    revision_conflict_codes = sorted(
            item.get("code") or item.get("conflict_type") or "unknown"
            for item in result.get("revision_conflicts") or []
    )
    if revision_conflict_codes:
        summary["revision_conflict_codes"] = revision_conflict_codes
    if risk:
        summary["risk"] = {
            "level": risk.get("risk_level") or risk.get("level") or "none",
            "delay_minutes": int(risk.get("delay_minutes") or 0),
            "reason": risk.get("risk_reason") or risk.get("reason") or "",
        }
    if replan:
        summary["replan"] = {
            "trigger_count": int(replan.get("trigger_count") or 0),
            "changed_operation_count": int(replan.get("changed_operation_count") or 0),
            "node_change_count": int(replan.get("node_change_count") or 0),
            "delayed_operation_count": int(replan.get("delayed_operation_count") or 0),
            "advanced_operation_count": int(replan.get("advanced_operation_count") or 0),
            "before_risk_level": replan.get("before_risk_level") or "none",
            "after_risk_level": replan.get("after_risk_level") or "none",
            "risk_change": replan.get("risk_change") or "unchanged",
            "blocked": bool(replan.get("blocked")),
            "trigger_reasons": replan.get("trigger_reasons") or [],
        }
    return summary


def _assert_baseline(name, summary):
    expected = BASELINE[name]
    assert summary == expected["summary"]
    assert _digest(summary) == expected["sha256"]


def _enable_node_engine(monkeypatch):
    monkeypatch.setattr(config, "PRODUCTION_NODE_QUERY_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_WRITE_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_ENGINE_ENABLED", True)


def _actor_id(db):
    return int(
        db.execute("SELECT id FROM users WHERE username='testrunner'").fetchone()[0]
    )


def _seed_order(
    db,
    process_names,
    *,
    quantity,
    plan_start,
    standard_minutes=None,
    setup_minutes=0,
    difficulty_factor=1,
    deadline=None,
    route_name,
):
    process_rows = [
        db.execute("SELECT id FROM processes WHERE name=?", (name,)).fetchone()
        for name in process_names
    ]
    assert all(process_rows), process_names
    process_ids = [int(row["id"]) for row in process_rows]
    route_id = create_process_route(db, process_ids, name=route_name)
    order_id = create_order(
        db,
        process_ids,
        quantity=quantity,
        product_code=f"CHAR-{route_name.upper().replace(' ', '-')}",
    )
    db.execute(
        "UPDATE orders SET route_id=?,plan_start=?,deadline=?,status='producing' WHERE id=?",
        (route_id, plan_start, deadline, order_id),
    )
    bind_order_process_versions(db, order_id)
    if standard_minutes is not None:
        route_version_id = db.execute(
            "SELECT route_version_id FROM orders WHERE id=?", (order_id,)
        ).fetchone()[0]
        for process_id in process_ids:
            process_version_id = db.execute(
                "SELECT process_version_id FROM order_processes "
                "WHERE order_id=? AND process_id=?",
                (order_id, process_id),
            ).fetchone()[0]
            db.execute(
                "INSERT INTO work_time_standards "
                "(route_id,route_version_id,process_id,process_version_id,"
                "standard_minutes_per_unit,setup_minutes,difficulty_factor,status,version) "
                "VALUES (?,?,?,?,?,?,?,'active',1)",
                (
                    route_id,
                    route_version_id,
                    process_id,
                    process_version_id,
                    standard_minutes,
                    setup_minutes,
                    difficulty_factor,
                ),
            )
    db.commit()
    return order_id


def _activate_first_nodes(db, process_name, count):
    process_id = db.execute(
        "SELECT id FROM processes WHERE name=?", (process_name,)
    ).fetchone()[0]
    nodes = db.execute(
        "SELECT id FROM production_nodes WHERE process_id=? ORDER BY id",
        (process_id,),
    ).fetchall()
    assert len(nodes) >= count
    active_ids = [int(row["id"]) for row in nodes[:count]]
    placeholders = ",".join("?" for _ in active_ids)
    db.execute(
        "UPDATE production_nodes SET status='inactive' WHERE process_id=?",
        (process_id,),
    )
    db.execute(
        f"UPDATE production_nodes SET status='active' WHERE id IN ({placeholders})",
        active_ids,
    )
    db.commit()
    return active_ids


def test_generation_baseline_captures_multi_node_cross_day_risk_and_replay(
    client, monkeypatch
):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        _activate_first_nodes(db, "焊接", 2)
        order_id = _seed_order(
            db,
            ["焊接"],
            quantity=8,
            plan_start="2030-01-07",
            deadline="2030-01-08",
            standard_minutes=300,
            route_name="characterization multi node",
        )
        result = ScheduleCapacityService.generate_order_schedule(
            order_id,
            start_date="2030-01-07",
            schedule_run_key="characterization-generate-v1",
            actor_id=_actor_id(db),
        )
        replay = ScheduleCapacityService.generate_order_schedule(
            order_id,
            start_date="2030-01-07",
            schedule_run_key="characterization-generate-v1",
            actor_id=_actor_id(db),
        )

        summary = {
            "first": _schedule_summary(result),
            "replay": {
                "idempotent_replay": bool(replay["idempotent_replay"]),
                "status": replay["status"],
                "operations_unchanged": (
                    _schedule_summary(replay)["operations"]
                    == _schedule_summary(result)["operations"]
                ),
            },
            "quantity_conserved": (
                _schedule_summary(result)["operations"][0]["allocated_quantity"] == 8
            ),
        }
        _assert_baseline("multi_node_cross_day", summary)


def test_blocking_baseline_captures_missing_work_time_without_fabrication(
    client, monkeypatch
):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        order_id = _seed_order(
            db,
            ["下料", "焊接"],
            quantity=2,
            plan_start="2030-01-07",
            standard_minutes=None,
            route_name="characterization missing standard",
        )
        result = ScheduleCapacityService.generate_order_schedule(
            order_id,
            start_date="2030-01-07",
            schedule_run_key="characterization-blocked-v1",
            actor_id=_actor_id(db),
        )
        _assert_baseline("missing_work_time", _schedule_summary(result))


def test_dynamic_replan_baseline_captures_report_rework_lock_and_replay(
    client, monkeypatch
):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        _activate_first_nodes(db, "下料", 1)
        actor_id = _actor_id(db)
        order_id = _seed_order(
            db,
            ["下料"],
            quantity=10,
            plan_start="2030-01-07",
            standard_minutes=10,
            route_name="characterization dynamic replan",
        )
        initial = ScheduleCapacityService.generate_order_schedule(
            order_id,
            start_date="2030-01-07",
            schedule_run_key="characterization-replan-seed-v1",
            actor_id=actor_id,
        )
        item = db.execute(
            "SELECT * FROM schedule_revision_items WHERE revision_id=?",
            (initial["schedule_revision_id"],),
        ).fetchone()
        ScheduleCapacityService.lock_schedule_item(
            item["id"],
            "characterization locked task",
            "characterization-replan-lock-v1",
            actor_id,
        )
        db.execute(
            "UPDATE order_processes SET completed=4,status='in_progress' WHERE id=?",
            (item["order_process_id"],),
        )
        db.execute(
            "INSERT INTO work_records "
            "(order_id,process_id,user_id,type,status,quantity) "
            "VALUES (?,?,?,'normal','approved',4)",
            (order_id, item["process_id"], actor_id),
        )
        db.execute(
            "INSERT INTO rework_records "
            "(order_id,process_id,user_id,quantity,reason,status) "
            "VALUES (?,?,?,?,?,'pending')",
            (order_id, item["process_id"], actor_id, 2, "characterization rework"),
        )
        db.commit()

        result = ScheduleCapacityService.dynamic_replan_order(
            order_id,
            start_at=item["planned_start_at"],
            schedule_run_key="characterization-replan-v1",
            reason="characterization production facts changed",
            actor_id=actor_id,
        )
        replay = ScheduleCapacityService.dynamic_replan_order(
            order_id,
            start_at=item["planned_start_at"],
            schedule_run_key="characterization-replan-v1",
            reason="characterization production facts changed",
            actor_id=actor_id,
        )
        _assert_baseline(
            "dynamic_replan",
            {
                "first": _schedule_summary(result),
                "replay": {
                    "idempotent_replay": bool(replay["idempotent_replay"]),
                    "status": replay["status"],
                    "operations_unchanged": (
                        _schedule_summary(replay)["operations"]
                        == _schedule_summary(result)["operations"]
                    ),
                },
            },
        )


def test_failure_and_publication_baseline_preserves_auditable_state(
    client, monkeypatch
):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        _activate_first_nodes(db, "下料", 1)
        creator_id = _actor_id(db)
        reviewer_id = ensure_user(
            db,
            "characterization-reviewer",
            TEST_HASH,
            "Characterization Reviewer",
            "worker",
            "CHAR-REVIEWER-001",
        )
        order_id = _seed_order(
            db,
            ["下料"],
            quantity=1,
            plan_start="2030-01-07",
            standard_minutes=60,
            route_name="characterization workflow",
        )
        generated = ScheduleCapacityService.generate_order_schedule(
            order_id,
            start_date="2030-01-07",
            schedule_run_key="characterization-workflow-v1",
            actor_id=creator_id,
        )
        revision_id = generated["schedule_revision_id"]
        ScheduleCapacityService.submit_revision(
            revision_id,
            "characterization submit",
            "characterization-submit-v1",
            creator_id,
        )
        ScheduleCapacityService.approve_revision(
            revision_id,
            "characterization independent approval",
            "characterization-approve-v1",
            reviewer_id,
        )
        published = ScheduleCapacityService.publish_revision(
            revision_id,
            "characterization publish",
            "characterization-publish-v1",
            creator_id,
        )
        replay = ScheduleCapacityService.publish_revision(
            revision_id,
            "characterization publish",
            "characterization-publish-v1",
            creator_id,
        )
        immutable = False
        try:
            db.execute(
                "UPDATE schedule_revision_items SET quantity=quantity+1 "
                "WHERE revision_id=?",
                (revision_id,),
            )
        except sqlite3.IntegrityError:
            immutable = True

        events = [
            row["event_type"]
            for row in db.execute(
                "SELECT event_type FROM schedule_node_workflow_events "
                "WHERE revision_id=? ORDER BY id",
                (revision_id,),
            ).fetchall()
        ]
        revision = db.execute(
            "SELECT status,approval_status,content_digest FROM schedule_revisions "
            "WHERE id=?",
            (revision_id,),
        ).fetchone()
        current_revision_id = db.execute(
            "SELECT current_schedule_revision_id FROM orders WHERE id=?",
            (order_id,),
        ).fetchone()[0]

        failed_order_id = _seed_order(
            db,
            ["下料"],
            quantity=1,
            plan_start="2030-01-08",
            standard_minutes=60,
            route_name="characterization failed run",
        )
        real_insert = ScheduleCapacityRepository.insert_operation_schedule

        def fail_insert(*args, **kwargs):
            raise RuntimeError("characterization persistence failure")

        monkeypatch.setattr(
            ScheduleCapacityRepository,
            "insert_operation_schedule",
            fail_insert,
        )
        with pytest.raises(ValueError, match="characterization persistence failure"):
            ScheduleCapacityService.generate_order_schedule(
                failed_order_id,
                start_date="2030-01-08",
                schedule_run_key="characterization-failed-v1",
                actor_id=creator_id,
            )
        monkeypatch.setattr(
            ScheduleCapacityRepository,
            "insert_operation_schedule",
            real_insert,
        )
        failed_run = db.execute(
            "SELECT status,error_message FROM schedule_runs "
            "WHERE schedule_run_key='characterization-failed-v1'",
        ).fetchone()
        failed_revision = db.execute(
            "SELECT status FROM schedule_revisions "
            "WHERE source_run_key='characterization-failed-v1'",
        ).fetchone()

        summary = {
            "published": {
                "service_status": published["result"]["status"],
                "approval_status": published["result"]["approval_status"],
                "event_types": events,
                "revision_status": revision["status"],
                "revision_approval_status": revision["approval_status"],
                "content_digest_present": len(revision["content_digest"] or "") == 64,
                "current_pointer_matches": current_revision_id == revision_id,
                "immutable_items": immutable,
                "publish_replay": bool(replay["idempotent_replay"]),
            },
            "failed": {
                "run_status": failed_run["status"],
                "error": failed_run["error_message"],
                "revision_status": failed_revision["status"],
            },
        }
        _assert_baseline("failure_and_publication", summary)
