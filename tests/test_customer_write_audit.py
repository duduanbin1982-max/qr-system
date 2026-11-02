"""Customer writes must commit their mandatory audit and business data together."""

import json
import sqlite3

import pytest

from modules.audit_writer import AuditCommand
from modules.db import get_db
from modules.db_unit_of_work import BaseService
from modules.repositories.audit_log_repository import AuditLogRepository
from modules.repositories.customer_repository import CustomerRepository
from modules.services.customer_service import CustomerService
from test_customers import _create_permission_user, _seed_customer_orders


OPERATIONS = ("create", "update", "delete")
CUSTOMER_PAYLOAD = {
    "name": "Audit Customer Changed",
    "contact": "Private Contact",
    "phone": "13900001111",
    "email": "private@example.com",
    "address": "Private Customer Address",
    "remark": "Private Customer Remark",
    "tags": "VIP,VIP,重点",
}


def _prepare_write(client, operation):
    customer_id, _, order_ids = _seed_customer_orders(client)
    if operation == "delete":
        with client.application.app_context():
            db = get_db()
            db.execute(
                "UPDATE orders SET deleted_at = datetime('now') WHERE customer_id = ?",
                (customer_id,),
            )
            db.commit()
    return customer_id, order_ids


def _write(client, operation, customer_id, headers):
    if operation == "create":
        return client.post("/api/customers", json=CUSTOMER_PAYLOAD, headers=headers)
    if operation == "update":
        return client.put(
            f"/api/customers/{customer_id}",
            json=CUSTOMER_PAYLOAD,
            headers=headers,
        )
    return client.delete(f"/api/customers/{customer_id}", headers=headers)


def _business_snapshot(client):
    with client.application.app_context():
        db = get_db()
        assert not db.in_transaction
        return {
            "customers": [
                dict(row) for row in db.execute("SELECT * FROM customers ORDER BY id")
            ],
            "orders": [
                dict(row) for row in db.execute(
                    "SELECT id, customer_id, customer, deleted_at FROM orders ORDER BY id"
                )
            ],
        }


def _customer_audits(client):
    with client.application.app_context():
        return [
            dict(row) for row in get_db().execute(
                "SELECT * FROM audit_logs WHERE target_type = 'customer' ORDER BY id"
            )
        ]


def _actor_id(client, headers):
    with client.application.app_context():
        return get_db().execute(
            "SELECT id FROM users WHERE token = ?",
            (headers["Authorization"].removeprefix("Bearer "),),
        ).fetchone()["id"]


@pytest.mark.parametrize("operation", OPERATIONS)
def test_customer_write_commits_one_required_audit(
    client, auth_headers, monkeypatch, operation,
):
    customer_id, order_ids = _prepare_write(client, operation)
    actor_id = _actor_id(client, auth_headers)
    observed_connections = []
    original_insert = AuditLogRepository.insert_command

    def insert_in_business_transaction(command, *, db):
        if command.target_type == "customer":
            assert db.in_transaction
            assert BaseService.is_in_transaction(db)
            observed_connections.append(db)
        return original_insert(command, db=db)

    monkeypatch.setattr(
        AuditLogRepository, "insert_command",
        staticmethod(insert_in_business_transaction),
    )
    response = _write(
        client,
        operation,
        customer_id,
        {**auth_headers, "X-Request-ID": "customer-request-" + "r" * 140},
    )

    assert response.status_code == 200
    assert response.get_json()["message"] == {
        "create": "创建成功", "update": "更新成功", "delete": "删除成功",
    }[operation]
    if operation == "create":
        customer_id = response.get_json()["id"]
    audits = _customer_audits(client)
    assert len(audits) == 1
    assert len(observed_connections) == 1
    audit = audits[0]
    assert audit["user_id"] == actor_id
    assert audit["action"] == f"{operation}_customer"
    assert audit["target_id"] == customer_id
    assert audit["mandatory"] == 1
    assert audit["event_id"]
    assert audit["request_id"] == ("customer-request-" + "r" * 140)[:120]
    if operation == "delete":
        assert audit["detail"] == ""
    else:
        assert json.loads(audit["detail"]) == {
            "changed_fields": sorted(CUSTOMER_PAYLOAD),
        }
        for private_value in CUSTOMER_PAYLOAD.values():
            assert private_value not in audit["detail"]
    with client.application.app_context():
        db = get_db()
        customer = CustomerRepository.find_by_id(customer_id, db=db)
        if operation == "delete":
            assert customer is None
            orders = db.execute(
                "SELECT customer_id, customer FROM orders WHERE id IN (?, ?)",
                order_ids,
            ).fetchall()
            assert all(row["customer_id"] is None for row in orders)
            assert all(row["customer"] for row in orders)
        else:
            assert customer["name"] == CUSTOMER_PAYLOAD["name"]
            assert customer["tags"] == "VIP,重点"
            if operation == "update":
                orders = db.execute(
                    "SELECT customer FROM orders WHERE customer_id = ?",
                    (customer_id,),
                ).fetchall()
                assert len(orders) == 2
                assert all(row["customer"] == CUSTOMER_PAYLOAD["name"] for row in orders)


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize(
    "failure",
    ("prepare", "runtime", "integrity", "storage", "after_insert"),
)
def test_customer_audit_failure_rolls_back_business_and_returns_generic_500(
    client, auth_headers, monkeypatch, operation, failure,
):
    customer_id, _ = _prepare_write(client, operation)
    before = _business_snapshot(client)
    before_audits = _customer_audits(client)
    monkeypatch.setitem(client.application.config, "PROPAGATE_EXCEPTIONS", False)
    original_insert = AuditLogRepository.insert_command
    original_prepare = AuditCommand.create

    def fail_prepare(*args, **kwargs):
        if len(args) > 2 and args[2] == "customer":
            raise RuntimeError("sensitive audit command preparation detail")
        return original_prepare(*args, **kwargs)

    def fail_insert(command, *, db):
        if command.target_type != "customer":
            return original_insert(command, db=db)
        assert db.in_transaction
        assert BaseService.is_in_transaction(db)
        if failure == "after_insert":
            original_insert(command, db=db)
        error_type = {
            "integrity": sqlite3.IntegrityError,
            "storage": sqlite3.OperationalError,
        }.get(failure, RuntimeError)
        raise error_type("sensitive customer audit storage failure")

    if failure == "prepare":
        monkeypatch.setattr(AuditCommand, "create", staticmethod(fail_prepare))
    else:
        monkeypatch.setattr(
            AuditLogRepository, "insert_command", staticmethod(fail_insert),
        )

    response = _write(client, operation, customer_id, auth_headers)

    assert response.status_code == 500
    assert response.get_json() == {"error": "服务器内部错误，请稍后重试"}
    assert _business_snapshot(client) == before
    assert _customer_audits(client) == before_audits
    assert not BaseService.is_in_transaction()


@pytest.mark.parametrize("operation", OPERATIONS)
def test_customer_business_failure_rolls_back_without_success_audit(
    client, auth_headers, monkeypatch, operation,
):
    customer_id, _ = _prepare_write(client, operation)
    before = _business_snapshot(client)
    monkeypatch.setitem(client.application.config, "PROPAGATE_EXCEPTIONS", False)
    repository_method = {
        "create": "insert",
        "update": "cascade_name_to_orders",
        "delete": "delete",
    }[operation]
    original = getattr(CustomerRepository, repository_method)

    def write_then_fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("customer business storage failure")

    monkeypatch.setattr(CustomerRepository, repository_method, staticmethod(write_then_fail))

    response = _write(client, operation, customer_id, auth_headers)

    assert response.status_code == 500
    assert _business_snapshot(client) == before
    assert _customer_audits(client) == []


@pytest.mark.parametrize("operation", OPERATIONS)
def test_customer_real_audit_constraint_failure_rolls_back(
    client, auth_headers, monkeypatch, operation,
):
    customer_id, _ = _prepare_write(client, operation)
    before = _business_snapshot(client)
    monkeypatch.setitem(client.application.config, "PROPAGATE_EXCEPTIONS", False)
    with client.application.app_context():
        db = get_db()
        db.execute(
            "CREATE TRIGGER reject_customer_audit BEFORE INSERT ON audit_logs "
            "WHEN NEW.target_type = 'customer' "
            "BEGIN SELECT RAISE(ABORT, 'customer audit constraint failure'); END"
        )
        db.commit()

    response = _write(client, operation, customer_id, auth_headers)

    assert response.status_code == 500
    assert response.get_json() == {"error": "服务器内部错误，请稍后重试"}
    assert _business_snapshot(client) == before
    assert _customer_audits(client) == []


@pytest.mark.parametrize("operation", OPERATIONS)
def test_customer_actual_readonly_failure_at_audit_write_rolls_back(
    client, auth_headers, monkeypatch, operation,
):
    customer_id, _ = _prepare_write(client, operation)
    before = _business_snapshot(client)
    monkeypatch.setitem(client.application.config, "PROPAGATE_EXCEPTIONS", False)
    original_insert = AuditLogRepository.insert_command

    def disable_writes_at_audit(command, *, db):
        if command.target_type == "customer":
            db.execute("PRAGMA query_only = ON")
        return original_insert(command, db=db)

    monkeypatch.setattr(
        AuditLogRepository, "insert_command", staticmethod(disable_writes_at_audit),
    )

    response = _write(client, operation, customer_id, auth_headers)

    assert response.status_code == 500
    assert response.get_json() == {"error": "服务器内部错误，请稍后重试"}
    assert _business_snapshot(client) == before
    assert _customer_audits(client) == []


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("actor_id", (None, 0, -1, True, "1000", 1.5))
def test_customer_service_rejects_invalid_actor_before_mutating(
    client, operation, actor_id,
):
    customer_id, _ = _prepare_write(client, operation)
    before = _business_snapshot(client)
    with client.application.app_context(), pytest.raises(ValueError, match="有效操作人"):
        if operation == "create":
            CustomerService.create_customer(dict(CUSTOMER_PAYLOAD), actor_id=actor_id)
        elif operation == "update":
            CustomerService.update_customer(
                customer_id, dict(CUSTOMER_PAYLOAD), actor_id=actor_id,
            )
        else:
            CustomerService.delete_customer(customer_id, actor_id=actor_id)

    assert _business_snapshot(client) == before
    assert _customer_audits(client) == []


@pytest.mark.parametrize("operation", OPERATIONS)
def test_customer_service_requires_actor_keyword(client, operation):
    customer_id, _ = _prepare_write(client, operation)
    before = _business_snapshot(client)
    with client.application.app_context(), pytest.raises(TypeError, match="actor_id"):
        if operation == "create":
            CustomerService.create_customer(dict(CUSTOMER_PAYLOAD))
        elif operation == "update":
            CustomerService.update_customer(customer_id, dict(CUSTOMER_PAYLOAD))
        else:
            CustomerService.delete_customer(customer_id)
    assert _business_snapshot(client) == before
    assert _customer_audits(client) == []


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("access", ("unauthenticated", "forbidden"))
def test_customer_write_authorization_denial_has_no_write_or_success_audit(
    client, operation, access,
):
    customer_id, _ = _prepare_write(client, operation)
    headers = (
        {"Authorization": "Bearer not-a-valid-customer-session"}
        if access == "unauthenticated"
        else _create_permission_user(client, ["customers:view"])
    )
    before = _business_snapshot(client)
    response = _write(client, operation, customer_id, headers)

    assert response.status_code == (401 if access == "unauthenticated" else 403)
    assert _business_snapshot(client) == before
    assert _customer_audits(client) == []


@pytest.mark.parametrize("scope", ("no_order_permission", "empty", "partial", "global"))
def test_customer_delete_blocks_global_association_without_order_details(
    client, auth_headers, scope,
):
    customer_id, process_ids, order_ids = _seed_customer_orders(client)
    if scope == "global":
        headers = auth_headers
    else:
        permissions = ["customers:view", "customers:delete"]
        if scope != "no_order_permission":
            permissions.append("orders:view")
        headers = _create_permission_user(client, permissions)
        if scope in ("empty", "partial"):
            actor_id = _actor_id(client, headers)
            with client.application.app_context():
                db = get_db()
                db.execute(
                    "UPDATE users SET process_ids = ? WHERE id = ?",
                    ("-1" if scope == "empty" else str(process_ids[0]), actor_id),
                )
                db.commit()
    before = _business_snapshot(client)

    history = client.get(f"/api/customers/{customer_id}/orders", headers=headers)
    if scope == "no_order_permission":
        assert history.status_code == 403
    else:
        assert history.status_code == 200
        expected_ids = {
            "empty": set(), "partial": {order_ids[0]}, "global": set(order_ids),
        }[scope]
        assert {row["id"] for row in history.get_json()["orders"]} == expected_ids

    response = client.delete(f"/api/customers/{customer_id}", headers=headers)

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "无法删除：该客户存在关联订单，请先处理订单",
    }
    assert _business_snapshot(client) == before
    assert _customer_audits(client) == []


def test_customer_delete_checks_existence_and_order_blocker_inside_transaction(
    client, auth_headers, monkeypatch,
):
    customer_id, _, _ = _seed_customer_orders(client)
    observed = []
    for method_name in ("find_by_id", "count_active_orders"):
        original = getattr(CustomerRepository, method_name)

        def observe(*args, _original=original, **kwargs):
            db = kwargs["db"]
            assert db.in_transaction
            assert BaseService.is_in_transaction(db)
            observed.append(db)
            return _original(*args, **kwargs)

        monkeypatch.setattr(CustomerRepository, method_name, staticmethod(observe))

    response = client.delete(f"/api/customers/{customer_id}", headers=auth_headers)

    assert response.status_code == 400
    assert len(observed) == 2
    assert observed[0] is observed[1]


def test_customer_delete_missing_preserves_legacy_400_without_success_audit(
    client, auth_headers,
):
    response = client.delete("/api/customers/999999999", headers=auth_headers)

    assert response.status_code == 400
    assert response.get_json() == {"error": "客户不存在"}
    assert _customer_audits(client) == []


@pytest.mark.parametrize(
    "method, payload",
    (("post", {"name": "   "}), ("put", {"name": "   "}), ("put", {})),
)
def test_customer_invalid_write_keeps_validation_response_without_audit(
    client, auth_headers, method, payload,
):
    customer_id, _ = _prepare_write(client, "update")
    before = _business_snapshot(client)
    response = getattr(client, method)(
        "/api/customers" if method == "post" else f"/api/customers/{customer_id}",
        json=payload,
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert _business_snapshot(client) == before
    assert _customer_audits(client) == []
