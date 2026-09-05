import uuid

import pytest

from factories import create_process_route
from modules.db import get_db
from modules.services.schedule_capacity_service import ScheduleCapacityService


def _seed_order(db, process_id, quantity=10):
    suffix = uuid.uuid4().hex[:8].upper()
    route_id = create_process_route(db, [process_id], name=f"Dynamic Route {suffix}")
    order_id = db.execute(
        "INSERT INTO orders (order_no,product_name,product_code,quantity,status,plan_start,route_id) "
        "VALUES (?, 'Dynamic Product', ?, ?, 'producing', '2026-09-01', ?)",
        (f"DYN-{suffix}", f"DYN-CODE-{suffix}", quantity, route_id),
    ).lastrowid
    db.execute(
        "INSERT INTO order_processes (order_id,process_id,seq_order,status) VALUES (?,?,1,'in_progress')",
        (order_id, process_id),
    )
    route_version = db.execute(
        "SELECT current_effective_version_id FROM process_routes WHERE id=?", (route_id,)
    ).fetchone()[0]
    process_version = db.execute(
        "SELECT process_version_id FROM process_route_version_items WHERE route_version_id=? AND process_id=?",
        (route_version, process_id),
    ).fetchone()[0]
    db.execute(
        "INSERT INTO work_time_standards (route_id,route_version_id,process_id,process_version_id,"
        "standard_minutes_per_unit,setup_minutes,difficulty_factor,status,version) "
        "VALUES (?,?,?,?,10,0,1,'active',1)",
        (route_id, route_version, process_id, process_version),
    )
    db.commit()
    return order_id, route_id


def test_dynamic_replan_uses_completed_and_open_rework_quantities(client):
    with client.application.app_context():
        db = get_db()
        process_id = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        order_id, _ = _seed_order(db, process_id, quantity=10)
        user_id = db.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()[0]
        db.execute(
            "UPDATE order_processes SET completed=4,status='in_progress' WHERE order_id=? AND process_id=?",
            (order_id, process_id),
        )
        db.execute(
            "INSERT INTO work_records (order_id,process_id,user_id,type,status,quantity) VALUES (?,?,?,'normal','approved',4)",
            (order_id, process_id, user_id),
        )
        db.execute(
            "INSERT INTO rework_records (order_id,process_id,user_id,quantity,reason,status) VALUES (?,?,?,2,'尺寸返工','pending')",
            (order_id, process_id, user_id),
        )
        db.commit()
        result = ScheduleCapacityService.dynamic_replan_order(
            order_id,
            start_at="2026-09-01 08:00",
            schedule_run_key="dynamic-baseline-v1",
            reason="报工进度和返工需求变化",
            actor_id=user_id,
        )
        operation = result["operations"][0]
        assert operation["quantity"] == 8
        assert operation["completed_quantity_snapshot"] == 4
        assert operation["rework_quantity_snapshot"] == 2
        assert result["input_digest"]
        run = db.execute(
            "SELECT run_type,trigger_source,input_digest,replan_reason FROM schedule_runs WHERE schedule_run_key=?",
            ("dynamic-baseline-v1",),
        ).fetchone()
        assert dict(run) == {
            "run_type": "dynamic_replan",
            "trigger_source": "production_facts",
            "input_digest": result["input_digest"],
            "replan_reason": "报工进度和返工需求变化",
        }


def test_dynamic_replan_treats_downtime_as_line_occupancy_and_is_idempotent(client):
    with client.application.app_context():
        db = get_db()
        process_id = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        order_id, _ = _seed_order(db, process_id, quantity=2)
        user_id = db.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()[0]
        line_id = db.execute(
            "SELECT id FROM process_production_lines WHERE process_id=? ORDER BY id LIMIT 1", (process_id,)
        ).fetchone()[0]
        ScheduleCapacityService.create_downtime_event(
            line_id, "2026-09-01 08:00", "2026-09-01 17:00", "设备检修", created_by=user_id
        )
        first = ScheduleCapacityService.dynamic_replan_order(
            order_id, start_at="2026-09-01 08:00", schedule_run_key="dynamic-downtime-v1", actor_id=user_id
        )
        assert first["operations"][0]["planned_start_at"].startswith("2026-09-02")
        replay = ScheduleCapacityService.dynamic_replan_order(
            order_id, start_at="2026-09-01 08:00", schedule_run_key="dynamic-downtime-v1", actor_id=user_id
        )
        assert replay["idempotent_replay"] is True
        assert replay["input_digest"] == first["input_digest"]
        assert replay["operations"] == first["operations"]


def test_dynamic_replan_keeps_the_previous_revision_and_carries_completed_fact(client):
    with client.application.app_context():
        db = get_db()
        process_id = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        order_id, _ = _seed_order(db, process_id, quantity=5)
        initial = ScheduleCapacityService.generate_order_schedule(
            order_id, start_date="2026-09-01", schedule_run_key="dynamic-history-initial"
        )
        user_id = db.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()[0]
        db.execute("UPDATE order_processes SET completed=2,status='in_progress' WHERE order_id=?", (order_id,))
        db.execute(
            "INSERT INTO work_records (order_id,process_id,user_id,type,status,quantity) VALUES (?,?,?,'normal','approved',2)",
            (order_id, process_id, user_id),
        )
        db.commit()
        replanned = ScheduleCapacityService.dynamic_replan_order(
            order_id, start_at="2026-09-02 08:00", schedule_run_key="dynamic-history-replan", reason="报工推进", actor_id=user_id
        )
        revisions = db.execute(
            "SELECT r.id,r.status,sr.run_type,r.replan_reason FROM schedule_revisions r "
            "LEFT JOIN schedule_runs sr ON sr.id=r.schedule_run_id WHERE r.order_id=? ORDER BY r.revision_no",
            (order_id,),
        ).fetchall()
        assert len(revisions) == 2
        assert revisions[0]["status"] == "draft"
        assert revisions[1]["run_type"] == "dynamic_replan"
        assert revisions[1]["replan_reason"] == "报工推进"
        assert replanned["operations"][0]["quantity"] == 3
        assert db.execute(
            "SELECT COUNT(*) FROM schedule_revision_items WHERE revision_id=?", (initial["schedule_revision_id"],)
        ).fetchone()[0] == 1


@pytest.mark.parametrize("start_at", ["bad timestamp", "2026/09/01"])
def test_dynamic_replan_rejects_invalid_start_time(client, start_at):
    with client.application.app_context():
        db = get_db()
        process_id = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        order_id, _ = _seed_order(db, process_id)
        with pytest.raises(ValueError):
            ScheduleCapacityService.dynamic_replan_order(
                order_id, start_at=start_at, schedule_run_key=f"dynamic-invalid-{uuid.uuid4().hex}"
            )


def test_dynamic_replan_and_downtime_api_contract(client, auth_headers):
    with client.application.app_context():
        db = get_db()
        process_id = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        order_id, _ = _seed_order(db, process_id, quantity=1)
        line_id = db.execute(
            "SELECT id FROM process_production_lines WHERE process_id=? ORDER BY id LIMIT 1", (process_id,)
        ).fetchone()[0]
    event = client.post(
        "/api/schedule/downtime",
        json={"process_line_id": line_id, "start_at": "2026-09-01 08:00", "end_at": "2026-09-01 09:00", "reason": "换刀"},
        headers=auth_headers,
    )
    assert event.status_code == 200, event.get_json()
    listed = client.get("/api/schedule/downtime?limit=10", headers=auth_headers)
    assert listed.status_code == 200
    assert listed.get_json()["events"][0]["reason"] == "换刀"
    replanned = client.post(
        f"/api/schedule/order/{order_id}/dynamic-replan",
        json={"start_at": "2026-09-01 08:00", "schedule_run_key": "dynamic-api-v1", "reason": "停机后重排"},
        headers=auth_headers,
    )
    assert replanned.status_code == 200, replanned.get_json()
    assert replanned.get_json()["operations"][0]["quantity"] == 1
