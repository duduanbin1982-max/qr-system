import sqlite3

import pytest

from factories import create_process_route, ensure_process
from modules.db import get_db
from modules.services.schedule_capacity_service import ScheduleCapacityService
from modules.services.work_time_service import WorkTimeService
from scripts import repair_schedule_standard_bindings as repair


def _add_route_version(db, route_id, process_ids, version=2, status="published"):
    root = db.execute("SELECT * FROM process_routes WHERE id=?", (route_id,)).fetchone()
    version_id = db.execute(
        "INSERT INTO process_route_versions "
        "(process_route_id,version,route_code_snapshot,name,category,description,status) "
        "VALUES (?,?,?,?,?,?,'draft')",
        (route_id, version, root["route_code"], root["name"], root["category"], root["description"]),
    ).lastrowid
    for seq, process_id in enumerate(process_ids, start=1):
        process_version_id = db.execute(
            "SELECT current_effective_version_id FROM processes WHERE id=?", (process_id,)
        ).fetchone()[0]
        db.execute(
            "INSERT INTO process_route_version_items "
            "(route_version_id,process_id,process_version_id,seq_order) VALUES (?,?,?,?)",
            (version_id, process_id, process_version_id, seq),
        )
    db.execute(
        "UPDATE process_route_versions SET status=? WHERE id=?",
        (status, version_id),
    )
    db.commit()
    return version_id


def _seed_order(db, route_id, process_id, route_version_id):
    order_id = db.execute(
        "INSERT INTO orders (order_no,product_name,product_code,quantity,status,plan_start,route_id,route_version_id) "
        "VALUES ('V085-EXT-1','V085 Product','V085-P',10,'pending','2026-09-15',?,?)",
        (route_id, route_version_id),
    ).lastrowid
    process_version_id = db.execute(
        "SELECT process_version_id FROM process_route_version_items "
        "WHERE route_version_id=? AND process_id=?", (route_version_id, process_id)
    ).fetchone()[0]
    version = db.execute(
        "SELECT process_code_snapshot,name,category FROM process_versions WHERE id=?", (process_version_id,)
    ).fetchone()
    db.execute(
        "INSERT INTO order_processes "
        "(order_id,process_id,seq_order,status,process_version_id,process_code_snapshot,"
        "process_name_snapshot,process_category_snapshot) VALUES (?, ?, 1, 'pending', ?, ?, ?, ?)",
        (order_id, process_id, process_version_id, version["process_code_snapshot"],
         version["name"], version["category"]),
    )
    db.commit()
    return order_id, process_version_id


def test_v085_declares_the_exact_approved_19_row_manifest():
    assert sum(len(item["source_standard_ids"]) for item in repair.APPROVED_BINDINGS) == 19
    assert {item["target_route_version_id"] for item in repair.APPROVED_BINDINGS} == {53, 60, 69}


def test_explicit_standard_binding_does_not_follow_current_route_version(client):
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, "V085精确绑定工序")
        route_id = create_process_route(db, [process_id], name="V085精确绑定路线")
        current_route_version_id = db.execute(
            "SELECT current_effective_version_id FROM process_routes WHERE id=?", (route_id,)
        ).fetchone()[0]
        target_route_version_id = _add_route_version(db, route_id, [process_id], status="superseded")
        target_process_version_id = db.execute(
            "SELECT process_version_id FROM process_route_version_items "
            "WHERE route_version_id=? AND process_id=?", (target_route_version_id, process_id)
        ).fetchone()[0]

        standard_id = WorkTimeService.create_standard({
            "route_id": route_id,
            "process_id": process_id,
            "route_version_id": target_route_version_id,
            "process_version_id": target_process_version_id,
            "standard_minutes_per_unit": 12.5,
            "effective_from": "2026-06-01",
        }, user_id=None)
        stored = db.execute(
            "SELECT route_version_id,process_version_id,version_binding_source "
            "FROM work_time_standards WHERE id=?", (standard_id,)
        ).fetchone()
        assert stored["route_version_id"] == target_route_version_id
        assert stored["route_version_id"] != current_route_version_id
        assert stored["process_version_id"] == target_process_version_id
        assert stored["version_binding_source"] == "captured"


def test_controlled_copy_is_idempotent_preserves_source_and_blocks_conflict(client, monkeypatch):
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, "V085复制工序")
        route_id = create_process_route(db, [process_id], name="V085复制路线")
        source_route_version_id = db.execute(
            "SELECT current_effective_version_id FROM process_routes WHERE id=?", (route_id,)
        ).fetchone()[0]
        source_process_version_id = db.execute(
            "SELECT process_version_id FROM process_route_version_items "
            "WHERE route_version_id=? AND process_id=?", (source_route_version_id, process_id)
        ).fetchone()[0]
        target_route_version_id = _add_route_version(db, route_id, [process_id], status="superseded")
        source_standard_id = db.execute(
            "INSERT INTO work_time_standards "
            "(route_id,route_version_id,process_id,process_version_id,standard_minutes_per_unit,"
            "setup_minutes,difficulty_factor,effective_from,status,version) "
            "VALUES (?,?,?,?,2.5,3,1.2,'2026-06-01','active',1)",
            (route_id, source_route_version_id, process_id, source_process_version_id),
        ).lastrowid
        db.commit()
        monkeypatch.setattr(repair, "APPROVED_BINDINGS", ({
            "target_route_version_id": target_route_version_id,
            "source_standard_ids": (source_standard_id,),
        },))

        before = dict(db.execute("SELECT * FROM work_time_standards WHERE id=?", (source_standard_id,)).fetchone())
        plan = repair.build_plan(db, "v085-copy-test", None, None)
        assert plan[0]["status"] == "planned"
        repair.apply_plan(db, plan)
        db.commit()
        target_id = plan[0]["target_standard_id"]
        after = dict(db.execute("SELECT * FROM work_time_standards WHERE id=?", (source_standard_id,)).fetchone())
        assert after == before
        assert db.execute("SELECT route_version_id FROM work_time_standards WHERE id=?", (target_id,)).fetchone()[0] == target_route_version_id

        replay = repair.build_plan(db, "v085-copy-test", None, None)
        assert replay[0]["status"] == "applied"
        assert replay[0]["reason"] == "幂等重放"
        assert db.execute(
            "SELECT COUNT(*) FROM work_time_standards WHERE route_version_id=? AND process_id=?",
            (target_route_version_id, process_id),
        ).fetchone()[0] == 1

        identical = repair.build_plan(db, "v085-copy-test-2", None, None)
        assert identical[0]["status"] == "skipped"
        db.execute("UPDATE work_time_standards SET standard_minutes_per_unit=99 WHERE id=?", (target_id,))
        db.commit()
        conflict = repair.build_plan(db, "v085-copy-test-3", None, None)
        assert conflict[0]["status"] == "blocked"
        assert "有效期重叠" in conflict[0]["reason"]


def test_non_scheduled_policy_does_not_require_standard_or_internal_line(client):
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, "V085外协非排程工序")
        route_id = create_process_route(db, [process_id], name="V085外协路线")
        route_version_id = db.execute(
            "SELECT current_effective_version_id FROM process_routes WHERE id=?", (route_id,)
        ).fetchone()[0]
        order_id, process_version_id = _seed_order(db, route_id, process_id, route_version_id)
        db.execute(
            "INSERT INTO route_process_execution_policies "
            "(route_version_id,process_version_id,process_id,execution_mode,reason) "
            "VALUES (?,?,?,'non_scheduled','pytest approved external process')",
            (route_version_id, process_version_id, process_id),
        )
        db.commit()

        result = ScheduleCapacityService.generate_order_schedule(
            order_id, start_date="2026-09-15", schedule_run_key="v085-non-scheduled"
        )
        operation = result["operations"][0]
        assert operation["status"] == "planned"
        assert operation["execution_mode"] == "non_scheduled"
        assert operation["process_line_id"] is None
        assert operation["standard_id"] is None
        assert operation["occupied_minutes"] == pytest.approx(0)
        stored = db.execute(
            "SELECT execution_mode,status,process_line_id,occupied_minutes FROM order_process_schedules "
            "WHERE order_id=?", (order_id,)
        ).fetchone()
        assert dict(stored) == {
            "execution_mode": "non_scheduled",
            "status": "planned",
            "process_line_id": None,
            "occupied_minutes": 0.0,
        }
