import json
import uuid

from factories import TEST_HASH, TEST_PASS
from modules.db import get_db
from modules.repositories.customer_repository import CustomerRepository
from modules.services.customer_service import CustomerService


def _login_headers(client, username, password=TEST_PASS):
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200, response.get_json()
    token = response.get_json()["user"]["token"]
    return {"Authorization": f"Bearer {token}"}


def _create_permission_user(client, permissions):
    suffix = uuid.uuid4().hex[:8]
    username = f"customer_perm_{suffix}"
    role_code = f"customer_perm_{suffix}"
    with client.application.app_context():
        db = get_db()
        role_id = db.execute(
            "INSERT INTO roles (name, code, description, permissions, status, level) "
            "VALUES (?, ?, 'pytest customer permission role', ?, 'active', 1)",
            (
                f"Customer Permission {suffix}",
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
                f"Customer Permission {suffix}",
                role_code,
                f"TEST-CUSTOMER-{suffix.upper()}",
            ),
        ).lastrowid
        db.execute(
            "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
            (user_id, role_id),
        )
        db.commit()
    return _login_headers(client, username)


def _seed_customer_orders(client):
    suffix = uuid.uuid4().hex[:8].upper()
    with client.application.app_context():
        db = get_db()
        customer_id = db.execute(
            "INSERT INTO customers (name, contact) VALUES (?, 'Customer Contact')",
            (f"Customer Scope {suffix}",),
        ).lastrowid
        process_ids = []
        for index in (1, 2):
            process_ids.append(db.execute(
                "INSERT INTO processes "
                "(name, description, category, seq_order, status, updated_at) "
                "VALUES (?, 'customer scope fixture', 'fixture', ?, 'active', datetime('now','localtime'))",
                (f"Customer Scope Process {suffix}-{index}", 9000 + index),
            ).lastrowid)
        order_ids = []
        for index, process_id in enumerate(process_ids, start=1):
            order_id = db.execute(
                "INSERT INTO orders "
                "(order_no, customer, customer_id, product_name, product_code, quantity, status) "
                "VALUES (?, ?, ?, 'Customer Product', ?, 2, 'producing')",
                (
                    f"TEST-CUSTOMER-{suffix}-{index}",
                    f"Customer Scope {suffix}",
                    customer_id,
                    f"CUSTOMER-{suffix}-{index}",
                ),
            ).lastrowid
            db.execute(
                "INSERT INTO order_processes "
                "(order_id, process_id, seq_order, status, completed) "
                "VALUES (?, ?, 1, 'pending', 0)",
                (order_id, process_id),
            )
            order_ids.append(order_id)
        db.execute(
            "INSERT INTO order_processes "
            "(order_id, process_id, seq_order, status, completed) "
            "VALUES (?, ?, 2, 'pending', 0)",
            (order_ids[0], process_ids[1]),
        )
        db.commit()
    return customer_id, process_ids, order_ids


def test_customer_order_history_requires_order_view_permission(client, auth_headers):
    customer_id, _, order_ids = _seed_customer_orders(client)
    customer_headers = _create_permission_user(client, ["customers:view"])

    list_response = client.get("/api/customers", headers=customer_headers)
    detail_response = client.get(
        f"/api/customers/{customer_id}/orders",
        headers=customer_headers,
    )
    admin_response = client.get(
        f"/api/customers/{customer_id}/orders",
        headers=auth_headers,
    )

    assert list_response.status_code == 200
    customer = next(
        item for item in list_response.get_json()["customers"]
        if item["id"] == customer_id
    )
    assert customer["order_count"] == 0
    assert customer["last_order_date"] is None
    assert detail_response.status_code == 403
    assert {item["id"] for item in admin_response.get_json()["orders"]} == set(order_ids)


def test_customer_order_history_filters_orders_and_processes_by_scope(client):
    customer_id, process_ids, order_ids = _seed_customer_orders(client)

    with client.application.app_context():
        result = CustomerService.get_customer_orders(
            customer_id,
            data_scope_pids=[process_ids[0]],
        )

    assert [item["id"] for item in result["orders"]] == [order_ids[0]]
    assert [item["process_id"] for item in result["orders"][0]["processes"]] == [process_ids[0]]


def test_update_missing_customer_returns_not_found_without_success_audit(
    client,
    auth_headers,
):
    missing_id = 999999999

    response = client.put(
        f"/api/customers/{missing_id}",
        json={"contact": "Missing Customer"},
        headers=auth_headers,
    )

    assert response.status_code == 404
    assert response.get_json()["error"] == "客户不存在"
    with client.application.app_context():
        audit = get_db().execute(
            "SELECT id FROM audit_logs "
            "WHERE action = 'update_customer' AND target_id = ?",
            (missing_id,),
        ).fetchone()
    assert audit is None


def test_create_customer_maps_unique_constraint_race_to_conflict(
    client,
    auth_headers,
    monkeypatch,
):
    customer_name = f"Race Customer {uuid.uuid4().hex[:8]}"
    with client.application.app_context():
        db = get_db()
        db.execute("INSERT INTO customers (name) VALUES (?)", (customer_name,))
        db.commit()

    monkeypatch.setattr(
        CustomerRepository,
        "find_by_name",
        staticmethod(lambda name, db=None: None),
    )
    response = client.post(
        "/api/customers",
        json={"name": customer_name},
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert response.get_json()["error"] == "客户名称已存在"


def test_update_customer_maps_unique_constraint_race_to_conflict(
    client,
    auth_headers,
    monkeypatch,
):
    suffix = uuid.uuid4().hex[:8]
    with client.application.app_context():
        db = get_db()
        first_name = f"First Customer {suffix}"
        first_id = db.execute(
            "INSERT INTO customers (name) VALUES (?)",
            (first_name,),
        ).lastrowid
        second_id = db.execute(
            "INSERT INTO customers (name) VALUES (?)",
            (f"Second Customer {suffix}",),
        ).lastrowid
        db.commit()
    assert first_id != second_id

    monkeypatch.setattr(
        CustomerRepository,
        "find_by_name_excluding",
        staticmethod(lambda name, exclude_id, db=None: None),
    )
    response = client.put(
        f"/api/customers/{second_id}",
        json={"name": first_name},
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert response.get_json()["error"] == "客户名称已存在"
