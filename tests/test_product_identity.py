import uuid

from modules.db import get_db


def _create_catalog_product(client, auth_headers):
    suffix = uuid.uuid4().hex[:8].upper()
    response = client.post(
        "/api/products",
        headers=auth_headers,
        json={
            "product_name": f"快照产品-{suffix}",
            "model": f"MODEL-{suffix}",
            "spec": "三角型",
            "style": "标准",
            "upper_opening": "360",
            "plate_thickness": "18",
            "category": "结构件",
        },
    )
    assert response.status_code == 200, response.get_json()
    product_id = response.get_json()["id"]
    with client.application.app_context():
        product = dict(get_db().execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone())
    return product


def _create_linked_order(client, auth_headers, product):
    response = client.post(
        "/api/orders",
        headers=auth_headers,
        json={
            "order_no": f"IDENTITY-{uuid.uuid4().hex[:8].upper()}",
            "product_id": product["id"],
            "product_code": product["product_code"],
            "product_name": product["product_name"],
            "quantity": 1,
        },
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()["id"]


def test_product_edit_keeps_order_id_and_name_code_snapshots(client, auth_headers):
    product = _create_catalog_product(client, auth_headers)
    order_id = _create_linked_order(client, auth_headers, product)

    response = client.put(
        f"/api/products/{product['id']}",
        headers=auth_headers,
        json={
            "product_name": "改名后的产品",
            "model": product["model"] + "-V2",
        },
    )
    assert response.status_code == 200, response.get_json()
    new_code = response.get_json()["product_code"]
    assert new_code != product["product_code"]

    with client.application.app_context():
        db = get_db()
        order = db.execute(
            "SELECT product_id, product_code, product_name FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        aliases = {
            row["product_code"]: row["product_id"]
            for row in db.execute(
                "SELECT product_code, product_id FROM product_code_aliases WHERE product_id = ?",
                (product["id"],),
            ).fetchall()
        }

    assert tuple(order) == (product["id"], product["product_code"], product["product_name"])
    assert aliases[product["product_code"]] == product["id"]
    assert aliases[new_code] == product["id"]


def test_order_product_id_and_code_mismatch_is_rejected(client, auth_headers):
    product = _create_catalog_product(client, auth_headers)
    response = client.post(
        "/api/orders",
        headers=auth_headers,
        json={
            "order_no": f"IDENTITY-MISMATCH-{uuid.uuid4().hex[:8].upper()}",
            "product_id": product["id"],
            "product_code": "NOT-THIS-PRODUCT",
            "product_name": product["product_name"],
            "quantity": 1,
        },
    )
    assert response.status_code == 400
    assert "不匹配" in response.get_json()["error"]


def test_daily_metadata_uses_stable_product_id_after_code_change(client, auth_headers):
    product = _create_catalog_product(client, auth_headers)
    order_id = _create_linked_order(client, auth_headers, product)

    with client.application.app_context():
        db = get_db()
        process = db.execute(
            "SELECT id FROM processes WHERE status = 'active' ORDER BY id LIMIT 1"
        ).fetchone()
        user = db.execute(
            "SELECT id FROM users WHERE username = 'testrunner'"
        ).fetchone()
        db.execute(
            "INSERT INTO work_records "
            "(order_id, process_id, user_id, type, quantity, status, created_at) "
            "VALUES (?, ?, ?, 'normal', 1, 'approved', '2025-02-17 08:00:00')",
            (order_id, process["id"], user["id"]),
        )
        db.commit()

    response = client.put(
        f"/api/products/{product['id']}",
        headers=auth_headers,
        json={"product_name": "报表外部改名", "model": product["model"] + "-V3"},
    )
    assert response.status_code == 200, response.get_json()

    daily = client.get(
        "/api/stats/daily?date=2025-02-17&per_page=5000",
        headers=auth_headers,
    )
    assert daily.status_code == 200, daily.get_json()
    rows = [row for row in daily.get_json()["records"] if row["order_id"] == order_id]
    assert len(rows) == 1
    assert rows[0]["product_id"] == product["id"]
    assert rows[0]["product_name"] == product["product_name"]
    assert rows[0]["product_model"] == product["model"] + "-V3"
