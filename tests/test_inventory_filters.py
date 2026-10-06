import os
import sqlite3

import pytest

from tests.inventory_product_helpers import seed_product_inventory_scenario


@pytest.fixture
def db():
    connection = sqlite3.connect(os.environ["DB_PATH"])
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def test_order_inventory_filters_support_specification_quality_and_pagination(
    client, auth_headers, db
):
    scenario = seed_product_inventory_scenario(db, specs=("标准", "加厚"))

    options = client.get("/api/inventory/filter-options", headers=auth_headers)
    assert options.status_code == 200
    payload = options.get_json()
    assert {item["value"] for item in payload["specifications"]} >= {"标准", "加厚"}
    assert payload["quality_statuses"]

    filtered = client.get(
        "/api/inventory?specification=加厚&quality_status=qualified&page=1&limit=1",
        headers=auth_headers,
    )
    assert filtered.status_code == 200
    body = filtered.get_json()
    assert body["total"] == 1
    assert body["limit"] == 1
    assert len(body["items"]) == 1
    assert body["items"][0]["specification"] == "加厚"
    assert body["items"][0]["id"] == scenario["inventory_ids"][1]

    stats = client.get(
        "/api/inventory/stats?specification=加厚&quality_status=qualified",
        headers=auth_headers,
    )
    assert stats.status_code == 200
    summary = stats.get_json()
    assert summary["total_items"] == 1
    assert summary["total_quantity"] == 7


def test_order_inventory_empty_specification_filter(client, auth_headers, db):
    db.execute(
        "INSERT INTO inventory(product_model,product_name,specification,quantity) "
        "VALUES('EMPTY-SPEC-1','空规格','',3)"
    )
    db.commit()
    response = client.get(
        "/api/inventory?specification=__empty__", headers=auth_headers
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["total"] == 1
    assert body["items"][0]["specification"] == ""


def test_default_inventory_stats_subtract_frozen_quantity(
    client, auth_headers, db
):
    db.execute(
        "INSERT INTO inventory(product_model,product_name,quantity,reserved,"
        "frozen_quantity,safe_stock) VALUES('FROZEN-STATS-1','冻结测试',10,0,4,7)"
    )
    db.commit()

    items = client.get("/api/inventory", headers=auth_headers).get_json()
    stats = client.get("/api/inventory/stats", headers=auth_headers).get_json()

    assert items["total"] == 1
    assert items["items"][0]["available_quantity"] == 6
    assert items["items"][0]["is_low"] == 1
    assert stats["total_items"] == 1
    assert stats["low_stock"] == 1
