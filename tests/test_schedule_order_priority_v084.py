"""Priority queue and automatic-plan ledger coverage for V084."""

import uuid

import pytest

from factories import create_process_route
from modules.db import get_db
from modules.domain.schedule_order_priority import ScheduleOrderPriorityPolicy
from modules.repositories.schedule_capacity_repository import ScheduleCapacityRepository
from modules.services.schedule_capacity_service import ScheduleCapacityService


def _seed_order(db, process_id, route_id, *, priority=3, expedited=False,
                order_no=None, status="pending", deadline=""):
    suffix = uuid.uuid4().hex[:10].upper()
    order_no = order_no or f"AUTO-{suffix}"
    order_id = db.execute(
        "INSERT INTO orders (order_no,product_name,product_code,quantity,status,"
        "plan_start,deadline,route_id,priority_level,is_expedited,"
        "previous_priority_level,previous_is_expedited,schedule_policy,priority_version) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (order_no, "Auto Product", f"AUTO-CODE-{suffix}", 2, status,
         "2026-09-14", deadline, route_id, priority, int(expedited),
         priority, int(expedited), "auto", 1),
    ).lastrowid
    db.execute(
        "INSERT INTO order_processes (order_id,process_id,seq_order,status) "
        "VALUES (?,?,1,'pending')",
        (order_id, process_id),
    )
    return order_id


def _seed_route_and_standard(db, process_id, name="Auto Priority Route"):
    route_id = create_process_route(db, [process_id], name=name)
    route_version_id = db.execute(
        "SELECT current_effective_version_id FROM process_routes WHERE id=?",
        (route_id,),
    ).fetchone()[0]
    process_version_id = db.execute(
        "SELECT process_version_id FROM process_route_version_items "
        "WHERE route_version_id=? AND process_id=?",
        (route_version_id, process_id),
    ).fetchone()[0]
    db.execute(
        "INSERT INTO work_time_standards (route_id,route_version_id,process_id,"
        "process_version_id,standard_minutes_per_unit,setup_minutes,difficulty_factor,"
        "status,version) VALUES (?,?,?,?,?,0,1,'active',1)",
        (route_id, route_version_id, process_id, process_version_id, 1),
    )
    db.commit()
    return route_id


def test_future_priority_and_expedited_intent_use_previous_value():
    order = {
        "priority_level": 1,
        "is_expedited": 1,
        "previous_priority_level": 3,
        "previous_is_expedited": 0,
        "priority_effective_at": "2099-01-01 00:00:00",
    }
    intent = ScheduleOrderPriorityPolicy.effective_intent(order, now=ScheduleCapacityService._parse_timestamp("2026-09-13"))
    assert intent["priority_level"] == 3
    assert intent["is_expedited"] is False
    assert intent["pending_effective_change"] is True


def test_missing_previous_intent_falls_back_to_current_value():
    intent = ScheduleOrderPriorityPolicy.effective_intent({
        "priority_level": 2,
        "is_expedited": 1,
        "priority_effective_at": "2099-01-01 00:00:00",
    }, now=ScheduleCapacityService._parse_timestamp("2026-09-13"))
    assert intent["priority_level"] == 2
    assert intent["is_expedited"] is True


def test_priority_queue_orders_priority_expedited_deadline_and_excludes_paused_p5(client):
    with client.application.app_context():
        db = get_db()
        process_id = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()[0]
        route_id = _seed_route_and_standard(db, process_id, "Priority Queue Route")
        p2_late = _seed_order(db, process_id, route_id, priority=2, deadline="2026-09-20")
        p1 = _seed_order(db, process_id, route_id, priority=1, deadline="2026-09-20")
        p2_expedited = _seed_order(db, process_id, route_id, priority=2, expedited=True, deadline="2026-09-25")
        p2_early = _seed_order(db, process_id, route_id, priority=2, deadline="2026-09-15")
        _seed_order(db, process_id, route_id, priority=5)
        _seed_order(db, process_id, route_id, priority=2, status="paused")
        orders = ScheduleCapacityRepository.list_schedulable_orders(limit=100, db=db)
        ids = [item["id"] for item in orders if item["id"] in {p1, p2_expedited, p2_early, p2_late}]
        assert ids == [p1, p2_expedited, p2_early, p2_late]


def test_auto_plan_is_idempotent_and_rejects_different_input(client):
    with client.application.app_context():
        db = get_db()
        process_id = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()[0]
        route_id = _seed_route_and_standard(db, process_id, "Auto Plan Idempotency Route")
        first_order = _seed_order(db, process_id, route_id, priority=1)
        second_order = _seed_order(db, process_id, route_id, priority=2)
        db.commit()
        key = "auto-plan-v084-test-001"
        first = ScheduleCapacityService.auto_plan_orders(
            start_date="2026-09-14", auto_plan_key=key, limit=100, actor_id=1,
        )
        assert first["status"] == "completed"
        assert [item["order_id"] for item in first["orders"]] == [first_order, second_order]
        replay = ScheduleCapacityService.auto_plan_orders(
            start_date="2026-09-14", auto_plan_key=key, limit=100, actor_id=1,
        )
        assert replay["idempotent_replay"] is True
        assert replay["orders"] == first["orders"]
        with pytest.raises(ValueError, match="不同输入"):
            ScheduleCapacityService.auto_plan_orders(
                start_date="2026-09-15", auto_plan_key=key, limit=100, actor_id=1,
            )
        ledger = db.execute(
            "SELECT status,created_by,result_digest,error_message FROM schedule_auto_plan_runs "
            "WHERE auto_plan_key=?", (key,)
        ).fetchone()
        assert tuple(ledger) == ("completed", 1, ledger["result_digest"], "")
        assert len(ledger["result_digest"]) == 64


def test_auto_plan_validates_key_and_limit(client):
    with client.application.app_context():
        with pytest.raises(ValueError, match="幂等键"):
            ScheduleCapacityService.auto_plan_orders(auto_plan_key="", limit=100)
        with pytest.raises(ValueError, match="limit"):
            ScheduleCapacityService.auto_plan_orders(auto_plan_key="auto-limit", limit=0)


def test_auto_plan_api_requires_edit_permission_and_returns_result(client, auth_headers):
    response = client.post(
        "/api/schedule/auto-plan",
        json={"start_date": "2026-09-14", "auto_plan_key": "api-auto-plan-v084", "limit": 100},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert payload["auto_plan_key"] == "api-auto-plan-v084"
    assert payload["idempotent_replay"] is False
    with client.application.app_context():
        audit = get_db().execute(
            "SELECT target_id,detail FROM audit_logs "
            "WHERE action='auto_plan_schedule' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert audit["target_id"] == 0
    assert "key=api-auto-plan-v084" in audit["detail"]


def test_auto_plan_api_rejects_worker_without_schedule_edit_permission(
    client, worker_auth_headers
):
    response = client.post(
        "/api/schedule/auto-plan",
        json={"start_date": "2026-09-14", "auto_plan_key": "worker-auto-plan-v084", "limit": 100},
        headers=worker_auth_headers,
    )
    assert response.status_code == 403, response.get_json()
