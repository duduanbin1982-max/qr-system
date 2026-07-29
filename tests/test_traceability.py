import uuid

from factories import create_order, ensure_process
from modules.db import get_db


def _create_serial_trace_fixture(client, serial_count=1):
    suffix = uuid.uuid4().hex[:8].upper()
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, name=f"Trace Process {suffix}")
        order_id = create_order(
            db,
            [process_id],
            quantity=serial_count,
            product_code=f"TRACE-{suffix}",
        )
        order = db.execute(
            "SELECT order_no FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        user_id = db.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()["id"]
        serial_numbers = []
        for position in range(1, serial_count + 1):
            serial_no = f"TRACE-{suffix}-{position:03d}"
            serial_numbers.append(serial_no)
            db.execute(
                "INSERT INTO product_items "
                "(serial_no, order_id, position_no, qr_content, status, current_process_id) "
                "VALUES (?, ?, ?, '{}', 'in_progress', ?)",
                (serial_no, order_id, position, process_id),
            )
        db.execute(
            "INSERT INTO work_records "
            "(order_id, process_id, user_id, type, quantity, serial_no, status) "
            "VALUES (?, ?, ?, 'normal', 1, ?, 'approved')",
            (order_id, process_id, user_id, serial_numbers[0]),
        )
        db.commit()
        return {
            "order_id": order_id,
            "order_no": order["order_no"],
            "process_id": process_id,
            "user_id": user_id,
            "serial_numbers": serial_numbers,
        }


def test_existing_serial_trace_returns_item_order_and_work_history(client, auth_headers):
    fixture = _create_serial_trace_fixture(client)

    response = client.get(
        f"/api/trace/{fixture['serial_numbers'][0]}",
        headers=auth_headers,
    )

    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert payload["item"]["serial_no"] == fixture["serial_numbers"][0]
    assert payload["order"]["order_no"] == fixture["order_no"]
    assert len(payload["work_records"]) == 1
    assert payload["work_records"][0]["quantity"] == 1
