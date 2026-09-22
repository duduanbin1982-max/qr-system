import json
from datetime import datetime

import pytest

from factories import create_order, create_process_route
from modules import config
from modules.db import get_db
from modules.services.schedule_capacity_service import ScheduleCapacityService


def _enable_node_engine(monkeypatch):
    monkeypatch.setattr(config, "PRODUCTION_NODE_QUERY_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_WRITE_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_ENGINE_ENABLED", True)


def _seed_node_order(db, *, process_name="焊接", quantity=3, unit=60, setup=0,
                     route_name="Exclusive node route", plan_start="2026-09-18"):
    process = db.execute("SELECT id FROM processes WHERE name=?", (process_name,)).fetchone()
    assert process, process_name
    route_id = create_process_route(db, [process["id"]], name=route_name)
    order_id = create_order(
        db, [process["id"]], quantity=quantity,
        product_code=f"NODE-SCHEDULE-{order_id_suffix(route_name)}",
    )
    db.execute("UPDATE orders SET route_id=? WHERE id=?", (route_id, order_id))
    db.execute("UPDATE orders SET plan_start=? WHERE id=?", (plan_start, order_id))
    route_version_id = db.execute(
        "SELECT current_effective_version_id FROM process_routes WHERE id=?", (route_id,)
    ).fetchone()[0]
    process_version_id = db.execute(
        "SELECT process_version_id FROM process_route_version_items "
        "WHERE route_version_id=? AND process_id=?", (route_version_id, process["id"])
    ).fetchone()[0]
    db.execute(
        "INSERT INTO work_time_standards "
        "(route_id,route_version_id,process_id,process_version_id,standard_minutes_per_unit,"
        "setup_minutes,difficulty_factor,status,version) VALUES (?,?,?,?,?,?,?,'active',1)",
        (route_id, route_version_id, process["id"], process_version_id, unit, setup, 1),
    )
    db.commit()
    node = db.execute(
        "SELECT n.*,pl.id AS legacy_line_id FROM production_nodes n "
        "JOIN process_production_lines pl ON pl.id=n.legacy_process_line_id "
        "WHERE n.process_id=? ORDER BY n.id LIMIT 1", (process["id"],)
    ).fetchone()
    assert node
    # Each test isolates one physical node.  The production seed contains
    # several parallel welding nodes, which is correct operationally but would
    # turn a focused exclusive-node assertion into a multi-node split test.
    db.execute(
        "UPDATE production_nodes SET status=CASE WHEN id=? THEN 'active' ELSE 'inactive' END "
        "WHERE process_id=?",
        (node["id"], process["id"]),
    )
    db.commit()
    return order_id, node["id"], node["legacy_line_id"]


def order_id_suffix(value):
    return "".join(ch for ch in str(value) if ch.isalnum())[-10:] or "X"


def test_exclusive_node_schedule_uses_node_id_and_deprecated_line_projection(client, monkeypatch):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        order_id, node_id, legacy_line_id = _seed_node_order(db, quantity=3)
        result = ScheduleCapacityService.generate_order_schedule(
            order_id, start_date="2026-09-18", schedule_run_key="node-exclusive-001",
        )
        operation = result["operations"][0]
        assert operation["production_node_id"] == node_id
        assert operation["process_line_id"] == legacy_line_id
        assert operation["capacity_mode_snapshot"] == "exclusive"
        assert operation["segments"][0]["production_node_id"] == node_id


def test_completed_operation_does_not_enter_empty_node_allocation(client, monkeypatch):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        order_id, _, _ = _seed_node_order(
            db, quantity=3, route_name="Completed node operation"
        )
        db.execute(
            "UPDATE order_processes SET completed=3,status='completed' WHERE order_id=?",
            (order_id,),
        )
        db.commit()

        result = ScheduleCapacityService.generate_order_schedule(
            order_id,
            start_date="2026-09-18",
            schedule_run_key="node-completed-no-empty-min-001",
        )

        operation = result["operations"][0]
        assert operation["status"] == "completed"
        assert operation["blocked_code"] == ""
        assert operation["quantity"] == 0
        assert operation["segments"] == []
        assert operation["reason"] == "已完成，无剩余排程量"


def test_unmapped_node_persists_node_native_segment_without_legacy_line(
    client, monkeypatch,
):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        order_id, mapped_node_id, _ = _seed_node_order(
            db, quantity=2, route_name="Node native segment"
        )
        mapped = db.execute(
            "SELECT process_id,calendar_id FROM production_nodes WHERE id=?",
            (mapped_node_id,),
        ).fetchone()
        db.execute(
            "UPDATE production_nodes SET status='inactive' WHERE process_id=?",
            (mapped["process_id"],),
        )
        node_id = db.execute(
            "INSERT INTO production_nodes "
            "(process_id,node_code,node_name,capacity_mode,status,calendar_id,"
            "legacy_process_line_id) VALUES (?,?,?,'exclusive','active',?,NULL)",
            (mapped["process_id"], "NODE-NATIVE-01", "节点原生01", mapped["calendar_id"]),
        ).lastrowid
        db.commit()

        result = ScheduleCapacityService.generate_order_schedule(
            order_id,
            start_date="2026-09-18",
            schedule_run_key="node-native-segment-001",
        )

        operation = result["operations"][0]
        assert operation["production_node_id"] == node_id
        assert operation["process_line_id"] is None
        assert operation["status"] == "planned"
        segment = db.execute(
            "SELECT process_line_id,production_node_id "
            "FROM order_process_schedule_segments WHERE schedule_id=?",
            (operation["id"],),
        ).fetchone()
        assert tuple(segment) == (None, node_id)


def test_node_schedule_filters_capabilities_and_blocks_without_match(client, monkeypatch):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        order_id, node_id, _ = _seed_node_order(db, quantity=1, route_name="Capability route")
        db.execute(
            "INSERT INTO production_node_capabilities "
            "(production_node_id,product_family,status) VALUES (?,?,'active')",
            (node_id, "only-other-family"),
        )
        db.commit()
        result = ScheduleCapacityService.generate_order_schedule(
            order_id, start_date="2026-09-18", schedule_run_key="node-capability-001",
        )
        operation = result["operations"][0]
        assert operation["status"] == "blocked"
        assert operation["blocked_code"] == "NO_COMPATIBLE_NODE"


def test_node_schedule_spans_calendar_gap_and_preserves_downstream_precedence(client, monkeypatch):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        first = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()[0]
        second = db.execute("SELECT id FROM processes WHERE name='焊接'").fetchone()[0]
        route_id = create_process_route(db, [first, second], name="Node calendar route")
        order_id = create_order(db, [first, second], quantity=1,
                                product_code="NODE-CALENDAR-01")
        db.execute("UPDATE orders SET route_id=? WHERE id=?", (route_id, order_id))
        db.execute("UPDATE orders SET plan_start='2026-09-18' WHERE id=?", (order_id,))
        rv = db.execute("SELECT current_effective_version_id FROM process_routes WHERE id=?", (route_id,)).fetchone()[0]
        pvs = db.execute("SELECT process_id,process_version_id FROM process_route_version_items WHERE route_version_id=?", (rv,)).fetchall()
        for row in pvs:
            db.execute(
                "INSERT INTO work_time_standards "
                "(route_id,route_version_id,process_id,process_version_id,standard_minutes_per_unit,setup_minutes,difficulty_factor,status,version) "
                "VALUES (?,?,?,?,?,?,1,'active',1)",
                (route_id, rv, row["process_id"], row["process_version_id"], 480, 0),
            )
        db.commit()
        result = ScheduleCapacityService.generate_order_schedule(
            order_id, start_date="2026-09-18", schedule_run_key="node-calendar-001",
        )
        rows = result["operations"]
        assert rows[0]["production_node_id"]
        assert rows[0]["planned_end_at"] > rows[0]["planned_start_at"]
        assert rows[1]["planned_start_at"] >= rows[0]["planned_end_at"]


def test_node_schedule_allocation_has_no_overlap_on_same_node(client, monkeypatch):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        order_a, node_id, _ = _seed_node_order(db, quantity=3, route_name="Overlap A")
        order_b, node_b, _ = _seed_node_order(db, quantity=3, route_name="Overlap B")
        assert node_b == node_id
        first = ScheduleCapacityService.generate_order_schedule(
            order_a, start_date="2026-09-18", schedule_run_key="node-overlap-a",
        )
        second = ScheduleCapacityService.generate_order_schedule(
            order_b, start_date="2026-09-18", schedule_run_key="node-overlap-b",
        )
        intervals = []
        for result in (first, second):
            for segment in result["operations"][0].get("segments", []):
                intervals.append((segment["start_at"], segment["end_at"]))
        assert intervals
        for index, first in enumerate(intervals):
            for second in intervals[index + 1:]:
                assert first[1] <= second[0] or second[1] <= first[0]


@pytest.mark.parametrize("error_code", ["MISSING_WORK_TIME_STANDARD", "NO_COMPATIBLE_NODE"])
def test_node_block_errors_are_structured(client, monkeypatch, error_code):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        order_id, node_id, _ = _seed_node_order(db, quantity=1, route_name=f"Block {error_code}")
        if error_code == "MISSING_WORK_TIME_STANDARD":
            db.execute("DELETE FROM work_time_standards")
        else:
            db.execute(
                "INSERT INTO production_node_capabilities "
                "(production_node_id,product_family,status) VALUES (?,?,'active')",
                (node_id, "unmatched"),
            )
        db.commit()
        result = ScheduleCapacityService.generate_order_schedule(
            order_id, start_date="2026-09-18", schedule_run_key=f"node-block-{error_code}",
        )
        assert result["operations"][0]["status"] == "blocked"
        assert result["operations"][0]["blocked_code"] == error_code
