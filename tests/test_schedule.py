import json
import uuid

from factories import TEST_HASH, TEST_PASS
from modules.db import get_db


def _permission_headers(client, permissions):
    suffix = uuid.uuid4().hex[:8]
    username = f"schedule_perm_{suffix}"
    role_code = f"schedule_perm_{suffix}"
    with client.application.app_context():
        db = get_db()
        role_id = db.execute(
            "INSERT INTO roles (name, code, description, permissions, status, level) "
            "VALUES (?, ?, 'pytest schedule permission role', ?, 'active', 1)",
            (
                f"Schedule Permission {suffix}",
                role_code,
                json.dumps(permissions, ensure_ascii=False),
            ),
        ).lastrowid
        user_id = db.execute(
            "INSERT INTO users "
            "(username, password, name, role, status, password_version, employee_no) "
            "VALUES (?, ?, ?, ?, 'active', 2, ?)",
            (
                username,
                TEST_HASH,
                f"Schedule Permission {suffix}",
                role_code,
                f"TEST-SCHEDULE-{suffix.upper()}",
            ),
        ).lastrowid
        db.execute(
            "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
            (user_id, role_id),
        )
        db.commit()

    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": TEST_PASS},
    )
    assert response.status_code == 200, response.get_json()
    return {"Authorization": f"Bearer {response.get_json()['user']['token']}"}


def _seed_scheduled_order_with_line(client):
    suffix = uuid.uuid4().hex[:6].upper()
    with client.application.app_context():
        db = get_db()
        line_id = db.execute(
            "INSERT INTO production_lines (name, capacity_per_day, status) VALUES (?, 1, 'active')",
            (f"Schedule Line {suffix}",),
        ).lastrowid
        order_id = db.execute(
            "INSERT INTO orders ("
            "order_no, customer, product_name, product_code, quantity, status, "
            "plan_start, plan_end, production_line_id, qr_mode"
            ") VALUES (?, 'Test Customer', 'Test Product', ?, 10, 'producing', "
            "'2026-07-01', '2026-07-03', ?, '')",
            (f"TEST-SCHEDULE-LINE-{suffix}", f"XMOD-LINE-{suffix}", line_id),
        ).lastrowid
        db.commit()
    return order_id, line_id


def _seed_scheduled_orders(client):
    suffix = uuid.uuid4().hex[:6].upper()
    orders = [
        (f"TEST-ZZZ-SCHEDULE-{suffix}-001", "2026-01-01", "2026-01-03"),
        (f"TEST-ZZZ-SCHEDULE-{suffix}-002", "2026-06-01", "2026-06-03"),
        (f"TEST-ZZZ-SCHEDULE-{suffix}-003", "2026-12-01", "2026-12-03"),
    ]
    with client.application.app_context():
        db = get_db()
        for order_no, plan_start, plan_end in orders:
            db.execute(
                "INSERT INTO orders ("
                "order_no, customer, product_name, product_code, quantity, status, "
                "plan_start, plan_end, qr_mode"
                ") VALUES (?, 'Test Customer', 'Test Product', ?, 1, 'producing', ?, ?, '')",
                (order_no, f"XMOD-SCHEDULE-{suffix}", plan_start, plan_end),
            )
        db.commit()
    return [order_no for order_no, _, _ in orders]


def _seed_completed_scheduled_order(client):
    suffix = uuid.uuid4().hex[:6].upper()
    order_no = f"TEST-ZZZ-SCHEDULE-{suffix}-999"
    with client.application.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO orders ("
            "order_no, customer, product_name, product_code, quantity, completed, status, "
            "plan_start, plan_end, qr_mode"
            ") VALUES (?, 'Test Customer', 'Test Product', ?, 3, 3, 'completed', "
            "'2026-12-20', '2026-12-22', '')",
            (order_no, f"XMOD-SCHEDULE-{suffix}"),
        )
        db.commit()
    return order_no


def _schedule_order_nos(client, auth_headers, query=""):
    response = client.get("/api/schedule/gantt?limit=1000" + query, headers=auth_headers)
    assert response.status_code == 200, response.get_json()
    return [order["order_no"] for order in response.get_json()["orders"]]


def test_schedule_gantt_orders_by_order_no_desc(client, auth_headers):
    order_nos = _seed_scheduled_orders(client)

    response = client.get("/api/schedule/gantt?limit=1000", headers=auth_headers)

    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    visible_order_nos = [
        order["order_no"] for order in payload["orders"] if order["order_no"] in order_nos
    ]
    assert visible_order_nos == sorted(order_nos, reverse=True)


def test_schedule_gantt_defaults_to_active_orders(client, auth_headers):
    active_order_nos = _seed_scheduled_orders(client)
    completed_order_no = _seed_completed_scheduled_order(client)

    order_nos = _schedule_order_nos(client, auth_headers)

    assert completed_order_no not in order_nos
    for order_no in active_order_nos:
        assert order_no in order_nos


def test_schedule_gantt_completed_scope_shows_completed_only(client, auth_headers):
    active_order_nos = _seed_scheduled_orders(client)
    completed_order_no = _seed_completed_scheduled_order(client)

    order_nos = _schedule_order_nos(client, auth_headers, "&status=completed")

    assert completed_order_no in order_nos
    for order_no in active_order_nos:
        assert order_no not in order_nos


def test_schedule_gantt_all_scope_includes_active_and_completed(client, auth_headers):
    active_order_nos = _seed_scheduled_orders(client)
    completed_order_no = _seed_completed_scheduled_order(client)

    order_nos = _schedule_order_nos(client, auth_headers, "&status=all")

    assert completed_order_no in order_nos
    for order_no in active_order_nos:
        assert order_no in order_nos


def test_schedule_view_permission_cannot_modify_orders(client):
    order_id, _ = _seed_scheduled_order_with_line(client)
    headers = _permission_headers(
        client,
        ["page:production", "page:production.schedule", "schedule:view"],
    )

    assert client.get("/api/schedule/gantt", headers=headers).status_code == 200
    update = client.patch(
        f"/api/schedule/order/{order_id}",
        json={"plan_start": "2026-07-02", "plan_end": "2026-07-04"},
        headers=headers,
    )
    batch = client.post(
        "/api/schedule/batch-shift",
        json={"order_ids": [order_id], "days": 1},
        headers=headers,
    )

    assert update.status_code == 403, update.get_json()
    assert batch.status_code == 403, batch.get_json()


def test_schedule_edit_preserves_line_when_field_is_omitted(client):
    order_id, line_id = _seed_scheduled_order_with_line(client)
    headers = _permission_headers(
        client,
        ["page:production", "page:production.schedule", "schedule:view", "schedule:edit"],
    )

    response = client.patch(
        f"/api/schedule/order/{order_id}",
        json={"plan_start": "2026-07-02", "plan_end": "2026-07-05"},
        headers=headers,
    )

    assert response.status_code == 200, response.get_json()
    with client.application.app_context():
        order = get_db().execute(
            "SELECT plan_start, plan_end, production_line_id FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
    assert order["plan_start"] == "2026-07-02"
    assert order["plan_end"] == "2026-07-05"
    assert order["production_line_id"] == line_id


def test_schedule_edit_clears_line_only_when_explicitly_requested(client, auth_headers):
    order_id, _ = _seed_scheduled_order_with_line(client)

    response = client.patch(
        f"/api/schedule/order/{order_id}",
        json={
            "plan_start": "2026-07-01",
            "plan_end": "2026-07-03",
            "production_line_id": None,
        },
        headers=auth_headers,
    )

    assert response.status_code == 200, response.get_json()
    with client.application.app_context():
        production_line_id = get_db().execute(
            "SELECT production_line_id FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()["production_line_id"]
    assert production_line_id is None


def test_schedule_update_validates_dates_line_and_order_state(client, auth_headers):
    order_id, _ = _seed_scheduled_order_with_line(client)

    invalid_date = client.patch(
        f"/api/schedule/order/{order_id}",
        json={"plan_start": "2026/07/01", "plan_end": "2026-07-03"},
        headers=auth_headers,
    )
    reversed_dates = client.patch(
        f"/api/schedule/order/{order_id}",
        json={"plan_start": "2026-07-04", "plan_end": "2026-07-03"},
        headers=auth_headers,
    )
    invalid_line = client.patch(
        f"/api/schedule/order/{order_id}",
        json={
            "plan_start": "2026-07-01",
            "plan_end": "2026-07-03",
            "production_line_id": 999999,
        },
        headers=auth_headers,
    )
    missing_order = client.patch(
        "/api/schedule/order/999999",
        json={"plan_start": "2026-07-01", "plan_end": "2026-07-03"},
        headers=auth_headers,
    )
    with client.application.app_context():
        db = get_db()
        db.execute(
            "UPDATE orders SET status = 'completed', completed = quantity WHERE id = ?",
            (order_id,),
        )
        db.commit()
    completed_order = client.patch(
        f"/api/schedule/order/{order_id}",
        json={"plan_start": "2026-07-01", "plan_end": "2026-07-03"},
        headers=auth_headers,
    )

    assert invalid_date.status_code == 400, invalid_date.get_json()
    assert reversed_dates.status_code == 400, reversed_dates.get_json()
    assert invalid_line.status_code == 400, invalid_line.get_json()
    assert missing_order.status_code == 404, missing_order.get_json()
    assert completed_order.status_code == 409, completed_order.get_json()


def test_schedule_gantt_returns_full_summary_and_bounded_pages(client, auth_headers):
    order_nos = _seed_scheduled_orders(client)

    first = client.get(
        "/api/schedule/gantt?limit=2&offset=0",
        headers=auth_headers,
    )
    second = client.get(
        "/api/schedule/gantt?limit=2&offset=2",
        headers=auth_headers,
    )
    bounded = client.get(
        "/api/schedule/gantt?limit=10000",
        headers=auth_headers,
    )

    assert first.status_code == 200, first.get_json()
    first_payload = first.get_json()
    second_payload = second.get_json()
    assert len(first_payload["orders"]) == 2
    assert first_payload["has_more"] is True
    assert first_payload["stats"]["total"] == first_payload["total"]
    assert first_payload["stats"]["producing"] >= len(order_nos)
    visible = {
        order["order_no"]
        for order in first_payload["orders"] + second_payload["orders"]
    }
    assert set(order_nos).issubset(visible)
    assert bounded.get_json()["limit"] == 500
