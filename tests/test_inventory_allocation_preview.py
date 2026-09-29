import os
import sqlite3

import pytest

from modules import config
from tests.inventory_product_helpers import seed_product_inventory_scenario


@pytest.fixture
def db():
    connection = sqlite3.connect(os.environ["DB_PATH"])
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture(autouse=True)
def allocation_flags(monkeypatch):
    monkeypatch.setattr(config, "INVENTORY_PRODUCT_QUERY_ENABLED", True)
    monkeypatch.setattr(config, "INVENTORY_ALLOCATION_PREVIEW_ENABLED", True)
    monkeypatch.setattr(config, "INVENTORY_CROSS_ORDER_OUTBOUND_ENABLED", True)
    monkeypatch.setattr(config, "INVENTORY_PRODUCT_THRESHOLD_ENABLED", True)


def test_fifo_preview_is_read_only_and_digest_is_stable(client, auth_headers, db):
    scenario = seed_product_inventory_scenario(db, quantities=(5, 7), reserved=(1, 2), frozen=(0, 1))
    before = db.execute("SELECT quantity,reserved,frozen_quantity FROM inventory ORDER BY id DESC LIMIT 2").fetchall()
    payload = client.post(
        f"/api/inventory/product-groups/{scenario['product_id']}/allocation-preview",
        headers=auth_headers,
        json={"quantity": 8, "mode": "fifo"},
    )
    assert payload.status_code == 200, payload.get_json()
    body = payload.get_json()
    assert body["read_only"] is True
    assert body["allocated_quantity"] == "8"
    assert len(body["items"]) == 2
    assert body["preview_digest"]
    after = db.execute("SELECT quantity,reserved,frozen_quantity FROM inventory ORDER BY id DESC LIMIT 2").fetchall()
    assert [tuple(row) for row in before] == [tuple(row) for row in after]

    repeat = client.post(
        f"/api/inventory/product-groups/{scenario['product_id']}/allocation-preview",
        headers=auth_headers,
        json={"quantity": 8, "mode": "fifo"},
    )
    assert repeat.get_json()["preview_digest"] == body["preview_digest"]


def test_manual_preview_rejects_sources_from_another_product(client, auth_headers, db):
    scenario = seed_product_inventory_scenario(db)
    other = db.execute(
        "INSERT INTO inventory(product_model,product_name,quantity) VALUES('OTHER-P','其他',5)"
    ).lastrowid
    db.commit()
    response = client.post(
        f"/api/inventory/product-groups/{scenario['product_id']}/allocation-preview",
        headers=auth_headers,
        json={"quantity": 1, "mode": "manual", "selected_inventory_ids": [other]},
    )
    assert response.status_code == 400
    assert response.get_json()["code"] == "inventory_allocation_validation_error"


def test_preview_shortage_is_explicit(client, auth_headers, db):
    scenario = seed_product_inventory_scenario(db, quantities=(1, 1), reserved=(1, 1), frozen=(0, 0))
    response = client.post(
        f"/api/inventory/product-groups/{scenario['product_id']}/allocation-preview",
        headers=auth_headers,
        json={"quantity": 1},
    )
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["code"] == "inventory_allocation_validation_error"
    assert payload["details"]["shortage"] == "1"


def test_preview_flag_disabled_is_actionable(client, auth_headers, monkeypatch, db):
    scenario = seed_product_inventory_scenario(db)
    monkeypatch.setattr(config, "INVENTORY_ALLOCATION_PREVIEW_ENABLED", False)
    response = client.post(
        f"/api/inventory/product-groups/{scenario['product_id']}/allocation-preview",
        headers=auth_headers,
        json={"quantity": 1},
    )
    assert response.status_code == 409
    assert response.get_json()["code"] == "inventory_allocation_preview_disabled"


def test_cross_order_outbound_is_atomic_idempotent_and_audited(client, auth_headers, db):
    scenario = seed_product_inventory_scenario(db, quantities=(5, 7), reserved=(1, 2), frozen=(0, 1))
    preview = client.post(
        f"/api/inventory/product-groups/{scenario['product_id']}/allocation-preview",
        headers=auth_headers,
        json={"quantity": 8},
    ).get_json()
    request = {
        "quantity": 8,
        "idempotency_key": "allocation-test-001",
        "preview_digest": preview["preview_digest"],
        "order_no": "OUT-TEST-001",
        "reason": "测试跨订单出库",
    }
    response = client.post(
        f"/api/inventory/product-groups/{scenario['product_id']}/outbound",
        headers=auth_headers,
        json=request,
    )
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["idempotent_replay"] is False
    assert len(body["items"]) == 2
    assert sum(float(item["allocated_quantity"]) for item in body["items"]) == 8
    assert db.execute("SELECT COUNT(*) FROM inventory_allocation_runs").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM inventory_allocation_items").fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM inventory_logs WHERE source_type='inventory_allocation'").fetchone()[0] == 2
    replay = client.post(
        f"/api/inventory/product-groups/{scenario['product_id']}/outbound",
        headers=auth_headers,
        json=request,
    )
    assert replay.status_code == 200
    assert replay.get_json()["idempotent_replay"] is True
    assert db.execute("SELECT COUNT(*) FROM inventory_allocation_runs").fetchone()[0] == 1


def test_cross_order_outbound_rejects_stale_preview(client, auth_headers, db):
    scenario = seed_product_inventory_scenario(db)
    response = client.post(
        f"/api/inventory/product-groups/{scenario['product_id']}/outbound",
        headers=auth_headers,
        json={"quantity": 1, "idempotency_key": "allocation-stale-001", "preview_digest": "stale"},
    )
    assert response.status_code == 409
    assert response.get_json()["code"] == "conflict"


@pytest.mark.parametrize(
    "payload",
    [
        {"quantity": 1, "idempotency_key": "allocation-missing-preview"},
        {
            "quantity": 1,
            "idempotency_key": "allocation-blank-preview",
            "preview_digest": "   ",
        },
    ],
)
def test_cross_order_outbound_requires_non_blank_preview_digest(
    client, auth_headers, db, payload
):
    scenario = seed_product_inventory_scenario(db)
    before_runs = db.execute(
        "SELECT COUNT(*) FROM inventory_allocation_runs"
    ).fetchone()[0]
    before_logs = db.execute("SELECT COUNT(*) FROM inventory_logs").fetchone()[0]

    response = client.post(
        f"/api/inventory/product-groups/{scenario['product_id']}/outbound",
        headers=auth_headers,
        json=payload,
    )

    assert response.status_code == 400
    assert db.execute(
        "SELECT COUNT(*) FROM inventory_allocation_runs"
    ).fetchone()[0] == before_runs
    assert db.execute("SELECT COUNT(*) FROM inventory_logs").fetchone()[0] == before_logs


def test_outbound_can_be_reversed_once_with_a_new_idempotency_key(client, auth_headers, db):
    scenario = seed_product_inventory_scenario(db, quantities=(5, 7), reserved=(1, 2), frozen=(0, 1))
    preview = client.post(
        f"/api/inventory/product-groups/{scenario['product_id']}/allocation-preview",
        headers=auth_headers, json={"quantity": 8},
    ).get_json()
    outbound = client.post(
        f"/api/inventory/product-groups/{scenario['product_id']}/outbound",
        headers=auth_headers,
        json={"quantity": 8, "idempotency_key": "allocation-reverse-source", "preview_digest": preview["preview_digest"]},
    ).get_json()
    reversed_response = client.post(
        f"/api/inventory/allocation-runs/{outbound['id']}/reverse",
        headers=auth_headers,
        json={"idempotency_key": "allocation-reverse-001", "reason": "测试撤销"},
    )
    assert reversed_response.status_code == 200, reversed_response.get_json()
    assert reversed_response.get_json()["mode"] == "reversal"
    assert db.execute("SELECT COUNT(*) FROM inventory_allocation_runs").fetchone()[0] == 2
    assert db.execute("SELECT SUM(qty_delta) FROM inventory_logs WHERE source_type LIKE 'inventory_allocation%'").fetchone()[0] == 0
    again = client.post(
        f"/api/inventory/allocation-runs/{outbound['id']}/reverse",
        headers=auth_headers,
        json={"idempotency_key": "allocation-reverse-001", "reason": "测试撤销"},
    )
    assert again.status_code == 200
    assert again.get_json()["idempotent_replay"] is True
    duplicate = client.post(
        f"/api/inventory/allocation-runs/{outbound['id']}/reverse",
        headers=auth_headers,
        json={"idempotency_key": "allocation-reverse-002", "reason": "重复撤销"},
    )
    assert duplicate.status_code == 409


def test_product_threshold_overrides_aggregate_warning_and_exports(client, auth_headers, db):
    scenario = seed_product_inventory_scenario(db, quantities=(5, 7), reserved=(1, 2), frozen=(0, 1))
    threshold = client.post(
        f"/api/inventory/product-groups/{scenario['product_id']}/threshold",
        headers=auth_headers,
        json={"safe_stock": 20, "warning_buffer": 5},
    )
    assert threshold.status_code == 200, threshold.get_json()
    groups = client.get("/api/inventory/product-groups", headers=auth_headers).get_json()["items"]
    group = next(item for item in groups if item["product_id"] == scenario["product_id"])
    assert group["safe_stock"] == 20
    assert group["warning_buffer"] == 5
    assert group["product_alert_level"] == "low"
    low_groups = client.get(
        "/api/inventory/product-groups?low_stock=1", headers=auth_headers
    ).get_json()["items"]
    assert scenario["product_id"] in {item["product_id"] for item in low_groups}
    summary = client.get("/api/inventory/product-groups/export", headers=auth_headers)
    assert summary.status_code == 200
    assert summary.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    detail = client.get(
        f"/api/inventory/product-groups/{scenario['product_id']}/export",
        headers=auth_headers,
    )
    assert detail.status_code == 200
