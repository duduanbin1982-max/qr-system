import json
import sqlite3
import uuid
from datetime import datetime

import pytest

from factories import ensure_process, create_process_route
from modules.db import get_db
from modules.services.schedule_capacity_service import ScheduleCapacityService
from modules.services.process_service import ProcessService
from modules.repositories.schedule_capacity_repository import ScheduleCapacityRepository
from modules.migrations import run_migrations
from scripts.preflight_schedule_precision import run_preflight


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
    route_version = db.execute(
        "SELECT current_effective_version_id FROM process_routes WHERE id=?", (route_id,)
    ).fetchone()[0]
    process_version = db.execute(
        "SELECT process_version_id FROM process_route_version_items "
        "WHERE route_version_id=? AND process_id=?", (route_version, process_id)
    ).fetchone()[0]
    db.execute(
        "INSERT INTO work_time_standards (route_id, route_version_id, process_id, process_version_id, "
        "standard_minutes_per_unit, setup_minutes, difficulty_factor, status, version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 1)",
        (route_id, route_version, process_id, process_version, unit, setup, factor),
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
        assert rows[1]["planned_start_at"] >= rows[0]["planned_end_at"]
        assert rows[1]["plan_start"] == rows[0]["plan_end"]
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
        _seed_standard(db, route_id, first, unit=10)
        _seed_standard(db, route_id, missing, unit=10)
        _seed_standard(db, route_id, last, unit=10)
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


def test_missing_standard_blocks_without_fabricated_duration(client):
    with client.application.app_context():
        db = get_db()
        process = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        route_id = create_process_route(db, [process], name="Capacity Missing Standard")
        order_id, _ = _seed_capacity_order(db, [process], route_id=route_id, quantity=10)
        result = ScheduleCapacityService.generate_order_schedule(order_id, schedule_run_key="capacity-missing-v1")
        row = result["operations"][0]
        assert row["status"] == "blocked"
        assert row["blocked_reason"] == "未配置标准工时"
        assert row["planned_minutes"] == 0


def test_schedule_fact_contains_exact_versions_and_standard_snapshot(client):
    with client.application.app_context():
        db = get_db()
        process = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        route_id = create_process_route(db, [process], name="Capacity Version Snapshot")
        order_id, _ = _seed_capacity_order(db, [process], route_id=route_id)
        _seed_standard(db, route_id, process, unit=12, setup=3, factor=1.5)
        result = ScheduleCapacityService.generate_order_schedule(order_id, schedule_run_key="capacity-snapshot-v1")
        row = result["operations"][0]
        assert row["route_version_id"]
        assert row["process_version_id"]
        assert row["standard_id"]
        assert row["standard_version"] == 1
        assert row["process_name_snapshot"]
        assert row["route_name_snapshot"] == "Capacity Version Snapshot"
        stored = db.execute(
            "SELECT route_version_id,process_version_id,standard_id,process_name_snapshot,"
            "route_name_snapshot,schedule_run_id FROM order_process_schedules WHERE order_id=?",
            (order_id,),
        ).fetchone()
        assert dict(stored)["schedule_run_id"]


def test_schedule_run_replays_after_detail_rows_are_removed(client):
    with client.application.app_context():
        db = get_db()
        process = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        route_id = create_process_route(db, [process], name="Capacity Run Ledger")
        order_id, _ = _seed_capacity_order(db, [process], route_id=route_id)
        _seed_standard(db, route_id, process)
        first = ScheduleCapacityService.generate_order_schedule(order_id, schedule_run_key="capacity-ledger-v1")
        db.execute("DELETE FROM order_process_schedules WHERE order_id=?", (order_id,))
        db.commit()
        replay = ScheduleCapacityService.generate_order_schedule(order_id, schedule_run_key="capacity-ledger-v1")
        assert replay["idempotent_replay"] is True
        assert replay["operations"] == first["operations"]


@pytest.mark.parametrize("limit", [0, -1, 1001, "bad", ""])
def test_schedule_queries_reject_invalid_limits(client, limit):
    with client.application.app_context():
        with pytest.raises(ValueError, match="limit"):
            ScheduleCapacityService.list_schedules(limit)
        with pytest.raises(ValueError, match="limit"):
            ScheduleCapacityService.list_schedulable_orders(limit)


def test_version_binding_mismatch_is_rejected_on_schedule_fact_write(client):
    with client.application.app_context():
        db = get_db()
        process = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        route_id = create_process_route(db, [process], name="Capacity Binding Guard")
        order_id, _ = _seed_capacity_order(db, [process], route_id=route_id)
        order = ScheduleCapacityRepository.ensure_order_version_bindings(order_id, db)
        op = db.execute("SELECT id,process_id,process_version_id FROM order_processes WHERE order_id=?", (order_id,)).fetchone()
        with pytest.raises(ValueError, match="版本绑定不一致"):
            ScheduleCapacityRepository.insert_operation_schedule(
                {
                    "order_id": order_id,
                    "order_process_id": op["id"],
                    "process_id": op["process_id"],
                    "route_version_id": order["route_version_id"] + 999,
                    "process_version_id": op["process_version_id"],
                    "plan_start": "2026-09-01",
                    "plan_end": "2026-09-01",
                    "status": "blocked",
                    "blocked_reason": "test",
                    "schedule_run_key": "capacity-binding-v1",
                    "schedule_run_id": None,
                },
                db,
            )


def test_soft_deleted_order_does_not_occupy_a_process_line(client):
    with client.application.app_context():
        db = get_db()
        process = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        route_id = create_process_route(db, [process], name="Capacity Deleted Occupancy")
        order_one, _ = _seed_capacity_order(db, [process], route_id=route_id, plan_start="2026-09-01")
        order_two, _ = _seed_capacity_order(db, [process], route_id=route_id, plan_start="2026-09-01")
        _seed_standard(db, route_id, process, unit=480)
        first = ScheduleCapacityService.generate_order_schedule(order_one, schedule_run_key="capacity-delete-v1")
        db.execute(
            "UPDATE orders SET deleted_at=datetime('now','localtime'),deleted_by=1 WHERE id=?",
            (order_one,),
        )
        db.commit()
        second = ScheduleCapacityService.generate_order_schedule(order_two, schedule_run_key="capacity-delete-v2")
        assert second["operations"][0]["plan_start"] == first["operations"][0]["plan_start"]


def test_capacity_query_endpoint_rejects_malformed_limit(client, auth_headers):
    response = client.get("/api/schedule/capacity-orders?limit=not-a-number", headers=auth_headers)
    assert response.status_code == 400
    assert "limit" in (response.get_json() or {}).get("error", "")


def test_product_specific_standard_never_falls_back_to_another_product(client):
    with client.application.app_context():
        db = get_db()
        process = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        route_id = create_process_route(db, [process], name="Capacity Strict Product")
        product_one = db.execute(
            "INSERT INTO products (product_name,product_code) VALUES ('产品一','STRICT-P1')"
        ).lastrowid
        product_two = db.execute(
            "INSERT INTO products (product_name,product_code) VALUES ('产品二','STRICT-P2')"
        ).lastrowid
        order_id, _ = _seed_capacity_order(db, [process], route_id=route_id)
        db.execute(
            "UPDATE orders SET product_id=?,product_code=? WHERE id=?",
            (product_one, "STRICT-P1", order_id),
        )
        route_version = db.execute(
            "SELECT current_effective_version_id FROM process_routes WHERE id=?", (route_id,)
        ).fetchone()[0]
        process_version = db.execute(
            "SELECT process_version_id FROM process_route_version_items WHERE route_version_id=? AND process_id=?",
            (route_version, process),
        ).fetchone()[0]
        db.execute(
            "INSERT INTO work_time_standards (product_id,route_id,route_version_id,process_id,process_version_id,"
            "standard_minutes_per_unit,status,version) VALUES (?,?,?,?,?,?,?,?)",
            (product_two, route_id, route_version, process, process_version, 99, "active", 1),
        )
        db.commit()
        result = ScheduleCapacityService.generate_order_schedule(
            order_id, schedule_run_key="capacity-strict-product-v1"
        )
        assert result["operations"][0]["status"] == "blocked"
        assert result["operations"][0]["blocked_reason"] == "未配置标准工时"


def test_product_specific_standard_precedes_more_specific_generic_standard(client):
    with client.application.app_context():
        db = get_db()
        process = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        route_id = create_process_route(db, [process], name="Capacity Product Priority")
        product_id = db.execute(
            "INSERT INTO products (product_name,product_code) VALUES ('产品优先','PRIORITY-P1')"
        ).lastrowid
        order_id, _ = _seed_capacity_order(db, [process], route_id=route_id, quantity=10)
        db.execute(
            "UPDATE orders SET product_id=?,product_code=? WHERE id=?",
            (product_id, "PRIORITY-P1", order_id),
        )
        route_version = db.execute(
            "SELECT current_effective_version_id FROM process_routes WHERE id=?", (route_id,)
        ).fetchone()[0]
        process_version = db.execute(
            "SELECT process_version_id FROM process_route_version_items "
            "WHERE route_version_id=? AND process_id=?", (route_version, process)
        ).fetchone()[0]
        # A route-revision generic standard must not override an exact product
        # standard that is scoped to the process.
        _seed_standard(db, route_id, process, unit=20)
        db.execute(
            "INSERT INTO work_time_standards "
            "(product_id,process_id,process_version_id,standard_minutes_per_unit,status,version) "
            "VALUES (?,?,?,?,?,?)",
            (product_id, process, process_version, 7, "active", 1),
        )
        db.commit()
        result = ScheduleCapacityService.generate_order_schedule(
            order_id, schedule_run_key="capacity-product-priority-v1"
        )
        row = result["operations"][0]
        assert row["status"] == "planned"
        assert row["planned_minutes"] == pytest.approx(70)
        assert row["standard_match_scope"] == "process:product"


def test_legacy_schedule_snapshot_never_backfills_another_products_standard(client):
    from modules.migration_schedule_capacity import _schedule_snapshot

    with client.application.app_context():
        db = get_db()
        process = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        route_id = create_process_route(db, [process], name="Capacity Legacy Snapshot")
        product_one = db.execute(
            "INSERT INTO products (product_name,product_code) VALUES ('历史产品一','LEGACY-P1')"
        ).lastrowid
        product_two = db.execute(
            "INSERT INTO products (product_name,product_code) VALUES ('历史产品二','LEGACY-P2')"
        ).lastrowid
        order_id, _ = _seed_capacity_order(db, [process], route_id=route_id)
        db.execute(
            "UPDATE orders SET product_id=?,product_code=? WHERE id=?",
            (product_one, "LEGACY-P1", order_id),
        )
        route_version = db.execute(
            "SELECT current_effective_version_id FROM process_routes WHERE id=?", (route_id,)
        ).fetchone()[0]
        process_version = db.execute(
            "SELECT process_version_id FROM process_route_version_items "
            "WHERE route_version_id=? AND process_id=?", (route_version, process)
        ).fetchone()[0]
        db.execute(
            "INSERT INTO work_time_standards "
            "(product_id,route_id,route_version_id,process_id,process_version_id,"
            "standard_minutes_per_unit,status,version) VALUES (?,?,?,?,?,?,?,?)",
            (product_two, route_id, route_version, process, process_version, 99, "active", 1),
        )
        db.commit()
        result = ScheduleCapacityService.generate_order_schedule(
            order_id, schedule_run_key="capacity-legacy-snapshot-v1"
        )
        assert result["operations"][0]["status"] == "blocked"
        schedule = db.execute(
            "SELECT * FROM order_process_schedules WHERE order_id=?", (order_id,)
        ).fetchone()
        snapshot = _schedule_snapshot(schedule, db)
        assert snapshot["standard_id"] is None
        assert snapshot["standard_version"] is None


def test_capacity_audit_exposes_breakdowns_and_line_loads(client):
    with client.application.app_context():
        db = get_db()
        process = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        route_id = create_process_route(db, [process], name="Capacity Audit Breakdown")
        order_id, _ = _seed_capacity_order(db, [process], route_id=route_id, quantity=2)
        _seed_standard(db, route_id, process, unit=5)
        ScheduleCapacityService.generate_order_schedule(
            order_id, schedule_run_key="capacity-audit-breakdown-v1"
        )
        audit = ScheduleCapacityService.audit_schedule_capacity()
        assert audit["occupied_minutes"] == pytest.approx(30)
        assert audit["match_scope_counts"]["route_version:generic"] == 1
        assert audit["blocked_reason_counts"] == {}
        line = next(item for item in audit["line_loads"] if item["process_id"] == process)
        assert line["scheduled_operations"] == 1
        assert line["occupied_minutes"] == pytest.approx(30)
        assert line["conflict_count"] == 0


def test_capacity_audit_exposes_delivery_risk_breakdown(client):
    with client.application.app_context():
        db = get_db()
        process = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        route_id = create_process_route(db, [process], name="Capacity Audit Risk")
        order_id, _ = _seed_capacity_order(db, [process], route_id=route_id, quantity=2)
        db.execute("UPDATE orders SET deadline='2026-09-01' WHERE id=?", (order_id,))
        _seed_standard(db, route_id, process, unit=60, setup=0)
        ScheduleCapacityService.generate_order_schedule(
            order_id, schedule_run_key="capacity-audit-risk-v1"
        )

        audit = ScheduleCapacityService.audit_schedule_capacity(
            now=datetime(2026, 9, 4, 10, 0)
        )

        assert audit["risk_counts"]["overdue"] >= 1
        assert audit["risk_order_count"] >= 1
        assert audit["delayed_order_count"] >= 1
        assert audit["total_delay_minutes"] > 0
        assert audit["max_delay_minutes"] > 0
        assert any(item["order_id"] == order_id for item in audit["risk_orders"])


def test_precision_preflight_returns_structured_breakdowns_without_source_mutation(tmp_path):
    source = tmp_path / "schedule-preflight.db"
    db = sqlite3.connect(source)
    try:
        run_migrations(db)
        before = db.execute("PRAGMA user_version").fetchone()[0]
    finally:
        db.close()

    report = run_preflight(source, limit=10)
    assert report["database_user_version"] == before == 82
    assert report["operations"] == 0
    assert report["coverage_percent"] == 100.0
    assert report["process_statistics"] == []
    assert report["product_statistics"] == []
    assert report["line_loads"]

    check = sqlite3.connect(source)
    try:
        assert check.execute("PRAGMA user_version").fetchone()[0] == before
    finally:
        check.close()


def test_precision_schedule_spans_shifts_and_preserves_snapshot(client):
    with client.application.app_context():
        db = get_db()
        process = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        route_id = create_process_route(db, [process], name="Capacity Precision Time")
        order_id, _ = _seed_capacity_order(db, [process], route_id=route_id, quantity=10, plan_start="2026-09-01")
        _seed_standard(db, route_id, process, unit=60, setup=0)
        result = ScheduleCapacityService.generate_order_schedule(
            order_id, schedule_run_key="capacity-precision-time-v1"
        )
        row = result["operations"][0]
        assert row["planned_start_at"] == "2026-09-01 08:00"
        assert row["planned_end_at"] == "2026-09-02 10:00"
        assert row["occupied_minutes"] == pytest.approx(600)
        assert row["standard_match_scope"].endswith(":generic")
        snapshot = json.loads(row["capacity_snapshot_json"])
        assert snapshot["daily_minutes"] == pytest.approx(480)
        assert len(row["segments"]) == 3
        stored_segments = db.execute(
            "SELECT COUNT(*) FROM order_process_schedule_segments WHERE schedule_id=?",
            (row["id"],),
        ).fetchone()[0]
        assert stored_segments == 3


def test_weekend_is_skipped_by_default_calendar(client):
    with client.application.app_context():
        db = get_db()
        process = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        route_id = create_process_route(db, [process], name="Capacity Calendar Weekend")
        order_id, _ = _seed_capacity_order(db, [process], route_id=route_id, quantity=10, plan_start="2026-09-04")
        _seed_standard(db, route_id, process, unit=60)
        result = ScheduleCapacityService.generate_order_schedule(
            order_id, schedule_run_key="capacity-calendar-weekend-v1"
        )
        row = result["operations"][0]
        assert row["planned_start_at"] == "2026-09-04 08:00"
        assert row["planned_end_at"] == "2026-09-07 10:20"


def test_parallel_lines_are_selected_by_earliest_minute_completion(client):
    with client.application.app_context():
        db = get_db()
        process = db.execute("SELECT id FROM processes WHERE name='焊接'").fetchone()["id"]
        route_id = create_process_route(db, [process], name="Capacity Parallel Minute")
        first_order, _ = _seed_capacity_order(db, [process], route_id=route_id, quantity=10)
        second_order, _ = _seed_capacity_order(db, [process], route_id=route_id, quantity=10)
        _seed_standard(db, route_id, process, unit=30)
        first = ScheduleCapacityService.generate_order_schedule(
            first_order, schedule_run_key="capacity-parallel-minute-1"
        )
        second = ScheduleCapacityService.generate_order_schedule(
            second_order, schedule_run_key="capacity-parallel-minute-2"
        )
        first_row = first["operations"][0]
        second_row = second["operations"][0]
        first_snapshot = json.loads(first_row["capacity_snapshot_json"])
        second_snapshot = json.loads(second_row["capacity_snapshot_json"])
        assert first_snapshot["line_count"] > 1
        assert sum(int(line["quantity"]) for line in first_snapshot["lines"]) == 10
        assert sum(int(segment.get("quantity") or 0) for segment in first_row["segments"]) == 10
        assert second_row["planned_start_at"] >= first_row["planned_end_at"]
        assert second_snapshot["line_count"] > 1
        assert sum(int(segment.get("quantity") or 0) for segment in second_row["segments"]) == 10


def test_generation_creates_draft_revision_and_immutable_items(client):
    with client.application.app_context():
        db = get_db()
        first = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        second = db.execute("SELECT id FROM processes WHERE name='焊接'").fetchone()["id"]
        route_id = create_process_route(db, [first, second], name="Revision Draft")
        order_id, _ = _seed_capacity_order(db, [first, second], route_id=route_id)
        _seed_standard(db, route_id, first, unit=5)
        _seed_standard(db, route_id, second, unit=7)

        result = ScheduleCapacityService.generate_order_schedule(
            order_id, schedule_run_key="capacity-revision-draft-v1"
        )
        revision_id = result["schedule_revision_id"]
        revision = db.execute(
            "SELECT * FROM schedule_revisions WHERE id=?", (revision_id,)
        ).fetchone()
        items = db.execute(
            "SELECT * FROM schedule_revision_items WHERE revision_id=? ORDER BY seq_order",
            (revision_id,),
        ).fetchall()

        assert revision["status"] == "draft"
        assert revision["result_digest"]
        assert len(items) == 2
        assert {item["order_process_id"] for item in items} == {
            row["id"] for row in db.execute(
                "SELECT id FROM order_processes WHERE order_id=?", (order_id,)
            ).fetchall()
        }
        assert all(item["payload_digest"] for item in items)
        # A generated revision is a draft until explicitly published; the
        # order's current published pointer must therefore remain unset.
        assert db.execute(
            "SELECT current_schedule_revision_id FROM orders WHERE id=?", (order_id,)
        ).fetchone()[0] is None

        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "UPDATE schedule_revision_items SET quantity=quantity+1 WHERE revision_id=?",
                (revision_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute(
                "DELETE FROM schedule_revision_items WHERE revision_id=?", (revision_id,)
            )


def test_generation_freezes_delivery_risk_snapshot_on_revision(client):
    with client.application.app_context():
        db = get_db()
        process = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        route_id = create_process_route(db, [process], name="Revision Risk Snapshot")
        order_id, _ = _seed_capacity_order(
            db, [process], route_id=route_id, quantity=10, plan_start="2026-09-01"
        )
        db.execute("UPDATE orders SET deadline='2026-09-01' WHERE id=?", (order_id,))
        _seed_standard(db, route_id, process, unit=60, setup=0)

        result = ScheduleCapacityService.generate_order_schedule(
            order_id, schedule_run_key="capacity-revision-risk-v1"
        )
        revision = db.execute(
            "SELECT deadline_snapshot,projected_completion_at_snapshot,risk_level,"
            "delay_minutes,risk_reason,risk_assessed_at FROM schedule_revisions WHERE id=?",
            (result["schedule_revision_id"],),
        ).fetchone()

        assert revision["deadline_snapshot"] == "2026-09-01"
        assert revision["projected_completion_at_snapshot"]
        assert revision["risk_level"] == "overdue"
        assert revision["delay_minutes"] > 0
        assert "交期" in revision["risk_reason"]
        assert revision["risk_assessed_at"]
        with pytest.raises(sqlite3.IntegrityError, match="risk snapshot is immutable"):
            db.execute(
                "UPDATE schedule_revisions SET risk_reason='tampered' WHERE id=?",
                (result["schedule_revision_id"],),
            )


def test_failed_generation_retains_cancelled_revision(client, monkeypatch):
    with client.application.app_context():
        db = get_db()
        process = ensure_process(db, "无排程资源", seq_order=1)
        route_id = create_process_route(db, [process], name="Revision Cancelled")
        order_id, _ = _seed_capacity_order(db, [process], route_id=route_id)
        _seed_standard(db, route_id, process, unit=10)

        result = ScheduleCapacityService.generate_order_schedule(
            order_id, schedule_run_key="capacity-revision-cancelled-v1"
        )
        assert result["status"] == "completed"
        # Force a persistence failure after the revision has been created;
        # the run must remain auditable as a cancelled revision.
        def fail_insert(*args, **kwargs):
            raise RuntimeError("schedule persistence failed")

        monkeypatch.setattr(
            ScheduleCapacityRepository, "insert_operation_schedule", fail_insert
        )
        with pytest.raises(ValueError, match="schedule persistence failed"):
            ScheduleCapacityService.generate_order_schedule(
                order_id, schedule_run_key="capacity-revision-cancelled-v2"
            )
        revision = db.execute(
            "SELECT status,source_run_key FROM schedule_revisions "
            "WHERE order_id=? ORDER BY revision_no DESC LIMIT 1", (order_id,)
        ).fetchone()
        assert revision["status"] == "cancelled"
        assert revision["source_run_key"] == "capacity-revision-cancelled-v2"


def test_regeneration_keeps_history_and_publish_supersedes_previous_revision(client):
    with client.application.app_context():
        db = get_db()
        process = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        route_id = create_process_route(db, [process], name="Revision History")
        order_id, _ = _seed_capacity_order(db, [process], route_id=route_id)
        _seed_standard(db, route_id, process, unit=5)

        first = ScheduleCapacityService.generate_order_schedule(
            order_id, schedule_run_key="capacity-revision-history-v1"
        )
        first_id = first["schedule_revision_id"]
        ScheduleCapacityService.publish_revision(first_id, published_by=1000)
        first_published_at = db.execute(
            "SELECT published_at FROM schedule_revisions WHERE id=?", (first_id,)
        ).fetchone()[0]
        # Publishing the same revision again is a no-op, including timestamps.
        ScheduleCapacityService.publish_revision(first_id, published_by=1000)
        assert db.execute(
            "SELECT published_at FROM schedule_revisions WHERE id=?", (first_id,)
        ).fetchone()[0] == first_published_at

        second = ScheduleCapacityService.generate_order_schedule(
            order_id, schedule_run_key="capacity-revision-history-v2"
        )
        second_id = second["schedule_revision_id"]
        ScheduleCapacityService.publish_revision(second_id, published_by=1000)
        rows = db.execute(
            "SELECT id,status,superseded_by FROM schedule_revisions "
            "WHERE order_id=? ORDER BY revision_no", (order_id,)
        ).fetchall()
        assert [row["id"] for row in rows] == [first_id, second_id]
        assert rows[0]["status"] == "superseded"
        assert rows[0]["superseded_by"] == second_id
        assert rows[1]["status"] == "published"


def test_revision_publish_requires_exact_operation_set(client):
    with client.application.app_context():
        db = get_db()
        process = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        route_id = create_process_route(db, [process], name="Revision Completeness")
        order_id, _ = _seed_capacity_order(db, [process], route_id=route_id)
        other_order_id, _ = _seed_capacity_order(db, [process], route_id=route_id)
        _seed_standard(db, route_id, process, unit=5)
        result = ScheduleCapacityService.generate_order_schedule(
            order_id, schedule_run_key="capacity-revision-completeness-v1"
        )
        revision_id = result["schedule_revision_id"]
        other_op_id = db.execute(
            "SELECT id FROM order_processes WHERE order_id=?", (other_order_id,)
        ).fetchone()[0]
        op = db.execute(
            "SELECT id FROM order_processes WHERE order_id=?", (order_id,)
        ).fetchone()[0]
        assert op != other_op_id
        malformed = ScheduleCapacityRepository.create_revision(
            order_id, None, "capacity-revision-completeness-malformed", db
        )
        db.execute(
            "INSERT INTO schedule_revision_items "
            "(revision_id,order_process_id,process_id,seq_order) VALUES (?,?,?,?)",
            (malformed, other_op_id, process, 1),
        )
        db.commit()
        with pytest.raises(ValueError, match="条目不完整"):
            ScheduleCapacityService.publish_revision(malformed, published_by=1000)


def test_revision_api_contracts_and_permissions(client, auth_headers, worker_auth_headers):
    with client.application.app_context():
        db = get_db()
        process = db.execute("SELECT id FROM processes WHERE name='下料'").fetchone()["id"]
        route_id = create_process_route(db, [process], name="Revision API")
        order_id, _ = _seed_capacity_order(db, [process], route_id=route_id)
        _seed_standard(db, route_id, process, unit=5)
        result = ScheduleCapacityService.generate_order_schedule(
            order_id, schedule_run_key="capacity-revision-api-v1"
        )
        revision_id = result["schedule_revision_id"]

    revisions = client.get(
        f"/api/schedule/order/{order_id}/revisions?limit=1", headers=auth_headers
    )
    assert revisions.status_code == 200
    assert revisions.get_json()["revisions"][0]["id"] == revision_id

    detail = client.get(f"/api/schedule/revisions/{revision_id}", headers=auth_headers)
    assert detail.status_code == 200
    assert detail.get_json()["revision"]["id"] == revision_id
    assert detail.get_json()["items"]

    invalid = client.get("/api/schedule/revisions/999999", headers=auth_headers)
    assert invalid.status_code == 400
    assert "不存在" in invalid.get_json()["error"]

    malformed_limit = client.get(
        f"/api/schedule/revisions/{revision_id}?limit=bad", headers=auth_headers
    )
    assert malformed_limit.status_code == 400
    assert "limit" in malformed_limit.get_json()["error"]

    publish = client.post(
        f"/api/schedule/revisions/{revision_id}/publish", headers=auth_headers
    )
    assert publish.status_code == 200
    assert publish.get_json()["revision"]["status"] == "published"

    forbidden = client.post(
        f"/api/schedule/revisions/{revision_id}/publish", headers=worker_auth_headers
    )
    assert forbidden.status_code == 403
