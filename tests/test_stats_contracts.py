import uuid
from datetime import datetime

from modules.db import get_db
from modules.domain.reporting_day import current_reporting_day, reporting_day_bounds


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
    quantity=1,
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
            "VALUES (?, ?, ?, 'normal', ?, 'daily display contract', 'approved', ?, datetime('now','localtime'))",
            (order_id, process_id, user_id, quantity, serial_no),
        )
    else:
        db.execute(
            "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, remark, status, serial_no, created_at) "
            "VALUES (?, ?, ?, 'normal', ?, 'daily display contract', 'approved', ?, ?)",
            (order_id, process_id, user_id, quantity, serial_no, created_at),
        )
    return order_id, product_code


def _insert_work_time_record(db, order_id, process_id, user_id, recorded_at, quantity):
    db.execute(
        "INSERT INTO work_time_records ("
        "order_id, process_id, user_id, quantity, standard_minutes, actual_minutes, "
        "effective_minutes, end_time, status, review_status"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'completed', 'approved')",
        (order_id, process_id, user_id, quantity, quantity * 10, quantity * 10, quantity * 10, recorded_at),
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


def _seed_two_daily_records(client, first_date="2026-06-30 08:00:00", second_date="2026-06-30 09:00:00"):
    first_order_no = f"TEST-DAILY-{uuid.uuid4().hex[:8].upper()}"
    second_order_no = f"TEST-DAILY-{uuid.uuid4().hex[:8].upper()}"

    with client.application.app_context():
        db = get_db()
        process_id = _active_process_id(db)
        user = db.execute("SELECT id FROM users WHERE username = 'testrunner'").fetchone()
        user_id = user["id"]
        _, first_product_code = _insert_daily_record(
            db,
            process_id,
            user_id,
            first_order_no,
            "",
            "",
            "2026-06-30 08:00:00",
            quantity=2,
        )
        _, second_product_code = _insert_daily_record(
            db,
            process_id,
            user_id,
            second_order_no,
            "",
            "",
            "2026-06-30 09:00:00",
            quantity=3,
        )
        db.commit()
    return first_order_no, second_order_no, first_product_code, second_product_code


def test_daily_records_include_product_metadata(client, auth_headers):
    first_order_no, second_order_no, first_product_code, second_product_code = _seed_two_daily_records(client)

    response = client.get("/api/stats/daily?date=2026-06-30&per_page=5001", headers=auth_headers)

    assert response.status_code == 200, response.get_json()
    data = response.get_json()
    by_order = {row["order_no"]: row for row in data["records"]}
    assert by_order[first_order_no]["product_code"] == first_product_code
    assert by_order[second_order_no]["product_code"] == second_product_code
    assert "product_model" in by_order[first_order_no]
    assert "customer" in by_order[first_order_no]
    assert "route_name" in by_order[first_order_no]


def test_daily_records_are_grouped_by_employee_with_totals(client, auth_headers):
    first_order_no, second_order_no, _first_product_code, _second_product_code = _seed_two_daily_records(client)
    response = client.get("/api/stats/daily?date=2026-06-30&per_page=5000", headers=auth_headers)
    assert response.status_code == 200, response.get_json()
    data = response.get_json()

    matching_groups = [
        group for group in data["employee_groups"]
        if {row["order_no"] for row in group["records"]} >= {first_order_no, second_order_no}
    ]
    assert len(matching_groups) == 1
    group = matching_groups[0]
    assert group["record_count"] == 2
    assert group["total_quantity"] == 5
    assert group["normal_quantity"] == 5
    assert group["order_count"] == 2
    assert group["product_count"] == 2
    assert [row["order_no"] for row in group["records"]] == [first_order_no, second_order_no]

    totals = data["summary_totals"]
    assert totals["record_count"] >= 2
    assert totals["total_quantity"] >= 5
    assert totals["worker_count"] >= 1
    assert totals["order_count"] >= 2
    assert totals["product_count"] >= 2


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


def test_reporting_day_uses_seven_am_boundary(client, auth_headers):
    prefix = f"TEST-REPORTING-DAY-{uuid.uuid4().hex[:8].upper()}"
    samples = [
        (f"{prefix}-BEFORE", "2026-06-30 06:59:59", 1),
        (f"{prefix}-START", "2026-06-30 07:00:00", 2),
        (f"{prefix}-END", "2026-07-01 06:59:59", 3),
        (f"{prefix}-AFTER", "2026-07-01 07:00:00", 4),
    ]

    with client.application.app_context():
        db = get_db()
        process_id = _active_process_id(db)
        user_id = db.execute("SELECT id FROM users WHERE username = 'testrunner'").fetchone()["id"]
        for order_no, recorded_at, quantity in samples:
            order_id, _product_code = _insert_daily_record(
                db,
                process_id,
                user_id,
                order_no,
                "",
                "",
                recorded_at,
                quantity=quantity,
            )
            _insert_work_time_record(db, order_id, process_id, user_id, recorded_at, quantity)
        db.commit()

    response = client.get("/api/stats/daily?date=2026-06-30", headers=auth_headers)

    assert response.status_code == 200, response.get_json()
    data = response.get_json()
    matching_orders = {
        row["order_no"] for row in data["records"] if row["order_no"].startswith(prefix)
    }
    assert matching_orders == {f"{prefix}-START", f"{prefix}-END"}
    assert data["total"] == 2
    assert data["summary_totals"]["record_count"] == 2
    assert data["summary_totals"]["total_quantity"] == 5
    assert sum(group["record_count"] for group in data["employee_groups"]) == 2
    assert data["work_time_summary"]["record_count"] == 2
    assert data["work_time_summary"]["quantity"] == 5
    assert data["period_start"] == "2026-06-30 07:00:00"
    assert data["period_end"] == "2026-07-01 07:00:00"

    legacy_response = client.get("/api/daily-report?date=2026-06-30", headers=auth_headers)
    assert legacy_response.status_code == 200, legacy_response.get_json()
    legacy_quantity = sum(
        process["quantity"]
        for employee in legacy_response.get_json()["report"]
        for process in employee["processes"].values()
    )
    assert legacy_quantity == 5


def test_reporting_day_helpers_handle_pre_shift_time():
    assert reporting_day_bounds("2026-06-30") == (
        "2026-06-30 07:00:00",
        "2026-07-01 07:00:00",
    )
    assert current_reporting_day(datetime(2026, 7, 1, 6, 59, 59)) == "2026-06-30"
    assert current_reporting_day(datetime(2026, 7, 1, 7, 0, 0)) == "2026-07-01"
