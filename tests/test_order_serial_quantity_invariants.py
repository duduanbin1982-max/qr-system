import json
import uuid

from modules.db import get_db


def _create_serial_order(client, quantity, item_statuses):
    suffix = uuid.uuid4().hex[:8].upper()
    order_no = f"SERIAL-GUARD-{suffix}"
    with client.application.app_context():
        db = get_db()
        order_id = db.execute(
            "INSERT INTO orders "
            "(order_no,customer,product_name,product_code,quantity,status,qr_mode) "
            "VALUES (?,'Test Customer','Serial Guard Product',?,?,'pending','serial')",
            (order_no, f"SERIAL-GUARD-{suffix}", quantity),
        ).lastrowid
        for position, status in enumerate(item_statuses, start=1):
            serial_no = f"{order_no}-{position:03d}"
            db.execute(
                "INSERT INTO product_items "
                "(serial_no,order_id,position_no,qr_content,status) VALUES (?,?,?,?,?)",
                (
                    serial_no,
                    order_id,
                    position,
                    json.dumps({"serial_no": serial_no}),
                    status,
                ),
            )
        db.commit()
    return order_id, order_no


def test_order_quantity_change_rejects_active_serial_mismatch(
    client, auth_headers
):
    order_id, _ = _create_serial_order(client, 2, ["pending", "pending"])

    response = client.put(
        f"/api/orders/{order_id}",
        headers=auth_headers,
        json={"quantity": 3},
    )

    assert response.status_code == 400
    assert "已有 2 个有效序列件" in response.get_json()["error"]
    with client.application.app_context():
        quantity = get_db().execute(
            "SELECT quantity FROM orders WHERE id=?", (order_id,)
        ).fetchone()[0]
    assert quantity == 2


def test_order_quantity_change_allows_count_after_controlled_void(
    client, auth_headers
):
    order_id, _ = _create_serial_order(
        client, 3, ["pending", "pending", "deleted"]
    )

    response = client.put(
        f"/api/orders/{order_id}",
        headers=auth_headers,
        json={"quantity": 2},
    )

    assert response.status_code == 200, response.get_json()
    with client.application.app_context():
        quantity = get_db().execute(
            "SELECT quantity FROM orders WHERE id=?", (order_id,)
        ).fetchone()[0]
    assert quantity == 2


def test_serial_qr_reprint_excludes_voided_items(client, auth_headers):
    order_id, order_no = _create_serial_order(
        client, 2, ["pending", "pending", "deleted"]
    )

    response = client.post(
        "/api/qrcode/batch",
        headers=auth_headers,
        json={"order_ids": [order_id], "mode": "serial"},
    )

    assert response.status_code == 200, response.get_json()
    serials = [item["serial_no"] for item in response.get_json()["codes"]]
    assert serials == [f"{order_no}-001", f"{order_no}-002"]


def test_serial_qr_print_rejects_active_item_count_mismatch(
    client, auth_headers
):
    order_id, _ = _create_serial_order(
        client, 2, ["pending", "pending", "pending"]
    )

    response = client.post(
        "/api/qrcode/batch",
        headers=auth_headers,
        json={"order_ids": [order_id], "mode": "serial"},
    )

    assert response.status_code == 409
    assert "存在 3 个有效序列件" in response.get_json()["error"]
