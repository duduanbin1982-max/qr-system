import json
import uuid

import pytest

from factories import bind_order_process_versions, create_order, create_process_route
from modules import config
from modules.db import get_db
from modules.repositories.production_node_repository import ProductionNodeRepository
from modules.services.schedule_capacity_service import ScheduleCapacityService


def _enable_node_engine(monkeypatch):
    monkeypatch.setattr(config, "PRODUCTION_NODE_QUERY_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_WRITE_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_ENGINE_ENABLED", True)


def _actor_id(db):
    return db.execute(
        "SELECT id FROM users WHERE username='testrunner'"
    ).fetchone()[0]


def _seed_node_schedule(
    db,
    *,
    actor_id,
    process_names=("下料",),
    quantity=1,
    unit_minutes=60,
    plan_start="2026-09-21",
):
    processes = [
        db.execute("SELECT id FROM processes WHERE name=?", (name,)).fetchone()
        for name in process_names
    ]
    assert all(processes)
    process_ids = [row["id"] for row in processes]
    route_id = create_process_route(
        db, process_ids, name=f"Node replan {uuid.uuid4().hex[:8]}"
    )
    order_id = create_order(
        db,
        process_ids,
        quantity=quantity,
        product_code=f"NODE-REPLAN-{uuid.uuid4().hex[:8].upper()}",
    )
    db.execute(
        "UPDATE orders SET route_id=?,plan_start=?,status='producing' WHERE id=?",
        (route_id, plan_start, order_id),
    )
    bind_order_process_versions(db, order_id)
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
            "VALUES (?,?,?,?,?,0,1,'active',1)",
            (
                route_id,
                route_version_id,
                process_id,
                process_version_id,
                unit_minutes,
            ),
        )
    db.commit()
    result = ScheduleCapacityService.generate_order_schedule(
        order_id,
        start_date=plan_start,
        schedule_run_key=f"node-replan-seed-{uuid.uuid4().hex}",
        actor_id=actor_id,
    )
    items = [
        dict(row)
        for row in db.execute(
            "SELECT * FROM schedule_revision_items WHERE revision_id=? "
            "ORDER BY seq_order,id",
            (result["schedule_revision_id"],),
        ).fetchall()
    ]
    assert len(items) == len(process_ids)
    return result, items


def test_node_downtime_api_and_legacy_filter_compatibility_observation(
    client, auth_headers, monkeypatch
):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        node = db.execute(
            "SELECT id,legacy_process_line_id FROM production_nodes "
            "WHERE status='active' AND legacy_process_line_id IS NOT NULL "
            "ORDER BY id LIMIT 1"
        ).fetchone()
        assert node
        node_id = node["id"]
        line_id = node["legacy_process_line_id"]

    created = client.post(
        "/api/schedule/downtime",
        json={
            "production_node_id": node_id,
            "start_at": "2026-09-21 08:00",
            "end_at": "2026-09-21 09:00",
            "reason": "节点换刀",
        },
        headers=auth_headers,
    )
    assert created.status_code == 200, created.get_json()
    event = created.get_json()["event"]
    assert event["production_node_id"] == node_id
    assert event["process_line_id"] == line_id

    node_list = client.get(
        f"/api/schedule/downtime?production_node_id={node_id}&limit=10",
        headers=auth_headers,
    )
    assert node_list.status_code == 200
    assert [item["id"] for item in node_list.get_json()["events"]] == [event["id"]]

    legacy_list = client.get(
        f"/api/schedule/downtime?process_line_id={line_id}&limit=10",
        headers=auth_headers,
    )
    assert legacy_list.status_code == 200
    assert [item["id"] for item in legacy_list.get_json()["events"]] == [event["id"]]
    with client.application.app_context():
        observation = get_db().execute(
            "SELECT scope,source_id,mismatch,difference_json FROM "
            "production_node_compatibility_observations "
            "WHERE scope='downtime_legacy_filter' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert observation
        assert observation["source_id"] == line_id
        assert observation["mismatch"] == 0
        difference = json.loads(observation["difference_json"])
        assert difference["legacy_filter_used"] is True
        assert difference["production_node_id"] == node_id


def test_unmapped_node_cannot_create_downtime(client, monkeypatch):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        source = db.execute(
            "SELECT process_id,calendar_id FROM production_nodes ORDER BY id LIMIT 1"
        ).fetchone()
        node_id = db.execute(
            "INSERT INTO production_nodes "
            "(process_id,node_code,node_name,capacity_mode,status,calendar_id) "
            "VALUES (?,?,?,'exclusive','active',?)",
            (
                source["process_id"],
                f"UNMAPPED-{uuid.uuid4().hex[:8]}",
                "未映射节点",
                source["calendar_id"],
            ),
        ).lastrowid
        db.commit()
        with pytest.raises(ValueError, match="Legacy 产线映射"):
            ScheduleCapacityService.create_downtime_event(
                node_id,
                "2026-09-21 08:00",
                "2026-09-21 09:00",
                "不应写入",
                created_by=_actor_id(db),
            )
        assert db.execute(
            "SELECT COUNT(*) FROM schedule_downtime_events "
            "WHERE production_node_id=?",
            (node_id,),
        ).fetchone()[0] == 0


def test_dynamic_replan_preserves_completed_rework_and_locked_task(
    client, monkeypatch
):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        actor_id = _actor_id(db)
        seeded, items = _seed_node_schedule(
            db, actor_id=actor_id, quantity=10, unit_minutes=10
        )
        source_item = items[0]
        source_payload = json.loads(source_item["payload_json"])
        ScheduleCapacityService.lock_schedule_item(
            source_item["id"],
            "保留现场已确认任务",
            "node-replan-preserve-lock",
            actor_id,
        )
        order_process_id = source_item["order_process_id"]
        process_id = source_item["process_id"]
        db.execute(
            "UPDATE order_processes SET completed=4,status='in_progress' WHERE id=?",
            (order_process_id,),
        )
        db.execute(
            "INSERT INTO work_records "
            "(order_id,process_id,user_id,type,status,quantity) "
            "VALUES (?,?,?,'normal','approved',4)",
            (seeded["order_id"], process_id, actor_id),
        )
        db.execute(
            "INSERT INTO rework_records "
            "(order_id,process_id,user_id,quantity,reason,status) "
            "VALUES (?,?,?,?,?,'pending')",
            (seeded["order_id"], process_id, actor_id, 2, "尺寸返工"),
        )
        db.commit()

        result = ScheduleCapacityService.dynamic_replan_order(
            seeded["order_id"],
            start_at=source_item["planned_start_at"],
            schedule_run_key="node-replan-preserve-001",
            reason="报工和返工事实变化",
            actor_id=actor_id,
        )
        operation = result["operations"][0]
        assert result["conflicts"] == []
        assert operation["completed_quantity_snapshot"] == 4
        assert operation["rework_quantity_snapshot"] == 2
        assert operation["remaining_quantity_snapshot"] == 8
        assert operation["quantity"] == 8
        assert operation["production_node_id"] == source_item["production_node_id"]
        assert operation["planned_start_at"] == source_item["planned_start_at"]
        assert operation["planned_end_at"] == source_item["planned_end_at"]
        assert operation["segments"] == ScheduleCapacityService._locked_task_segments(
            source_item, source_payload
        )
        assert operation["locked"] is True
        assert operation["revision_item_id"] != source_item["id"]
        assert result["input_snapshot"]["locked_tasks"] == [
            {
                "revision_item_id": source_item["id"],
                "order_process_id": source_item["order_process_id"],
                "production_node_id": source_item["production_node_id"],
                "planned_start_at": source_item["planned_start_at"],
                "planned_end_at": source_item["planned_end_at"],
            }
        ]
        assert db.execute(
            "SELECT COUNT(*) FROM schedule_node_task_locks "
            "WHERE revision_item_id=? AND status='active'",
            (operation["revision_item_id"],),
        ).fetchone()[0] == 1

        replay = ScheduleCapacityService.dynamic_replan_order(
            seeded["order_id"],
            start_at=source_item["planned_start_at"],
            schedule_run_key="node-replan-preserve-001",
            reason="报工和返工事实变化",
            actor_id=actor_id,
        )
        assert replay["idempotent_replay"] is True
        assert replay["operations"] == result["operations"]
        assert replay["conflicts"] == result["conflicts"]


def test_locked_task_downtime_conflict_blocks_following_operation(
    client, monkeypatch
):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        actor_id = _actor_id(db)
        seeded, items = _seed_node_schedule(
            db,
            actor_id=actor_id,
            process_names=("下料", "铆接"),
            quantity=1,
            unit_minutes=60,
        )
        locked_item = items[0]
        ScheduleCapacityService.lock_schedule_item(
            locked_item["id"],
            "现场固定节点与时间",
            "node-replan-conflict-lock",
            actor_id,
        )
        downtime = ScheduleCapacityService.create_downtime_event(
            locked_item["production_node_id"],
            locked_item["planned_start_at"],
            locked_item["planned_end_at"],
            "临时停机",
            created_by=actor_id,
        )["event"]

        result = ScheduleCapacityService.dynamic_replan_order(
            seeded["order_id"],
            start_at=locked_item["planned_start_at"],
            schedule_run_key="node-replan-conflict-001",
            reason="节点停机后重排",
            actor_id=actor_id,
        )
        first, second = result["operations"]
        assert first["code"] == "LOCKED_TASK_CONFLICT"
        assert first["blocked_code"] == "LOCKED_TASK_CONFLICT"
        assert first["conflict_type"] == "downtime"
        assert first["downtime_event_id"] == downtime["id"]
        assert first["requires_manual_unlock"] is True
        assert first["production_node_id"] == locked_item["production_node_id"]
        assert first["planned_start_at"] == locked_item["planned_start_at"]
        assert first["planned_end_at"] == locked_item["planned_end_at"]
        assert second["status"] == "blocked"
        assert second["blocked_code"] == "PREVIOUS_OPERATION_BLOCKED"
        assert result["conflicts"] == [
            {
                "code": "LOCKED_TASK_CONFLICT",
                "revision_item_id": first["revision_item_id"],
                "source_revision_item_id": locked_item["id"],
                "production_node_id": locked_item["production_node_id"],
                "requires_manual_unlock": True,
                "reason": "锁定任务与生产节点停机时段冲突",
                "conflict_type": "downtime",
                "downtime_event_id": downtime["id"],
            }
        ]

        replay = ScheduleCapacityService.dynamic_replan_order(
            seeded["order_id"],
            start_at=locked_item["planned_start_at"],
            schedule_run_key="node-replan-conflict-001",
            reason="节点停机后重排",
            actor_id=actor_id,
        )
        assert replay["idempotent_replay"] is True
        assert replay["operations"] == result["operations"]
        assert replay["conflicts"] == result["conflicts"]


def test_node_overtime_adds_capacity_outside_normal_shift(client, monkeypatch):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        node = ProductionNodeRepository.find_node(
            db.execute(
                "SELECT id FROM production_nodes WHERE status='active' ORDER BY id LIMIT 1"
            ).fetchone()[0],
            db=db,
        )
        db.execute(
            "INSERT INTO production_node_calendar_overrides "
            "(production_node_id,start_at,end_at,override_type,reason,status,created_by) "
            "VALUES (?,?,?,'overtime',?,'active',?)",
            (
                node["id"],
                "2026-09-21 18:00",
                "2026-09-21 19:00",
                "交期加班",
                _actor_id(db),
            ),
        )
        db.commit()
        segments = ScheduleCapacityService._allocate_on_node(
            db,
            node,
            ScheduleCapacityService._parse_timestamp("2026-09-21 18:00"),
            60,
            {},
        )
        assert segments == [
            {
                "start_at": "2026-09-21 18:00",
                "end_at": "2026-09-21 19:00",
                "occupied_minutes": 60.0,
                "shift_id": None,
                "production_node_id": node["id"],
                "process_line_id": node["legacy_process_line_id"],
            }
        ]
