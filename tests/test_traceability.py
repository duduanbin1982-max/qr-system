import json
import uuid

import pytest

from factories import (
    TEST_HASH,
    TEST_PASS,
    create_inventory_item,
    create_material,
    create_order,
    ensure_process,
)
from modules.domain.errors import AuthorizationError
from modules.db import get_db
from modules.services.trace_service import TraceService


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
        work_record_ids = []
        for serial_no in serial_numbers:
            cursor = db.execute(
                "INSERT INTO work_records "
                "(order_id, process_id, user_id, type, quantity, serial_no, status) "
                "VALUES (?, ?, ?, 'normal', 1, ?, 'approved')",
                (order_id, process_id, user_id, serial_no),
            )
            work_record_ids.append(cursor.lastrowid)
        db.commit()
        return {
            "order_id": order_id,
            "order_no": order["order_no"],
            "process_id": process_id,
            "user_id": user_id,
            "serial_numbers": serial_numbers,
            "work_record_ids": work_record_ids,
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
    assert "qr_content" not in payload["item"]
    assert "order_id" not in payload["item"]
    assert payload["order"]["order_no"] == fixture["order_no"]
    assert len(payload["work_records"]) == 1
    assert payload["work_records"][0]["quantity"] == 1
    assert set(payload["meta"]["history_evidence"]["counts"]) == {
        "snapshot",
        "version",
        "legacy_fallback",
        "missing",
    }
    assert payload["meta"]["history_evidence"]["has_legacy_fallback"] is True


def test_missing_trace_targets_return_not_found(client, auth_headers):
    missing_serial = client.get(
        "/api/trace/TRACE-MISSING-SERIAL",
        headers=auth_headers,
    )
    missing_order = client.get(
        "/api/trace/order/TRACE-MISSING-ORDER",
        headers=auth_headers,
    )

    assert missing_serial.status_code == 404
    assert missing_serial.get_json() == {
        "error": "产品序列号不存在",
        "code": "not_found",
    }
    assert missing_order.status_code == 404
    assert missing_order.get_json() == {
        "error": "订单不存在",
        "code": "not_found",
    }


def test_serial_trace_hides_soft_deleted_order(client, auth_headers):
    fixture = _create_serial_trace_fixture(client)

    with client.application.app_context():
        db = get_db()
        db.execute(
            "UPDATE orders SET deleted_at = datetime('now','localtime') WHERE id = ?",
            (fixture["order_id"],),
        )
        db.commit()

    response = client.get(
        f"/api/trace/{fixture['serial_numbers'][0]}",
        headers=auth_headers,
    )

    assert response.status_code == 404
    assert response.get_json() == {
        "error": "产品序列号不存在",
        "code": "not_found",
    }

    with client.application.app_context():
        db = get_db()
        db.execute(
            "UPDATE orders SET deleted_at = '' WHERE id = ?",
            (fixture["order_id"],),
        )
        db.commit()

    empty_marker_response = client.get(
        f"/api/trace/{fixture['serial_numbers'][0]}",
        headers=auth_headers,
    )
    assert empty_marker_response.status_code == 404


def test_serial_trace_keeps_orphan_product_item_semantics(client, auth_headers):
    serial_no = f"TRACE-ORPHAN-{uuid.uuid4().hex[:8].upper()}"
    with client.application.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO product_items "
            "(serial_no, order_id, position_no, qr_content, status) "
            "VALUES (?, NULL, 1, '{}', 'in_progress')",
            (serial_no,),
        )
        db.commit()

    response = client.get(f"/api/trace/{serial_no}", headers=auth_headers)

    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert payload["item"]["serial_no"] == serial_no
    assert payload["order"] is None
    assert payload["order_scope"] == {
        "rework_records": [],
        "manual_material_consumptions": [],
        "inventory_logs": [],
        "shipments": [],
    }


def test_trace_routes_require_trace_view_permission(client, worker_auth_headers):
    response = client.get(
        "/api/trace/TRACE-MISSING-SERIAL",
        headers=worker_auth_headers,
    )

    assert response.status_code == 403


def test_trace_service_denies_orders_outside_process_scope(client):
    fixture = _create_serial_trace_fixture(client)

    with client.application.app_context():
        with pytest.raises(AuthorizationError):
            TraceService.trace_by_order(
                fixture["order_no"],
                data_scope_pids=[],
            )


def test_trace_routes_enforce_object_process_scope(client):
    allowed = _create_serial_trace_fixture(client)
    denied = _create_serial_trace_fixture(client)
    suffix = uuid.uuid4().hex[:8]
    username = f"trace_scope_{suffix}"
    with client.application.app_context():
        db = get_db()
        role_code = f"trace_scope_role_{suffix}"
        role_id = db.execute(
            "INSERT INTO roles (name, code, description, permissions, status, level) "
            "VALUES (?, ?, 'trace scope fixture', ?, 'active', 1)",
            (
                f"Trace Scope {suffix}",
                role_code,
                json.dumps(["trace:view"], ensure_ascii=False),
            ),
        ).lastrowid
        user_id = db.execute(
            "INSERT INTO users "
            "(username, password, name, role, status, password_version, employee_no) "
            "VALUES (?, ?, ?, ?, 'active', 2, ?)",
            (
                username,
                TEST_HASH,
                f"Trace Scope {suffix}",
                role_code,
                f"TRACE-SCOPE-{suffix.upper()}",
            ),
        ).lastrowid
        db.execute(
            "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
            (user_id, role_id),
        )
        db.execute(
            "INSERT INTO user_processes (user_id, process_id) VALUES (?, ?)",
            (user_id, allowed["process_id"]),
        )
        db.commit()

    login = client.post(
        "/api/auth/login",
        json={"username": username, "password": TEST_PASS},
    )
    assert login.status_code == 200, login.get_json()
    headers = {"Authorization": f"Bearer {login.get_json()['user']['token']}"}

    allowed_response = client.get(
        f"/api/trace/{allowed['serial_numbers'][0]}",
        headers=headers,
    )
    denied_serial = client.get(
        f"/api/trace/{denied['serial_numbers'][0]}",
        headers=headers,
    )
    denied_order = client.get(
        f"/api/trace/order/{denied['order_no']}",
        headers=headers,
    )

    assert allowed_response.status_code == 200, allowed_response.get_json()
    assert denied_serial.status_code == 403
    assert denied_order.status_code == 403

    with client.application.app_context():
        db = get_db()
        db.execute(
            "UPDATE orders SET deleted_at = datetime('now','localtime') WHERE id = ?",
            (allowed["order_id"],),
        )
        db.commit()

    archived_serial = client.get(
        f"/api/trace/{allowed['serial_numbers'][0]}",
        headers=headers,
    )
    assert archived_serial.status_code == 404
    assert archived_serial.get_json() == {
        "error": "产品序列号不存在",
        "code": "not_found",
    }


def test_order_trace_uses_public_dtos_snapshot_and_database_pagination(
    client,
    auth_headers,
):
    fixture = _create_serial_trace_fixture(client, serial_count=3)

    response = client.get(
        f"/api/trace/order/{fixture['order_no']}?page=2&per_page=1"
        "&work_records_page=2&work_records_per_page=1",
        headers=auth_headers,
    )

    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert set(payload["order"]) == {
        "order_no",
        "customer",
        "product_name",
        "product_code",
        "quantity",
        "completed",
        "scrapped",
        "rework",
        "status",
        "plan_start",
        "plan_end",
        "deadline",
        "remark",
        "qr_mode",
        "delivery_status",
        "created_at",
        "updated_at",
    }
    assert [item["serial_no"] for item in payload["items"]] == [
        fixture["serial_numbers"][1]
    ]
    assert "qr_content" not in payload["items"][0]
    assert "order_id" not in payload["items"][0]
    assert "process_id" not in payload["work_records"][0]
    assert "process_version_id" not in payload["work_records"][0]
    assert [record["serial_no"] for record in payload["work_records"]] == [
        fixture["serial_numbers"][1]
    ]
    assert payload["meta"]["scope"] == "order"
    assert payload["meta"]["snapshot_at"]
    assert payload["meta"]["page"] == 2
    assert payload["meta"]["per_page"] == 1
    assert payload["meta"]["total_pages"] == 3
    assert payload["meta"]["totals"]["items"] == 3
    assert payload["meta"]["totals"]["work_records"] == 3
    assert payload["meta"]["pagination"]["items"] == {
        "page": 2,
        "per_page": 1,
        "total": 3,
        "total_pages": 3,
    }
    assert payload["meta"]["pagination"]["work_records"]["page"] == 2


def test_order_trace_history_evidence_covers_records_beyond_current_page(
    client,
    auth_headers,
):
    fixture = _create_serial_trace_fixture(client)

    with client.application.app_context():
        db = get_db()
        process_version_id = db.execute(
            "SELECT current_effective_version_id FROM processes WHERE id = ?",
            (fixture["process_id"],),
        ).fetchone()["current_effective_version_id"]
        db.execute(
            "UPDATE work_records SET process_version_id = ? WHERE id = ?",
            (process_version_id, fixture["work_record_ids"][0]),
        )
        for index in range(99):
            db.execute(
                "INSERT INTO work_records "
                "(order_id, process_id, process_version_id, user_id, type, quantity, status) "
                "VALUES (?, ?, ?, ?, 'normal', 1, 'approved')",
                (
                    fixture["order_id"],
                    fixture["process_id"],
                    process_version_id,
                    fixture["user_id"],
                ),
            )
        db.execute(
            "INSERT INTO work_records "
            "(order_id, process_id, user_id, type, quantity, status) "
            "VALUES (?, ?, ?, 'normal', 1, 'approved')",
            (fixture["order_id"], fixture["process_id"], fixture["user_id"]),
        )
        db.commit()

    response = client.get(
        f"/api/trace/order/{fixture['order_no']}?per_page=100",
        headers=auth_headers,
    )

    assert response.status_code == 200, response.get_json()
    evidence = response.get_json()["meta"]["history_evidence"]
    assert evidence["scope"] == "full_order"
    assert evidence["page_counts"]["legacy_fallback"] == 0
    assert evidence["counts"]["legacy_fallback"] == 1
    assert evidence["has_legacy_fallback"] is True


def test_order_trace_rejects_invalid_pagination(client, auth_headers):
    fixture = _create_serial_trace_fixture(client)

    response = client.get(
        f"/api/trace/order/{fixture['order_no']}?page=0&per_page=201",
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "validation_error"


def test_serial_trace_separates_item_and_order_scope(client, auth_headers):
    fixture = _create_serial_trace_fixture(client, serial_count=2)
    suffix = uuid.uuid4().hex[:8].upper()
    with client.application.app_context():
        db = get_db()
        material_id = create_material(db, name=f"Trace Material {suffix}")
        for index, serial_no in enumerate(fixture["serial_numbers"]):
            task = db.execute(
                "INSERT INTO quality_inspection_tasks "
                "(task_no, trigger_key, order_id, process_id, serial_no, inspection_type) "
                "VALUES (?, ?, ?, ?, ?, 'process')",
                (
                    f"TRACE-TASK-{suffix}-{index}",
                    f"trace-task-{suffix}-{index}",
                    fixture["order_id"],
                    fixture["process_id"],
                    serial_no,
                ),
            )
            inspection = db.execute(
                "INSERT INTO quality_inspections "
                "(order_id, process_id, inspector_id, serial_no, task_id, result) "
                "VALUES (?, ?, ?, ?, ?, 'pass')",
                (
                    fixture["order_id"],
                    fixture["process_id"],
                    fixture["user_id"],
                    serial_no,
                    task.lastrowid,
                ),
            )
            ncr = db.execute(
                "INSERT INTO quality_nonconformances "
                "(ncr_no, task_id, inspection_id, order_id, process_id, serial_no) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    f"TRACE-NCR-{suffix}-{index}",
                    task.lastrowid,
                    inspection.lastrowid,
                    fixture["order_id"],
                    fixture["process_id"],
                    serial_no,
                ),
            )
            db.execute(
                "INSERT INTO quality_capa_records (capa_no, ncr_id, title) VALUES (?, ?, ?)",
                (f"TRACE-CAPA-{suffix}-{index}", ncr.lastrowid, f"CAPA {index}"),
            )
            db.execute(
                "INSERT INTO material_consumptions "
                "(material_id, order_id, process_id, quantity, source_work_record_id) "
                "VALUES (?, ?, ?, 1, ?)",
                (
                    material_id,
                    fixture["order_id"],
                    fixture["process_id"],
                    fixture["work_record_ids"][index],
                ),
            )
        manual_consumption = db.execute(
            "INSERT INTO material_consumptions "
            "(material_id, order_id, process_id, quantity, notes) VALUES (?, ?, ?, 2, 'manual')",
            (material_id, fixture["order_id"], fixture["process_id"]),
        )
        db.commit()

    response = client.get(
        f"/api/trace/{fixture['serial_numbers'][0]}",
        headers=auth_headers,
    )

    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    serial_scope = payload["serial_scope"]
    assert len(serial_scope["work_records"]) == 1
    assert [row["serial_no"] for row in serial_scope["quality_inspections"]] == [
        fixture["serial_numbers"][0]
    ]
    assert [row["serial_no"] for row in serial_scope["quality_tasks"]] == [
        fixture["serial_numbers"][0]
    ]
    assert [row["serial_no"] for row in serial_scope["quality_nonconformances"]] == [
        fixture["serial_numbers"][0]
    ]
    assert len(serial_scope["quality_capa"]) == 1
    assert serial_scope["quality_capa"][0]["capa_no"] == f"TRACE-CAPA-{suffix}-0"
    assert "source_work_record_id" not in serial_scope["material_consumptions"][0]
    assert [row["id"] for row in payload["order_scope"]["manual_material_consumptions"]] == [
        manual_consumption.lastrowid
    ]


def test_serial_trace_returns_complete_order_scope_lifecycle(client, auth_headers):
    fixture = _create_serial_trace_fixture(client)
    suffix = uuid.uuid4().hex[:8].upper()
    with client.application.app_context():
        db = get_db()
        inventory_id = create_inventory_item(
            db,
            order_id=fixture["order_id"],
            product_model=f"TRACE-INV-{suffix}",
            product_name="Trace Inventory Product",
        )
        rework = db.execute(
            "INSERT INTO rework_records (order_id, process_id, user_id, quantity, reason) "
            "VALUES (?, ?, ?, 1, 'trace lifecycle')",
            (fixture["order_id"], fixture["process_id"], fixture["user_id"]),
        )
        inventory_log = db.execute(
            "INSERT INTO inventory_logs "
            "(inventory_id, type, quantity, order_id, order_no, operator_id, operator_name) "
            "VALUES (?, 'in', 1, ?, ?, ?, 'Trace Operator')",
            (
                inventory_id,
                fixture["order_id"],
                fixture["order_no"],
                fixture["user_id"],
            ),
        )
        shipment_ids = []
        for index in range(11):
            shipment = db.execute(
                "INSERT INTO shipments "
                "(shipment_no, customer, status, total_quantity) VALUES (?, 'Trace Customer', 'completed', 1)",
                (f"TRACE-SHIP-{suffix}-{index:02d}",),
            )
            shipment_ids.append(shipment.lastrowid)
            db.execute(
                "INSERT INTO shipment_items "
                "(shipment_id, inventory_id, product_model, product_name, quantity, order_id, order_no) "
                "VALUES (?, ?, ?, 'Trace Inventory Product', 1, ?, ?)",
                (
                    shipment.lastrowid,
                    inventory_id,
                    f"TRACE-INV-{suffix}",
                    fixture["order_id"],
                    fixture["order_no"],
                ),
            )
        db.commit()

    response = client.get(
        f"/api/trace/{fixture['serial_numbers'][0]}",
        headers=auth_headers,
    )

    assert response.status_code == 200, response.get_json()
    order_scope = response.get_json()["order_scope"]
    assert [row["id"] for row in order_scope["rework_records"]] == [rework.lastrowid]
    assert [row["id"] for row in order_scope["inventory_logs"]] == [inventory_log.lastrowid]
    assert order_scope["inventory_logs"][0]["product_model"] == f"TRACE-INV-{suffix}"
    assert len(order_scope["shipments"]) == 11
    assert {row["id"] for row in order_scope["shipments"]} == set(shipment_ids)
    assert all(row["order_quantity"] == 1 for row in order_scope["shipments"])
