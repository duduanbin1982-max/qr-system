import sqlite3

from modules.services.schedule_capacity_service import ScheduleCapacityService
from scripts.validate_production_scheduling_v094_final_acceptance import (
    _historical_replay,
    build_acceptance,
    summarize_historical_replays,
)


def _passing_acceptance_inputs():
    return {
        "source_replica_unchanged": True,
        "quick_check": "ok",
        "foreign_key_violations": 0,
        "after_version": 94,
        "active_count": 2,
        "queue_count": 2,
        "batch_queue_count": 2,
        "operation_metrics": {
            "order_result_counts": {"success": 2},
            "quantity_conservation_violation_count": 0,
            "serial_split_violation_count": 0,
        },
        "conflict_metrics": {
            "batch_internal_conflict_count": 0,
            "batch_to_existing_conflict_count": 0,
        },
        "node_metrics": {
            "configured_counts_ok": True,
            "all_configured_nodes_exercised": True,
            "multi_node_splits_exercised": True,
        },
        "calendar_metrics": {
            "cross_shift_operation_count": 1,
            "cross_day_operation_count": 1,
            "weekend_spanning_operation_count": 1,
            "weekend_segment_count": 0,
            "invalid_segment_count": 0,
        },
        "external_metrics": {
            "external_operation_count": 1,
            "capacity_violation_count": 0,
        },
        "execution_facts_unchanged": True,
        "historical_metrics": {
            "selected_order_count": 1,
            "failed_order_count": 0,
            "quantity_conservation_violation_count": 0,
            "conflict_count": 0,
        },
        "latest_compat_mismatches": 0,
    }


def test_summarize_historical_replays_reports_failures_and_ratios():
    summary = summarize_historical_replays([
        {
            "ok": True,
            "operation_count": 7,
            "blocked_operation_count": 0,
            "quantity_conservation_violation_count": 0,
            "conflict_count": 0,
            "actual_deadline_met": True,
            "projected_deadline_met": True,
            "calendar_span_ratio": 0.25,
        },
        {
            "ok": False,
            "operation_count": 7,
            "blocked_operation_count": 1,
            "blocked_codes": {"MISSING_STANDARD": 1},
            "quantity_conservation_violation_count": 1,
            "conflict_count": 2,
            "actual_deadline_met": False,
            "projected_deadline_met": False,
            "calendar_span_ratio": 0.75,
            "error": "replay failed",
        },
    ])

    assert summary["selected_order_count"] == 2
    assert summary["successful_order_count"] == 1
    assert summary["failed_order_count"] == 1
    assert summary["operation_count"] == 14
    assert summary["blocked_codes"] == {
        "MISSING_STANDARD": 1,
        "REPLAY_ERROR": 1,
    }
    assert summary["median_planned_to_actual_calendar_span_ratio"] == 0.5


def test_acceptance_rejects_blocked_orders_and_conflicts():
    inputs = _passing_acceptance_inputs()
    assert all(build_acceptance(**inputs).values())

    inputs["operation_metrics"] = {
        **inputs["operation_metrics"],
        "order_result_counts": {"success": 1, "blocked": 1},
    }
    inputs["conflict_metrics"] = {
        "batch_internal_conflict_count": 1,
        "batch_to_existing_conflict_count": 0,
    }
    acceptance = build_acceptance(**inputs)

    assert acceptance["active_orders_all_succeeded"] is False
    assert acceptance["active_orders_blocked_zero"] is False
    assert acceptance["node_conflicts_zero"] is False


def test_historical_replay_rolls_back_temporary_order_state(monkeypatch):
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            order_no TEXT,
            status TEXT,
            quantity INTEGER,
            completed INTEGER,
            current_schedule_revision_id INTEGER,
            plan_start TEXT,
            plan_end TEXT,
            deadline TEXT
        );
        CREATE TABLE processes (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE order_processes (
            id INTEGER PRIMARY KEY,
            order_id INTEGER,
            process_id INTEGER,
            seq_order INTEGER,
            completed INTEGER,
            scrapped INTEGER,
            rework INTEGER,
            status TEXT
        );
        CREATE TABLE work_records (
            id INTEGER PRIMARY KEY,
            order_id INTEGER,
            process_id INTEGER,
            status TEXT,
            quantity INTEGER,
            created_at TEXT
        );
        INSERT INTO orders VALUES (
            1,'HIST-001','completed',5,5,42,'2026-09-01','2026-09-02','2026-09-10'
        );
        INSERT INTO processes VALUES (10,'焊接');
        INSERT INTO order_processes VALUES (100,1,10,1,5,0,0,'completed');
        INSERT INTO work_records VALUES (
            1000,1,10,'approved',5,'2026-09-02 08:00:00'
        );
        """
    )

    def fake_generate_order_schedule(order_id, **kwargs):
        changed = db.execute(
            "SELECT status,completed,current_schedule_revision_id FROM orders WHERE id=?",
            (order_id,),
        ).fetchone()
        assert tuple(changed) == ("pending", 0, None)
        return {
            "operations": [{
                "order_process_id": 100,
                "process_id": 10,
                "process_name": "焊接",
                "status": "planned",
                "quantity": 5,
                "occupied_minutes": 300,
                "planned_start_at": "2026-09-02 08:00:00",
                "planned_end_at": "2026-09-02 13:00:00",
                "allocations": [{"production_node_id": 7, "quantity": 5}],
            }],
            "conflicts": [],
        }

    monkeypatch.setattr(
        ScheduleCapacityService,
        "generate_order_schedule",
        staticmethod(fake_generate_order_schedule),
    )
    replay = _historical_replay(
        db,
        {
            "id": 1,
            "order_no": "HIST-001",
            "quantity": 5,
            "plan_start": "2026-09-01",
            "deadline": "2026-09-10",
            "actual_start_at": "2026-09-02 08:00:00",
            "actual_end_at": "2026-09-02 08:00:00",
        },
        actor_id=1,
        index=1,
    )

    assert replay["ok"] is True
    assert replay["quantity_conservation_violation_count"] == 0
    restored_order = db.execute(
        "SELECT status,completed,current_schedule_revision_id,plan_start,plan_end "
        "FROM orders WHERE id=1"
    ).fetchone()
    restored_operation = db.execute(
        "SELECT completed,scrapped,rework,status FROM order_processes WHERE id=100"
    ).fetchone()
    assert tuple(restored_order) == (
        "completed", 5, 42, "2026-09-01", "2026-09-02"
    )
    assert tuple(restored_operation) == (5, 0, 0, "completed")
    db.close()
