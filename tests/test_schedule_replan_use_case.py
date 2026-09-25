import inspect

import pytest

from factories import create_process_route
from modules import config
from modules.db import get_db
from modules.repositories.schedule_capacity_repository import ScheduleCapacityRepository
from modules.services.schedule_capacity_service import ScheduleCapacityService
from modules.services.schedule_replan_service import ScheduleReplanService


@pytest.fixture(autouse=True)
def enable_dynamic_replan(monkeypatch):
    monkeypatch.setattr(config, "PRODUCTION_NODE_QUERY_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_WRITE_ENABLED", True)


def _seed_order(db, process_id, quantity=3):
    route_id = create_process_route(db, [process_id], name="Task 4 replan route")
    order_id = db.execute(
        "INSERT INTO orders "
        "(order_no,product_name,product_code,quantity,status,plan_start,route_id) "
        "VALUES ('TASK4-REPLAN','Task 4 product','TASK4',?, 'producing','2026-09-01',?)",
        (quantity, route_id),
    ).lastrowid
    db.execute(
        "INSERT INTO order_processes (order_id,process_id,seq_order,status) "
        "VALUES (?,?,1,'in_progress')",
        (order_id, process_id),
    )
    route_version = db.execute(
        "SELECT current_effective_version_id FROM process_routes WHERE id=?",
        (route_id,),
    ).fetchone()[0]
    process_version = db.execute(
        "SELECT process_version_id FROM process_route_version_items "
        "WHERE route_version_id=? AND process_id=?",
        (route_version, process_id),
    ).fetchone()[0]
    db.execute(
        "INSERT INTO work_time_standards "
        "(route_id,route_version_id,process_id,process_version_id,"
        "standard_minutes_per_unit,setup_minutes,difficulty_factor,status,version) "
        "VALUES (?,?,?,?,10,0,1,'active',1)",
        (route_id, route_version, process_id, process_version),
    )
    db.commit()
    return order_id


def test_task4_entrypoint_is_split_into_explicit_phases():
    phase_names = (
        "_prepare_request",
        "_load_replan_facts",
        "_replay_existing_run",
        "_create_replan_ledger",
        "_load_replan_occupancy",
        "_restore_locked_task",
        "_plan_replan_operations",
        "_finalize_replan",
        "_fail_replan",
    )
    assert all(callable(getattr(ScheduleReplanService, name)) for name in phase_names)
    source = inspect.getsource(ScheduleReplanService.dynamic_replan_order)
    for name in phase_names:
        assert f"ScheduleReplanService.{name}" in source or name == "_restore_locked_task"
    assert "SAVEPOINT dynamic_schedule_replan" in source


def test_evidence_failure_keeps_failed_ledger_and_old_projection(client, monkeypatch):
    with client.application.app_context():
        db = get_db()
        process_id = db.execute(
            "SELECT id FROM processes WHERE name='下料'"
        ).fetchone()["id"]
        order_id = _seed_order(db, process_id)
        initial = ScheduleCapacityService.generate_order_schedule(
            order_id,
            start_date="2026-09-01",
            schedule_run_key="task4-initial",
        )
        before_projection = [
            tuple(row)
            for row in db.execute(
                "SELECT quantity,planned_start_at,planned_end_at,production_node_id "
                "FROM order_process_schedules WHERE order_id=? ORDER BY id",
                (order_id,),
            ).fetchall()
        ]

        def fail_evidence(*args, **kwargs):
            raise RuntimeError("task4 evidence persistence failure")

        monkeypatch.setattr(
            ScheduleCapacityRepository,
            "save_replan_evidence",
            fail_evidence,
        )
        with pytest.raises(ValueError, match="task4 evidence persistence failure"):
            ScheduleCapacityService.dynamic_replan_order(
                order_id,
                start_at="2026-09-02 08:00",
                schedule_run_key="task4-evidence-failure",
                reason="验证证据原子性",
            )

        after_projection = [
            tuple(row)
            for row in db.execute(
                "SELECT quantity,planned_start_at,planned_end_at,production_node_id "
                "FROM order_process_schedules WHERE order_id=? ORDER BY id",
                (order_id,),
            ).fetchall()
        ]
        failed_run = db.execute(
            "SELECT status,error_message FROM schedule_runs "
            "WHERE schedule_run_key='task4-evidence-failure'"
        ).fetchone()
        failed_revision = db.execute(
            "SELECT status FROM schedule_revisions "
            "WHERE source_run_key='task4-evidence-failure'"
        ).fetchone()
        assert after_projection == before_projection
        assert failed_run["status"] == "failed"
        assert "task4 evidence persistence failure" in failed_run["error_message"]
        assert failed_revision["status"] == "cancelled"
        assert db.execute(
            "SELECT current_schedule_revision_id FROM orders WHERE id=?",
            (order_id,),
        ).fetchone()[0] is None
