import uuid

import pytest

from factories import ensure_process, create_process_route
from modules.db import get_db
from modules.services.schedule_capacity_service import ScheduleCapacityService
from modules.services.process_service import ProcessService


def _seed_capacity_order(db, process_ids, quantity=10, route_id=None, plan_start="2026-09-01"):
    suffix = uuid.uuid4().hex[:10].upper()
    if route_id is None:
        route_id = create_process_route(db, process_ids, name=f"Capacity Route {suffix}")
    order_id = db.execute(
        "INSERT INTO orders (order_no, product_name, product_code, quantity, status, plan_start, route_id) "
        "VALUES (?, 'Capacity Product', ?, ?, 'pending', ?, ?)",
        (f"CAP-{suffix}", f"CAP-CODE-{suffix}", quantity, plan_start, route_id),
    ).lastrowid
    for seq_order, process_id in enumerate(process_ids, start=1):
        db.execute(
            "INSERT INTO order_processes (order_id, process_id, seq_order, status) VALUES (?, ?, ?, 'pending')",
            (order_id, process_id, seq_order),
        )
    db.commit()
    return order_id, route_id


def _seed_standard(db, route_id, process_id, *, unit=10, setup=20, factor=1):
    db.execute(
        "INSERT INTO work_time_standards (route_id, process_id, standard_minutes_per_unit, setup_minutes, difficulty_factor, status) "
        "VALUES (?, ?, ?, ?, ?, 'active')",
        (route_id, process_id, unit, setup, factor),
    )
    db.commit()


def test_default_capacity_pool_matches_parallel_line_requirements(client):
    with client.application.app_context():
        db = get_db()
        # v65 provisions pools for operations already present in master data;
        # deployments add any missing operation roots through the process UI.
        expected = {"下料": 1, "焊接": 10, "打磨": 1, "喷漆": 2}
        rows = db.execute(
            "SELECT p.name, COUNT(pl.id) AS count FROM processes p "
            "JOIN process_production_lines pl ON pl.process_id=p.id "
            "WHERE p.name IN ({}) GROUP BY p.name".format(",".join("?" for _ in expected)),
            tuple(expected),
        ).fetchall()
        assert {row["name"]: row["count"] for row in rows} == expected


@pytest.mark.parametrize("process_name,expected_count", [("铆接", 4), ("抛丸", 1), ("镗孔", 2)])
def test_new_known_process_provisions_its_default_line_pool(client, process_name, expected_count):
    with client.application.app_context():
        process_id = ProcessService.create_process({"name": process_name, "category": "结构件"})
        count = get_db().execute(
            "SELECT COUNT(*) FROM process_production_lines WHERE process_id=?",
            (process_id,),
        ).fetchone()[0]
        assert count == expected_count


def test_renaming_a_process_does_not_create_a_second_line_pool(client):
    with client.application.app_context():
        process_id = ProcessService.create_process({"name": "铆接", "category": "结构件"})
        before = get_db().execute(
            "SELECT id, line_code FROM process_production_lines WHERE process_id=? ORDER BY id",
            (process_id,),
        ).fetchall()
        ProcessService.update_process(process_id, {"name": "铆接改名"})
        after = get_db().execute(
            "SELECT id, line_code FROM process_production_lines WHERE process_id=? ORDER BY id",
            (process_id,),
        ).fetchall()
        assert len(after) == len(before) == 4
        assert [row["id"] for row in after] == [row["id"] for row in before]


def test_capacity_orders_directory_is_read_only_and_includes_unplanned_orders(client, auth_headers):
    with client.application.app_context():
        db = get_db()
        process = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        order_id, _ = _seed_capacity_order(db, [process], plan_start="")
    response = client.get("/api/schedule/capacity-orders", headers=auth_headers)
    assert response.status_code == 200, response.get_json()
    assert any(row["id"] == order_id for row in response.get_json()["orders"])


def test_capacity_generation_requires_schedule_edit_permission(client):
    headers = {"Authorization": "Bearer invalid"}
    response = client.post("/api/schedule/order/1/generate", json={}, headers=headers)
    assert response.status_code in (401, 403)

def test_schedule_uses_work_time_factor_and_preserves_precedence(client):
    with client.application.app_context():
        db = get_db()
        cut = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        weld = db.execute("SELECT id FROM processes WHERE name='焊接'").fetchone()["id"]
        route_id = create_process_route(db, [cut, weld], name="Capacity Precedence")
        order_id, _ = _seed_capacity_order(db, [cut, weld], quantity=10, route_id=route_id)
        _seed_standard(db, route_id, cut, unit=30, setup=10, factor=2)
        _seed_standard(db, route_id, weld, unit=5, setup=0, factor=1)

        result = ScheduleCapacityService.generate_order_schedule(
            order_id, schedule_run_key="capacity-precedence-v1"
        )
        rows = result["operations"]
        assert rows[0]["planned_minutes"] == pytest.approx(610)
        assert rows[0]["difficulty_factor"] == pytest.approx(2)
        assert rows[0]["plan_start"] == "2026-09-01"
        assert rows[1]["plan_start"] > rows[0]["plan_end"]
        order = db.execute("SELECT plan_start, plan_end, schedule_version FROM orders WHERE id=?", (order_id,)).fetchone()
        assert order["plan_start"] == rows[0]["plan_start"]
        assert order["plan_end"] == rows[-1]["plan_end"]
        assert order["schedule_version"] == 2


def test_schedule_blocks_following_operations_when_a_line_is_unavailable(client):
    with client.application.app_context():
        db = get_db()
        first = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        missing = ensure_process(db, "排程无产线", seq_order=2)
        last = db.execute("SELECT id FROM processes WHERE name='焊接'").fetchone()["id"]
        route_id = create_process_route(db, [first, missing, last], name="Capacity Blocked")
        order_id, _ = _seed_capacity_order(db, [first, missing, last], route_id=route_id)
        result = ScheduleCapacityService.generate_order_schedule(order_id, schedule_run_key="capacity-blocked-v1")
        assert [row["status"] for row in result["operations"]] == ["planned", "blocked", "blocked"]
        assert result["operations"][1]["reason"] == "工序未配置可用产线"
        assert result["operations"][2]["reason"] == "前序工序无法排程"


def test_schedule_idempotency_replays_same_key_and_rejects_cross_order_reuse(client):
    with client.application.app_context():
        db = get_db()
        process = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        route_id = create_process_route(db, [process], name="Capacity Idempotency")
        order_one, _ = _seed_capacity_order(db, [process], route_id=route_id)
        order_two, _ = _seed_capacity_order(db, [process], route_id=route_id)
        first = ScheduleCapacityService.generate_order_schedule(order_one, schedule_run_key="capacity-idem-v1")
        replay = ScheduleCapacityService.generate_order_schedule(order_one, schedule_run_key="capacity-idem-v1")
        assert replay["idempotent_replay"] is True
        assert replay["operations"][0]["schedule_run_key"] == first["schedule_run_key"]
        with pytest.raises(ValueError, match="已被其他订单使用"):
            ScheduleCapacityService.generate_order_schedule(order_two, schedule_run_key="capacity-idem-v1")
