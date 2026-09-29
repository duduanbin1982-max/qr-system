import os
import sqlite3

import pytest

from modules import config
from tests.inventory_product_helpers import (
    seed_product_inventory_scenario,
    seed_unresolved_inventory,
)


@pytest.fixture
def db():
    connection = sqlite3.connect(os.environ["DB_PATH"])
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture(autouse=True)
def product_query_enabled(monkeypatch):
    monkeypatch.setattr(config, "INVENTORY_PRODUCT_QUERY_ENABLED", True)


def test_product_groups_aggregate_by_product_id_and_preserve_order_details(
    client, auth_headers, db
):
    scenario = seed_product_inventory_scenario(db)
    product_id = scenario["product_id"]
    first_inventory, second_inventory = scenario["inventory_ids"]

    response = client.get(
        "/api/inventory/product-groups?limit=50",
        headers=auth_headers,
    )

    assert response.status_code == 200
    payload = response.get_json()
    group = next(item for item in payload["items"] if item["product_id"] == product_id)
    assert group["quantity"] == 12
    assert group["reserved_quantity"] == 3
    assert group["frozen_quantity"] == 1
    assert group["available_quantity"] == 8
    assert group["order_count"] == 2

    details = client.get(
        f"/api/inventory/product-groups/{product_id}/details",
        headers=auth_headers,
    ).get_json()
    assert {item["inventory_id"] for item in details["inventory_items"]} == {
        first_inventory, second_inventory,
    }


def test_product_group_keeps_incompatible_specifications_separate(
    client, auth_headers, db
):
    scenario = seed_product_inventory_scenario(db, specs=("标准", "加厚"))
    product_id = scenario["product_id"]
    payload = client.get(
        f"/api/inventory/product-groups/{product_id}/details",
        headers=auth_headers,
    ).get_json()
    assert len(payload["compatibility_groups"]) == 2
    assert {group["specification"] for group in payload["compatibility_groups"]} == {
        "标准", "加厚",
    }


def test_unresolved_identity_is_reported_and_not_silently_aggregated(
    client, auth_headers, db
):
    inventory_id = seed_unresolved_inventory(db)
    payload = client.get(
        "/api/inventory/product-groups?identity_status=unresolved",
        headers=auth_headers,
    ).get_json()
    assert len(payload["identity_exceptions"]) == 1
    assert payload["identity_exceptions"][0]["inventory_id"] == inventory_id
    assert payload["identity_exceptions"][0]["reason"] == "product_identity_unresolved"
