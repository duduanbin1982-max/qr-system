import pytest

from factories import create_order, create_process_route
from modules import config
from modules.db import get_db
from modules.domain.production_node_scheduling import NodeSchedulingError, ProductionNodePolicy
from modules.services.schedule_capacity_service import ScheduleCapacityService


def _enable_node_engine(monkeypatch):
    monkeypatch.setattr(config, "PRODUCTION_NODE_QUERY_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_WRITE_ENABLED", True)
    monkeypatch.setattr(config, "PRODUCTION_NODE_ENGINE_ENABLED", True)


def _seed_batch_order(db, quantity=5, serial_ids=None):
    process = db.execute("SELECT id FROM processes WHERE name='焊接'").fetchone()
    route_id = create_process_route(db, [process["id"]], name="Batch node route")
    order_id = create_order(db, [process["id"]], quantity=quantity, product_code="BATCH-NODE-01")
    db.execute("UPDATE orders SET route_id=?,plan_start='2026-09-18' WHERE id=?", (route_id, order_id))
    route_version_id = db.execute(
        "SELECT current_effective_version_id FROM process_routes WHERE id=?", (route_id,)
    ).fetchone()[0]
    process_version_id = db.execute(
        "SELECT process_version_id FROM process_route_version_items WHERE route_version_id=? AND process_id=?",
        (route_version_id, process["id"]),
    ).fetchone()[0]
    db.execute(
        "INSERT INTO work_time_standards "
        "(route_id,route_version_id,process_id,process_version_id,standard_minutes_per_unit,"
        "setup_minutes,difficulty_factor,status,version) VALUES (?,?,?,?,?,?,?,'active',1)",
        (route_id, route_version_id, process["id"], process_version_id, 60, 0, 1),
    )
    db.commit()
    nodes = db.execute(
        "SELECT n.*,pl.id AS legacy_line_id FROM production_nodes n "
        "JOIN process_production_lines pl ON pl.id=n.legacy_process_line_id "
        "WHERE n.process_id=? ORDER BY n.id", (process["id"],)
    ).fetchall()
    assert nodes
    node_id = nodes[0]["id"]
    db.execute(
        "UPDATE production_nodes SET status=CASE WHEN id=? THEN 'active' ELSE 'inactive' END "
        "WHERE process_id=?", (node_id, process["id"])
    )
    db.execute(
        "UPDATE production_nodes SET capacity_mode='batch' WHERE id=?", (node_id,)
    )
    db.execute(
        "INSERT INTO production_node_capabilities "
        "(production_node_id,max_batch_quantity,batch_minutes,changeover_minutes,allow_mixed_orders,status) "
        "VALUES (?,?,?,?,?,'active')", (node_id, 2, 20, 5, 0),
    )
    if serial_ids:
        order_no = db.execute("SELECT order_no FROM orders WHERE id=?", (order_id,)).fetchone()[0]
        for position, serial_id in enumerate(serial_ids, start=1):
            db.execute(
                "INSERT INTO product_items (serial_no,order_id,order_no,position_no,status) "
                "VALUES (?,?,?,?, 'pending')",
                (serial_id, order_id, order_no, position),
            )
    db.commit()
    return order_id, node_id


def test_quantity_conservation_fails_closed():
    with pytest.raises(NodeSchedulingError) as exc:
        ProductionNodePolicy.validate_quantity_conservation(
            5, [{"production_node_id": 1, "quantity": 4}]
        )
    assert exc.value.code == "QUANTITY_CONSERVATION_FAILED"
    assert exc.value.details == {"requested_quantity": 5, "allocated_quantity": 4}


def test_serial_items_are_assigned_to_one_node_and_keep_text_ids():
    serial_ids = ["26072401-001", "A-001"]
    allocations = [{"production_node_id": 10, "serial_ids": serial_ids}]
    assert ProductionNodePolicy.validate_serial_allocation(serial_ids, allocations)
    assert all(isinstance(value, str) for value in serial_ids)


def test_batch_schedule_persists_bounded_allocations_and_changeover(client, monkeypatch):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        order_id, node_id = _seed_batch_order(db, quantity=5)
        result = ScheduleCapacityService.generate_order_schedule(
            order_id, start_date="2026-09-18", schedule_run_key="batch-safe-001",
        )
        operation = result["operations"][0]
        assert operation["status"] == "planned"
        allocations = db.execute(
            "SELECT * FROM production_node_schedule_allocations "
            "WHERE schedule_id=? ORDER BY id", (operation["id"],)
        ).fetchall()
        assert sum(row["quantity"] for row in allocations) == 5
        assert {row["production_node_id"] for row in allocations} == {node_id}
        assert all(row["quantity"] <= 2 for row in allocations)
        assert len({row["batch_key"] for row in allocations}) == 3
        assert allocations[0]["changeover_minutes"] == 5
        assert all(row["serial_id"] is None for row in allocations)


def test_batch_keys_are_stable_across_idempotent_regeneration(client, monkeypatch):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        order_id, _ = _seed_batch_order(db, quantity=3)
        first = ScheduleCapacityService.generate_order_schedule(
            order_id, start_date="2026-09-18", schedule_run_key="batch-safe-stable-001",
        )
        first_keys = [row["batch_key"] for row in db.execute(
            "SELECT batch_key FROM production_node_schedule_allocations WHERE schedule_id=? ORDER BY id",
            (first["operations"][0]["id"],),
        ).fetchall()]
        replay = ScheduleCapacityService.generate_order_schedule(
            order_id, start_date="2026-09-18", schedule_run_key="batch-safe-stable-002",
        )
        second_keys = [row["batch_key"] for row in db.execute(
            "SELECT batch_key FROM production_node_schedule_allocations WHERE schedule_id=? ORDER BY id",
            (replay["operations"][0]["id"],),
        ).fetchall()]
        assert first_keys == second_keys


def test_serial_schedule_persists_text_ids_on_one_node(client, monkeypatch):
    _enable_node_engine(monkeypatch)
    with client.application.app_context():
        db = get_db()
        serial_ids = ["26072401-001", "A-001"]
        order_id, node_id = _seed_batch_order(db, quantity=len(serial_ids), serial_ids=serial_ids)
        result = ScheduleCapacityService.generate_order_schedule(
            order_id, start_date="2026-09-18", schedule_run_key="serial-safe-001",
        )
        operation = result["operations"][0]
        allocations = db.execute(
            "SELECT production_node_id,quantity,serial_id FROM production_node_schedule_allocations "
            "WHERE schedule_id=? ORDER BY id", (operation["id"],)
        ).fetchall()
        assert [row["serial_id"] for row in allocations] == serial_ids
        assert {row["production_node_id"] for row in allocations} == {node_id}
        assert sum(row["quantity"] for row in allocations) == len(serial_ids)
