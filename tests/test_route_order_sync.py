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
                (f"Fixture {label} {suffix}", "cross module fixture", "结构件", seq_order),
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
            (route_id, route_name, "cross module fixture", "结构件"),
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


def _order_route_id(client, order_id):
    with client.application.app_context():
        row = get_db().execute(
            "SELECT route_id FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        return row["route_id"]


def _route_processes(client, route_id):
    with client.application.app_context():
        return [
            (row["process_id"], row["required_audit"])
            for row in get_db().execute(
                "SELECT process_id, required_audit FROM process_route_items "
                "WHERE route_id = ? ORDER BY seq_order",
                (route_id,),
            ).fetchall()
        ]


def _seed_alternate_route(client, process_id):
    with client.application.app_context():
        db = get_db()
        route_id = db.execute(
            "SELECT MAX(value) + 10000 FROM ("
            "SELECT COALESCE(MAX(id), 0) AS value FROM process_routes "
            "UNION ALL "
            "SELECT COALESCE(MAX(route_id), 0) AS value FROM orders WHERE route_id IS NOT NULL"
            ")"
        ).fetchone()[0]
        db.execute(
            "INSERT INTO process_routes (id, name, description, status, category, updated_at) "
            "VALUES (?, ?, 'alternate route fixture', 'active', '结构件', datetime('now','localtime'))",
            (route_id, f"Alternate Route {uuid.uuid4().hex[:6].upper()}"),
        )
        db.execute(
            "INSERT INTO process_route_items (route_id, process_id, seq_order, required_audit) "
            "VALUES (?, ?, 1, 1)",
            (route_id, process_id),
        )
        db.commit()
        return route_id


def test_unreferenced_route_can_be_updated(client, auth_headers):
    route_id, route_name, process_ids = _seed_route(client)

    response = client.put(
        f"/api/process-routes/{route_id}",
        headers=auth_headers,
        json={
            "name": route_name,
            "description": "cross module fixture",
            "category": "结构件",
            "processes": [
                {"process_id": process_ids[2], "required_audit": 1},
                {"process_id": process_ids[0], "required_audit": 0},
            ],
        },
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["synced_orders"] == 0, response.get_json()
    assert response.get_json()["skipped_orders"] == 0, response.get_json()
    assert _route_processes(client, route_id) == [(process_ids[2], 1), (process_ids[0], 0)]


def test_route_update_rejects_order_reference(client, auth_headers):
    route_id, route_name, process_ids = _seed_route(client)
    order_id = _create_order_with_route(client, auth_headers, route_id)

    response = client.put(
        f"/api/process-routes/{route_id}",
        headers=auth_headers,
        json={
            "name": route_name,
            "description": "cross module fixture",
            "category": "结构件",
            "processes": [
                {"process_id": process_ids[2], "required_audit": 1},
                {"process_id": process_ids[0], "required_audit": 0},
            ],
        },
    )

    assert response.status_code == 409, response.get_json()
    assert response.get_json()["code"] == "conflict"
    assert "1 个订单" in response.get_json()["error"]
    assert _route_processes(client, route_id) == [(process_ids[0], 0), (process_ids[1], 0)]
    assert _order_processes(client, order_id) == [(process_ids[0], 0), (process_ids[1], 0)]


def test_route_update_rejects_product_reference(client, auth_headers):
    route_id, route_name, process_ids = _seed_route(client)
    with client.application.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO products (product_name, product_code, model, spec, category, route_id) "
            "VALUES (?, ?, 'TEST', 'Standard', 'fixture', ?)",
            ("Route Locked Product", f"LOCK-{uuid.uuid4().hex[:8].upper()}", route_id),
        )
        db.commit()

    response = client.put(
        f"/api/process-routes/{route_id}",
        headers=auth_headers,
        json={
            "name": route_name,
            "description": "changed description",
            "category": "结构件",
            "processes": [{"process_id": process_ids[2], "required_audit": 1}],
        },
    )

    assert response.status_code == 409, response.get_json()
    assert "1 个产品" in response.get_json()["error"]
    assert _route_processes(client, route_id) == [(process_ids[0], 0), (process_ids[1], 0)]


def test_route_usage_is_exposed_and_recycled_references_stay_locked(client, auth_headers):
    route_id, _, _ = _seed_route(client)
    _create_order_with_route(client, auth_headers, route_id)
    with client.application.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO products "
            "(product_name, product_code, model, spec, category, route_id, deleted_at) "
            "VALUES (?, ?, 'TEST', 'Standard', 'fixture', ?, datetime('now','localtime'))",
            ("Recycled Route Product", f"RECYCLE-{uuid.uuid4().hex[:8].upper()}", route_id),
        )
        db.commit()

    list_response = client.get("/api/process-routes?limit=200", headers=auth_headers)
    assert list_response.status_code == 200, list_response.get_json()
    listed_route = next(route for route in list_response.get_json()["routes"] if route["id"] == route_id)
    assert listed_route["used_orders"] == 1
    assert listed_route["used_products"] == 1
    assert listed_route["is_locked"] is True

    impact_response = client.get(f"/api/process-routes/{route_id}/impact", headers=auth_headers)
    assert impact_response.status_code == 200, impact_response.get_json()
    assert impact_response.get_json()["used_orders"] == 1
    assert impact_response.get_json()["used_products"] == 1
    assert impact_response.get_json()["is_locked"] is True

    delete_response = client.delete(f"/api/process-routes/{route_id}", headers=auth_headers)
    assert delete_response.status_code == 409, delete_response.get_json()
    assert "无法删除" in delete_response.get_json()["error"]


def test_unreferenced_route_can_be_deleted(client, auth_headers):
    route_id, _, _ = _seed_route(client)

    response = client.delete(f"/api/process-routes/{route_id}", headers=auth_headers)

    assert response.status_code == 200, response.get_json()
    with client.application.app_context():
        route = get_db().execute(
            "SELECT id FROM process_routes WHERE id = ?", (route_id,)
        ).fetchone()
    assert route is None


def test_unreported_order_clears_route_and_copied_processes(client, auth_headers):
    route_id, _, process_ids = _seed_route(client)
    order_id = _create_order_with_route(client, auth_headers, route_id)
    assert _order_processes(client, order_id) == [(process_ids[0], 0), (process_ids[1], 0)]

    response = client.put(
        f"/api/orders/{order_id}",
        headers=auth_headers,
        json={"route_id": None},
    )

    assert response.status_code == 200, response.get_json()
    assert _order_route_id(client, order_id) is None
    assert _order_processes(client, order_id) == []


def test_reported_order_rejects_direct_route_change(client, auth_headers):
    route_id, _, process_ids = _seed_route(client)
    order_id = _create_order_with_route(client, auth_headers, route_id)
    alternate_route_id = _seed_alternate_route(client, process_ids[2])

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
        f"/api/orders/{order_id}",
        headers=auth_headers,
        json={"route_id": alternate_route_id},
    )

    assert response.status_code == 400, response.get_json()
    assert "已有 1 条报工记录" in response.get_json()["error"]
    assert _order_route_id(client, order_id) == route_id
    assert _order_processes(client, order_id) == [(process_ids[0], 0), (process_ids[1], 0)]
