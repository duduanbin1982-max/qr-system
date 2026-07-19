import uuid

from modules.db import get_db


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
