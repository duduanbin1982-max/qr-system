import uuid

from factories import TEST_USER
from modules.db import get_db


def _seed_route(client):
    suffix = uuid.uuid4().hex[:6].upper()
    route_name = f"Fixture Route Sync {suffix}"

    with client.application.app_context():
        db = get_db()
        process_ids = []
        for seq_order, label in enumerate(("Cut", "Weld", "Pack"), start=1):
            cursor = db.execute(
                "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
                "VALUES (?, ?, ?, ?, 'active', datetime('now','localtime'))",
                (f"Fixture {label} {suffix}", "cross module fixture", "fixture", seq_order),
            )
            process_ids.append(cursor.lastrowid)

        route_id = db.execute(
            "SELECT MAX(value) + 10000 FROM ("
            "SELECT COALESCE(MAX(id), 0) AS value FROM process_routes "
            "UNION ALL "
            "SELECT COALESCE(MAX(route_id), 0) AS value FROM orders WHERE route_id IS NOT NULL"
            ")"
        ).fetchone()[0]
        db.execute(
            "INSERT INTO process_routes (id, name, description, status, category, updated_at) "
            "VALUES (?, ?, ?, 'active', ?, datetime('now','localtime'))",
            (route_id, route_name, "cross module fixture", "fixture"),
        )

        for seq_order, process_id in enumerate(process_ids[:2], start=1):
            db.execute(
                "INSERT INTO process_route_items (route_id, process_id, seq_order, required_audit) "
                "VALUES (?, ?, ?, 0)",
                (route_id, process_id, seq_order),
            )

        db.commit()
        return route_id, route_name, process_ids


def _create_order_with_route(client, auth_headers, route_id):
    response = client.post(
        "/api/orders",
        headers=auth_headers,
        json={
            "order_no": f"TEST-ROUTE-SYNC-{uuid.uuid4().hex[:8].upper()}",
            "customer": "Cross Module Customer",
            "product_name": "Cross Module Product",
            "product_code": f"XMOD-{uuid.uuid4().hex[:6].upper()}",
            "quantity": 10,
            "route_id": route_id,
        },
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()["id"]


def _order_processes(client, order_id):
    with client.application.app_context():
        db = get_db()
        return [
            (row["process_id"], row["required_audit"])
            for row in db.execute(
                "SELECT process_id, required_audit FROM order_processes "
                "WHERE order_id = ? ORDER BY seq_order",
                (order_id,),
            ).fetchall()
        ]


def test_route_update_syncs_unreported_order_processes(client, auth_headers):
    route_id, route_name, process_ids = _seed_route(client)
    order_id = _create_order_with_route(client, auth_headers, route_id)

    assert _order_processes(client, order_id) == [(process_ids[0], 0), (process_ids[1], 0)]

    response = client.put(
        f"/api/process-routes/{route_id}",
        headers=auth_headers,
        json={
            "name": route_name,
            "description": "cross module fixture",
            "category": "fixture",
            "processes": [
                {"process_id": process_ids[2], "required_audit": 1},
                {"process_id": process_ids[0], "required_audit": 0},
            ],
        },
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["synced_orders"] == 1
    assert response.get_json()["skipped_orders"] == 0
    assert _order_processes(client, order_id) == [(process_ids[2], 1), (process_ids[0], 0)]


def test_route_update_skips_orders_with_work_records(client, auth_headers):
    route_id, route_name, process_ids = _seed_route(client)
    order_id = _create_order_with_route(client, auth_headers, route_id)

    with client.application.app_context():
        db = get_db()
        user_id = db.execute(
            "SELECT id FROM users WHERE username = ?",
            (TEST_USER,),
        ).fetchone()["id"]
        db.execute(
            "INSERT INTO work_records (order_id, process_id, user_id, status, quantity) "
            "VALUES (?, ?, ?, 'approved', 1)",
            (order_id, process_ids[0], user_id),
        )
        db.commit()

    response = client.put(
        f"/api/process-routes/{route_id}",
        headers=auth_headers,
        json={
            "name": route_name,
            "description": "cross module fixture",
            "category": "fixture",
            "processes": [
                {"process_id": process_ids[2], "required_audit": 1},
                {"process_id": process_ids[0], "required_audit": 0},
            ],
        },
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["synced_orders"] == 0
    assert response.get_json()["skipped_orders"] == 1
    assert _order_processes(client, order_id) == [(process_ids[0], 0), (process_ids[1], 0)]
