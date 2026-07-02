import uuid

from modules.db import get_db


def _active_process_id(db):
    row = db.execute(
        "SELECT id FROM processes WHERE status = 'active' ORDER BY seq_order, id LIMIT 1"
    ).fetchone()
    if row:
        return row["id"]
    cursor = db.execute(
        "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
        "VALUES (?, ?, ?, 1, 'active', datetime('now','localtime'))",
        ("Fixture Daily Stats Process", "pytest fixture process", "fixture"),
    )
    return cursor.lastrowid


def _insert_daily_record(
    db,
    process_id,
    user_id,
    order_no,
    qr_mode,
    serial_no,
    created_at=None,
):
    product_code = f"XMOD-{uuid.uuid4().hex[:6].upper()}"
    cursor = db.execute(
        "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status, qr_mode) "
        "VALUES (?, 'Test Customer', 'Cross Module Product', ?, 10, 'producing', ?)",
        (order_no, product_code, qr_mode),
    )
    order_id = cursor.lastrowid
    db.execute(
        "INSERT INTO order_processes (order_id, process_id, seq_order, status, completed, scrapped, rework) "
        "VALUES (?, ?, 1, 'pending', 0, 0, 0)",
        (order_id, process_id),
    )
    if created_at is None:
        db.execute(
            "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, remark, status, serial_no, created_at) "
            "VALUES (?, ?, ?, 'normal', 1, 'daily display contract', 'approved', ?, datetime('now','localtime'))",
            (order_id, process_id, user_id, serial_no),
        )
    else:
        db.execute(
            "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, remark, status, serial_no, created_at) "
            "VALUES (?, ?, ?, 'normal', 1, 'daily display contract', 'approved', ?, ?)",
            (order_id, process_id, user_id, serial_no, created_at),
        )


def test_daily_records_display_order_number_or_serial(client, auth_headers):
    order_no = f"TEST-DAILY-{uuid.uuid4().hex[:8].upper()}"
    serial_order_no = f"TEST-DAILY-{uuid.uuid4().hex[:8].upper()}"
    serial_no = f"SN-{uuid.uuid4().hex[:8].upper()}"

    with client.application.app_context():
        db = get_db()
        process_id = _active_process_id(db)
        user_id = db.execute("SELECT id FROM users WHERE username = 'testrunner'").fetchone()["id"]
        _insert_daily_record(db, process_id, user_id, order_no, "", "")
        _insert_daily_record(db, process_id, user_id, serial_order_no, "serial", serial_no)
        db.commit()

    response = client.get("/api/stats/daily", headers=auth_headers)

    assert response.status_code == 200, response.get_json()
    rows = response.get_json()["records"]
    by_order = {row["order_no"]: row for row in rows}

    assert by_order[order_no]["display_order_no"] == order_no
    assert by_order[order_no]["serial_no"] == ""
    assert by_order[serial_order_no]["display_order_no"] == serial_no
    assert by_order[serial_order_no]["serial_no"] == serial_no


def test_daily_records_cache_isolated_by_query_string(client, auth_headers):
    first_order_no = f"TEST-DAILY-{uuid.uuid4().hex[:8].upper()}"
    second_order_no = f"TEST-DAILY-{uuid.uuid4().hex[:8].upper()}"

    with client.application.app_context():
        db = get_db()
        process_id = _active_process_id(db)
        user_id = db.execute("SELECT id FROM users WHERE username = 'testrunner'").fetchone()["id"]
        _insert_daily_record(
            db,
            process_id,
            user_id,
            first_order_no,
            "",
            "",
            "2026-06-28 08:00:00",
        )
        _insert_daily_record(
            db,
            process_id,
            user_id,
            second_order_no,
            "",
            "",
            "2026-06-29 08:00:00",
        )
        db.commit()

    first_response = client.get("/api/stats/daily?date=2026-06-28", headers=auth_headers)
    second_response = client.get("/api/stats/daily?date=2026-06-29", headers=auth_headers)

    assert first_response.status_code == 200, first_response.get_json()
    assert second_response.status_code == 200, second_response.get_json()
    first_orders = {row["order_no"] for row in first_response.get_json()["records"]}
    second_orders = {row["order_no"] for row in second_response.get_json()["records"]}

    assert first_order_no in first_orders
    assert second_order_no not in first_orders
    assert second_order_no in second_orders
    assert first_order_no not in second_orders
