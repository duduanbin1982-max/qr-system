import os
import sqlite3
from uuid import uuid4

import pytest

from modules import config
from factories import create_process_route, ensure_process
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


def _product(db, code):
    product_id = db.execute(
        "INSERT INTO products(product_code,product_name,model,spec,category) "
        "VALUES(?,?,'','','结构件')",
        (code, f"产品-{code}"),
    ).lastrowid
    db.execute(
        "INSERT OR IGNORE INTO product_code_aliases(product_id,product_code,source) "
        "VALUES(?,?,'current')",
        (product_id, code),
    )
    return product_id


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


def test_conflicting_identity_is_excluded_from_groups_and_reported(
    client, auth_headers, db
):
    suffix = uuid4().hex[:8]
    inventory_product_id = _product(db, f"CONFLICT-A-{suffix}")
    alias_product_id = _product(db, f"CONFLICT-B-{suffix}")
    alias_code = db.execute(
        "SELECT product_code FROM products WHERE id=?", (alias_product_id,)
    ).fetchone()[0]
    inventory_id = db.execute(
        "INSERT INTO inventory(product_model,product_name,quantity,product_id,"
        "product_code_snapshot,product_name_snapshot) VALUES(?, '冲突库存', 9, ?, ?, '冲突库存')",
        (alias_code, inventory_product_id, alias_code),
    ).lastrowid
    db.commit()

    groups = client.get("/api/inventory/product-groups", headers=auth_headers).get_json()
    assert inventory_product_id not in {item["product_id"] for item in groups["items"]}
    assert alias_product_id not in {item["product_id"] for item in groups["items"]}

    exceptions = client.get(
        "/api/inventory/product-groups?identity_status=conflict",
        headers=auth_headers,
    ).get_json()["identity_exceptions"]
    warning = next(item for item in exceptions if item["inventory_id"] == inventory_id)
    assert warning["reason"] == "product_identity_conflict"


def test_compatibility_groups_split_route_version_and_quality(client, auth_headers, db):
    scenario = seed_product_inventory_scenario(db)
    process_id = ensure_process(db, f"compat-process-{uuid4().hex[:8]}")
    first_route = create_process_route(db, [process_id], name=f"route-a-{uuid4().hex[:8]}")
    second_route = create_process_route(db, [process_id], name=f"route-b-{uuid4().hex[:8]}")
    route_versions = [
        db.execute(
            "SELECT current_effective_version_id FROM process_routes WHERE id=?", (route_id,)
        ).fetchone()[0]
        for route_id in (first_route, second_route)
    ]
    db.execute(
        "UPDATE inventory SET route_version_id_snapshot=?,quality_status='qualified' WHERE id=?",
        (route_versions[0], scenario["inventory_ids"][0]),
    )
    db.execute(
        "UPDATE inventory SET route_version_id_snapshot=?,quality_status='quarantined' WHERE id=?",
        (route_versions[1], scenario["inventory_ids"][1]),
    )
    db.commit()

    payload = client.get(
        f"/api/inventory/product-groups/{scenario['product_id']}/details",
        headers=auth_headers,
    ).get_json()
    assert {
        (group["route_version_id_snapshot"], group["quality_status"])
        for group in payload["compatibility_groups"]
    } == {
        (route_versions[0], "qualified"),
        (route_versions[1], "quarantined"),
    }


def test_compatibility_normalizes_whitespace_and_key_filters_exact_group(
    client, auth_headers, db
):
    scenario = seed_product_inventory_scenario(db, specs=(" 标准 ", "标准"))
    first_inventory, second_inventory = scenario["inventory_ids"]
    db.execute(
        "UPDATE inventory SET quality_status='   ' WHERE id=?",
        (first_inventory,),
    )
    db.execute(
        "UPDATE inventory SET quality_status='qualified' WHERE id=?",
        (second_inventory,),
    )
    db.commit()

    details_url = f"/api/inventory/product-groups/{scenario['product_id']}/details"
    payload = client.get(details_url, headers=auth_headers).get_json()
    assert len(payload["compatibility_groups"]) == 1
    group = payload["compatibility_groups"][0]
    assert group["specification"] == "标准"
    assert group["quality_status"] == "qualified"
    assert len({item["compatibility_key"] for item in payload["compatibility_groups"]}) == 1

    isolated = client.get(
        f"{details_url}?compatibility_key={group['compatibility_key']}",
        headers=auth_headers,
    ).get_json()
    assert {item["inventory_id"] for item in isolated["inventory_items"]} == {
        first_inventory, second_inventory,
    }


def test_compatibility_key_detail_filter_isolates_one_displayed_group(
    client, auth_headers, db
):
    scenario = seed_product_inventory_scenario(db, specs=("标准", "加厚"))
    details_url = f"/api/inventory/product-groups/{scenario['product_id']}/details"
    payload = client.get(details_url, headers=auth_headers).get_json()
    standard = next(
        group for group in payload["compatibility_groups"]
        if group["specification"] == "标准"
    )

    isolated = client.get(
        f"{details_url}?compatibility_key={standard['compatibility_key']}",
        headers=auth_headers,
    ).get_json()
    assert len(isolated["inventory_items"]) == 1
    assert isolated["inventory_items"][0]["specification"] == "标准"


def test_product_warning_is_not_hidden_by_first_hundred_unrelated_exceptions(
    client, auth_headers, db
):
    for index in range(101):
        db.execute(
            "INSERT INTO inventory(product_model,product_name,quantity) VALUES(?,?,1)",
            (f"UNRELATED-{index:03d}-{uuid4().hex[:6]}", "无关异常"),
        )
    suffix = uuid4().hex[:8]
    product_id = _product(db, f"TARGET-A-{suffix}")
    conflicting_product_id = _product(db, f"TARGET-B-{suffix}")
    conflicting_code = db.execute(
        "SELECT product_code FROM products WHERE id=?", (conflicting_product_id,)
    ).fetchone()[0]
    target_inventory_id = db.execute(
        "INSERT INTO inventory(product_model,product_name,quantity,product_id,"
        "product_code_snapshot) VALUES(?, '目标冲突', 1, ?, ?)",
        (conflicting_code, product_id, conflicting_code),
    ).lastrowid
    db.commit()

    payload = client.get(
        f"/api/inventory/product-groups/{product_id}/details",
        headers=auth_headers,
    ).get_json()
    assert target_inventory_id in {
        warning["inventory_id"] for warning in payload["identity_warnings"]
    }


def test_query_flag_disabled_returns_actionable_conflict(
    client, auth_headers, monkeypatch
):
    monkeypatch.setattr(config, "INVENTORY_PRODUCT_QUERY_ENABLED", False)
    capabilities = client.get(
        "/api/inventory/capabilities", headers=auth_headers
    ).get_json()
    assert capabilities["product_query_enabled"] is False

    response = client.get("/api/inventory/product-groups", headers=auth_headers)
    assert response.status_code == 409
    assert response.get_json() == {
        "error": "产品编码库存视图尚未启用",
        "code": "inventory_product_query_disabled",
        "action": "use_order_inventory_view",
    }


@pytest.mark.parametrize("endpoint", [
    "/api/inventory/capabilities",
    "/api/inventory/product-groups",
    "/api/inventory/product-groups/1/details",
])
def test_product_query_endpoints_require_auth_and_inventory_view_permission(
    client, worker_auth_headers, endpoint
):
    client.delete_cookie("qr_token")
    assert client.get(endpoint).status_code == 401
    assert client.get(endpoint, headers=worker_auth_headers).status_code == 403
