import uuid

import pytest

from modules import config
from modules.db import get_db
from modules.domain.errors import LegacyProcessLineWriteBlockedError
from modules.services.order_service import OrderService
from modules.services.production_line_service import ProductionLineService
from modules.services.schedule_service import ScheduleService


def _assert_blocked(response):
    assert response.status_code == 409, response.get_json()
    assert response.get_json()["code"] == "LEGACY_PROCESS_LINE_WRITE_BLOCKED"
    assert response.get_json()["action"] == "use_production_node_api"


def _order_payload(prefix="LEGACY-GUARD"):
    suffix = uuid.uuid4().hex[:8].upper()
    return {
        "order_no": f"TEST-{prefix}-{suffix}",
        "customer": "Legacy Guard Customer",
        "product_name": "Legacy Guard Product",
        "quantity": 1,
    }


def test_legacy_line_crud_is_available_before_cutover_and_blocked_afterward(
    client, auth_headers, monkeypatch
):
    monkeypatch.setattr(config, "LEGACY_PROCESS_LINE_WRITE_BLOCKED", False)
    line_name = f"Legacy Guard {uuid.uuid4().hex[:8]}"
    created = client.post(
        "/api/production-lines",
        headers=auth_headers,
        json={"name": line_name, "capacity_per_day": 9, "remark": "before cutover"},
    )
    assert created.status_code == 200, created.get_json()
    with client.application.app_context():
        db = get_db()
        line_id = db.execute(
            "INSERT INTO production_lines (name,capacity_per_day,remark,status) "
            "VALUES (?,9,'before cutover','active')",
            (f"{line_name} persisted",),
        ).lastrowid
        db.commit()

    monkeypatch.setattr(config, "LEGACY_PROCESS_LINE_WRITE_BLOCKED", True)

    listed = client.get("/api/production-lines", headers=auth_headers)
    assert listed.status_code == 200, listed.get_json()
    assert any(line["id"] == line_id for line in listed.get_json()["lines"])

    responses = (
        client.post(
            "/api/production-lines",
            headers=auth_headers,
            json={"name": f"Blocked {uuid.uuid4().hex[:8]}"},
        ),
        client.put(
            f"/api/production-lines/{line_id}",
            headers=auth_headers,
            json={"name": "Blocked Rename", "capacity_per_day": 1},
        ),
        client.delete(f"/api/production-lines/{line_id}", headers=auth_headers),
    )
    for response in responses:
        _assert_blocked(response)

    with client.application.app_context():
        row = get_db().execute(
            "SELECT name,capacity_per_day,remark FROM production_lines WHERE id=?",
            (line_id,),
        ).fetchone()
    assert dict(row) == {
        "name": f"{line_name} persisted",
        "capacity_per_day": 9,
        "remark": "before cutover",
    }


def test_service_layer_blocks_direct_legacy_line_and_order_assignment(
    monkeypatch
):
    monkeypatch.setattr(config, "LEGACY_PROCESS_LINE_WRITE_BLOCKED", True)

    with pytest.raises(LegacyProcessLineWriteBlockedError):
        ProductionLineService.create("Direct bypass")
    with pytest.raises(LegacyProcessLineWriteBlockedError):
        ProductionLineService.update(999999, "Direct bypass")
    with pytest.raises(LegacyProcessLineWriteBlockedError):
        ProductionLineService.delete(999999)
    with pytest.raises(LegacyProcessLineWriteBlockedError):
        OrderService.create_order(
            {**_order_payload("DIRECT-CREATE"), "production_line_id": 1}
        )
    with pytest.raises(LegacyProcessLineWriteBlockedError):
        OrderService.update_order(999999, {"production_line_id": None})
    with pytest.raises(LegacyProcessLineWriteBlockedError):
        ScheduleService.update_order_schedule(
            999999,
            "2026-09-20",
            "2026-09-21",
            production_line_id=None,
        )


def test_order_and_schedule_legacy_line_inputs_return_stable_409(
    client, auth_headers, monkeypatch
):
    monkeypatch.setattr(config, "LEGACY_PROCESS_LINE_WRITE_BLOCKED", False)
    created = client.post(
        "/api/orders", headers=auth_headers, json=_order_payload("BASE")
    )
    assert created.status_code == 200, created.get_json()
    order_id = created.get_json()["id"]

    monkeypatch.setattr(config, "LEGACY_PROCESS_LINE_WRITE_BLOCKED", True)

    blocked_create = client.post(
        "/api/orders",
        headers=auth_headers,
        json={**_order_payload("CREATE"), "production_line_id": None},
    )
    blocked_update = client.put(
        f"/api/orders/{order_id}",
        headers=auth_headers,
        json={"production_line_id": None},
    )
    blocked_batch = client.post(
        "/api/orders/batch",
        headers=auth_headers,
        json={
            "orders": [
                {**_order_payload("BATCH"), "production_line_id": None}
            ]
        },
    )
    blocked_schedule = client.patch(
        f"/api/schedule/order/{order_id}",
        headers=auth_headers,
        json={
            "plan_start": "2026-09-20",
            "plan_end": "2026-09-21",
            "production_line_id": None,
        },
    )

    for response in (
        blocked_create,
        blocked_update,
        blocked_batch,
        blocked_schedule,
    ):
        _assert_blocked(response)

    date_only = client.patch(
        f"/api/schedule/order/{order_id}",
        headers=auth_headers,
        json={"plan_start": "2026-09-20", "plan_end": "2026-09-21"},
    )
    assert date_only.status_code == 200, date_only.get_json()


def test_node_native_write_keeps_required_legacy_projection(
    client, auth_headers, monkeypatch
):
    monkeypatch.setattr(config, "PRODUCTION_NODE_WRITE_ENABLED", True)
    monkeypatch.setattr(config, "LEGACY_PROCESS_LINE_WRITE_BLOCKED", True)
    with client.application.app_context():
        node = get_db().execute(
            "SELECT id,legacy_process_line_id FROM production_nodes "
            "WHERE status='active' AND legacy_process_line_id IS NOT NULL "
            "ORDER BY id LIMIT 1"
        ).fetchone()
        assert node is not None
        node_id = node["id"]
        legacy_line_id = node["legacy_process_line_id"]

    response = client.post(
        "/api/schedule/downtime",
        headers=auth_headers,
        json={
            "production_node_id": node_id,
            "start_at": "2026-09-20 08:00:00",
            "end_at": "2026-09-20 09:00:00",
            "reason": "verify node-native compatibility projection",
        },
    )

    assert response.status_code == 200, response.get_json()
    event = response.get_json()["event"]
    assert event["production_node_id"] == node_id
    assert event["process_line_id"] == legacy_line_id
