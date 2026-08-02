import uuid

from modules.db import get_db
from modules.product_query import ProductQueryFilter


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


def _insert_reporting_records(db, order_id, recorded_at, product_code=""):
    process = db.execute(
        "SELECT id FROM processes WHERE status = 'active' ORDER BY id LIMIT 1"
    ).fetchone()
    user = db.execute(
        "SELECT id FROM users WHERE username = 'testrunner'"
    ).fetchone()
    db.execute(
        "INSERT INTO work_records "
        "(order_id, process_id, user_id, type, quantity, status, created_at) "
        "VALUES (?, ?, ?, 'normal', 1, 'approved', ?)",
        (order_id, process["id"], user["id"], recorded_at),
    )
    db.execute(
        "INSERT INTO work_time_records ("
        "order_id, process_id, user_id, product_code, quantity, standard_minutes, "
        "actual_minutes, effective_minutes, end_time, status, review_status"
        ") VALUES (?, ?, ?, ?, 1, 10, 10, 10, ?, 'completed', 'approved')",
        (order_id, process["id"], user["id"], product_code, recorded_at),
    )


def _daily_order_ids(client, auth_headers, date, product_code):
    response = client.get(
        f"/api/stats/daily?date={date}&product_code={product_code}&per_page=5000",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json(), {
        row["order_id"] for row in response.get_json()["records"]
    }


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


def test_current_and_historical_codes_share_stable_report_identity(client, auth_headers):
    product = _create_catalog_product(client, auth_headers)
    old_code = product["product_code"]
    order_id = _create_linked_order(client, auth_headers, product)
    with client.application.app_context():
        db = get_db()
        _insert_reporting_records(db, order_id, "2026-07-12 08:00:00", old_code)
        db.commit()

    response = client.put(
        f"/api/products/{product['id']}",
        headers=auth_headers,
        json={"model": product["model"] + "-FILTER"},
    )
    assert response.status_code == 200, response.get_json()
    new_code = response.get_json()["product_code"]

    with client.application.app_context():
        db = get_db()
        assert ProductQueryFilter.resolve(db, old_code).product_id == product["id"]
        assert ProductQueryFilter.resolve(db, new_code).product_id == product["id"]

    old_data, old_order_ids = _daily_order_ids(
        client, auth_headers, "2026-07-12", old_code
    )
    new_data, new_order_ids = _daily_order_ids(
        client, auth_headers, "2026-07-12", new_code
    )
    assert order_id in old_order_ids
    assert order_id in new_order_ids
    assert old_data["work_time_summary"]["record_count"] == 1
    assert new_data["work_time_summary"]["record_count"] == 1


def test_stable_product_id_takes_precedence_over_conflicting_order_snapshot(
    client, auth_headers
):
    linked_product = _create_catalog_product(client, auth_headers)
    conflicting_product = _create_catalog_product(client, auth_headers)
    order_id = _create_linked_order(client, auth_headers, linked_product)
    with client.application.app_context():
        db = get_db()
        db.execute(
            "UPDATE orders SET product_code = ? WHERE id = ?",
            (conflicting_product["product_code"], order_id),
        )
        _insert_reporting_records(db, order_id, "2026-07-13 08:00:00")
        db.commit()

    linked_data, linked_order_ids = _daily_order_ids(
        client, auth_headers, "2026-07-13", linked_product["product_code"]
    )
    conflicting_data, conflicting_order_ids = _daily_order_ids(
        client, auth_headers, "2026-07-13", conflicting_product["product_code"]
    )
    assert order_id in linked_order_ids
    assert order_id not in conflicting_order_ids
    assert linked_data["work_time_summary"]["record_count"] == 1
    assert conflicting_data["work_time_summary"]["record_count"] == 0


def test_unresolved_product_code_uses_exact_snapshot_fallback(client, auth_headers):
    unresolved_code = f"LEGACY-{uuid.uuid4().hex[:8].upper()}"
    with client.application.app_context():
        db = get_db()
        order_id = db.execute(
            "INSERT INTO orders ("
            "order_no, product_name, product_code, quantity, status"
            ") VALUES (?, 'Legacy snapshot', ?, 1, 'producing')",
            (f"IDENTITY-LEGACY-{uuid.uuid4().hex[:8].upper()}", unresolved_code),
        ).lastrowid
        _insert_reporting_records(
            db, order_id, "2026-07-14 08:00:00", unresolved_code
        )
        db.commit()
        assert ProductQueryFilter.resolve(db, unresolved_code).product_id is None

    data, order_ids = _daily_order_ids(
        client, auth_headers, "2026-07-14", unresolved_code
    )
    _other_data, other_order_ids = _daily_order_ids(
        client, auth_headers, "2026-07-14", unresolved_code + "-OTHER"
    )
    assert order_id in order_ids
    assert order_id not in other_order_ids
    assert data["work_time_summary"]["record_count"] == 1
