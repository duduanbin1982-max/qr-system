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
from modules.domain.errors import AuthorizationError, ValidationError
from modules.db import get_db
from modules.repositories.trace_repository import TraceRepository
from modules.services.trace_service import TraceService


TRACE_COLLECTIONS = (
    "items",
    "work_records",
    "rework_records",
    "quality_inspections",
    "quality_tasks",
    "quality_nonconformances",
    "quality_capa",
    "material_consumptions",
    "inventory_logs",
    "shipments",
)


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


def test_order_trace_quality_inspection_pages_do_not_expand_for_multiple_ncrs(
    client,
    auth_headers,
):
    fixture = _create_serial_trace_fixture(client)

    with client.application.app_context():
        db = get_db()
        inspection_ids = []
        for index in range(2):
            cursor = db.execute(
                "INSERT INTO quality_inspections "
                "(order_id, process_id, inspection_type, result, created_at) "
                "VALUES (?, ?, 'in_process', 'fail', ?)",
                (
                    fixture["order_id"],
                    fixture["process_id"],
                    f"2026-11-04 00:00:0{index}",
                ),
            )
            inspection_ids.append(cursor.lastrowid)

        db.execute(
            "INSERT INTO quality_nonconformances "
            "(ncr_no, inspection_id, order_id) VALUES (?, ?, ?)",
            ("TRACE-NCR-FIRST", inspection_ids[0], fixture["order_id"]),
        )
        db.execute(
            "INSERT INTO quality_nonconformances "
            "(ncr_no, inspection_id, order_id) VALUES (?, ?, ?)",
            ("TRACE-NCR-LATEST", inspection_ids[0], fixture["order_id"]),
        )
        db.execute(
            "INSERT INTO quality_nonconformances "
            "(ncr_no, inspection_id, order_id) VALUES (?, ?, ?)",
            ("TRACE-NCR-SECOND", inspection_ids[1], fixture["order_id"]),
        )
        db.commit()

    first_page = client.get(
        f"/api/trace/order/{fixture['order_no']}?"
        "quality_inspections_page=1&quality_inspections_per_page=1",
        headers=auth_headers,
    )
    second_page = client.get(
        f"/api/trace/order/{fixture['order_no']}?"
        "quality_inspections_page=2&quality_inspections_per_page=1",
        headers=auth_headers,
    )

    assert first_page.status_code == 200, first_page.get_json()
    assert second_page.status_code == 200, second_page.get_json()
    first_payload = first_page.get_json()
    second_payload = second_page.get_json()
    assert [row["id"] for row in first_payload["quality_inspections"]] == [
        inspection_ids[0]
    ]
    assert [row["id"] for row in second_payload["quality_inspections"]] == [
        inspection_ids[1]
    ]
    assert first_payload["quality_inspections"][0]["ncr_no"] == "TRACE-NCR-LATEST"
    assert first_payload["meta"]["pagination"]["quality_inspections"] == {
        "page": 1,
        "per_page": 1,
        "total": 2,
        "total_pages": 2,
    }
    assert second_payload["meta"]["pagination"]["quality_inspections"] == {
        "page": 2,
        "per_page": 1,
        "total": 2,
        "total_pages": 2,
    }


@pytest.mark.parametrize(
    ("parameter", "value"),
    (
        ("quality_inspections_page", "not-an-integer"),
        ("work_records_per_page", "25.5"),
    ),
)
def test_order_trace_rejects_malformed_collection_pagination(
    client,
    auth_headers,
    parameter,
    value,
):
    fixture = _create_serial_trace_fixture(client)

    response = client.get(
        f"/api/trace/order/{fixture['order_no']}?{parameter}={value}",
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "error": "分页参数必须是整数",
        "code": "validation_error",
    }


@pytest.mark.parametrize(
    "parameter",
    ("page", "per_page")
    + tuple(
        f"{name}_{suffix}"
        for name in TRACE_COLLECTIONS
        for suffix in ("page", "per_page")
    ),
)
def test_order_trace_validates_raw_pagination_before_queries(
    client, auth_headers, monkeypatch, parameter
):
    fixture = _create_serial_trace_fixture(client)

    def unexpected_snapshot():
        pytest.fail("Invalid pagination must be rejected before trace queries")

    monkeypatch.setattr(TraceRepository, "read_snapshot", unexpected_snapshot)
    invalid_values = [
        ("abc", "分页参数必须是整数"),
        ("", "分页参数必须是整数"),
        ("1.5", "分页参数必须是整数"),
    ]
    range_message = (
        "每页数量必须在 1 到 200 之间"
        if parameter.endswith("per_page")
        else "页码必须大于等于 1"
    )
    invalid_values.extend([("0", range_message), ("-1", range_message)])
    if parameter.endswith("per_page"):
        invalid_values.append(("201", range_message))

    for value, message in invalid_values:
        response = client.get(
            f"/api/trace/order/{fixture['order_no']}",
            query_string={parameter: value},
            headers=auth_headers,
        )
        assert response.status_code == 400, (parameter, value, response.get_json())
        assert response.get_json() == {
            "error": message,
            "code": "validation_error",
        }, (parameter, value)


@pytest.mark.parametrize(
    ("parameters", "message"),
    (
        (
            {"page": "abc", "items_page": "0", "shipments_per_page": ""},
            "分页参数必须是整数",
        ),
        (
            {"items_page": "0", "work_records_page": "abc"},
            "页码必须大于等于 1",
        ),
        (
            {"quality_inspections_per_page": "201", "shipments_page": ""},
            "每页数量必须在 1 到 200 之间",
        ),
    ),
)
def test_order_trace_multiple_invalid_parameters_have_stable_errors(
    client, auth_headers, monkeypatch, parameters, message
):
    fixture = _create_serial_trace_fixture(client)

    def unexpected_snapshot():
        pytest.fail("Invalid pagination must be rejected before trace queries")

    monkeypatch.setattr(TraceRepository, "read_snapshot", unexpected_snapshot)
    # Query-string order must not determine which validation error is returned.
    for pairs in (list(parameters.items()), list(reversed(parameters.items()))):
        response = client.get(
            f"/api/trace/order/{fixture['order_no']}",
            query_string=pairs,
            headers=auth_headers,
        )
        assert response.status_code == 400
        assert response.get_json() == {
            "error": message,
            "code": "validation_error",
        }


@pytest.mark.parametrize(
    ("parameters", "item_page", "other_page", "per_page"),
    (
        ({}, 1, 1, 100),
        ({"page": "2", "per_page": "1"}, 2, 1, 1),
        ({"per_page": "200"}, 1, 1, 200),
        (
            {
                f"{name}_{suffix}": value
                for name in TRACE_COLLECTIONS
                for suffix, value in (("page", "1"), ("per_page", "200"))
            },
            1, 1, 200,
        ),
        (
            {
                f"{name}_{suffix}": value
                for name in TRACE_COLLECTIONS
                for suffix, value in (("page", "2"), ("per_page", "1"))
            },
            2, 2, 1,
        ),
    ),
)
def test_order_trace_pagination_defaults_and_valid_boundaries(
    client, auth_headers, parameters, item_page, other_page, per_page
):
    fixture = _create_serial_trace_fixture(client, serial_count=3)
    response = client.get(
        f"/api/trace/order/{fixture['order_no']}",
        query_string=parameters,
        headers=auth_headers,
    )
    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert payload["meta"]["page"] == item_page
    assert payload["meta"]["per_page"] == per_page
    for name in TRACE_COLLECTIONS:
        pagination = payload["meta"]["pagination"][name]
        assert pagination["page"] == (item_page if name == "items" else other_page)
        assert pagination["per_page"] == per_page
    assert payload["items"][0]["serial_no"] == fixture["serial_numbers"][
        (item_page - 1) * per_page
    ]


@pytest.mark.parametrize(
    ("page", "per_page", "message"),
    (
        ("abc", 100, "分页参数必须是整数"),
        ("", 100, "分页参数必须是整数"),
        ("1.5", 100, "分页参数必须是整数"),
        (1.5, 100, "分页参数必须是整数"),
        (True, 100, "分页参数必须是整数"),
        (1, 1.5, "分页参数必须是整数"),
        (1, True, "分页参数必须是整数"),
        (None, 100, "分页参数必须是整数"),
        (0, 100, "页码必须大于等于 1"),
        (-1, 100, "页码必须大于等于 1"),
        (1, 0, "每页数量必须在 1 到 200 之间"),
        (1, -1, "每页数量必须在 1 到 200 之间"),
        (1, 201, "每页数量必须在 1 到 200 之间"),
    ),
)
def test_trace_pagination_preserves_domain_error_contract(page, per_page, message):
    with pytest.raises(ValidationError) as exc_info:
        TraceService._pagination(page, per_page)
    assert type(exc_info.value) is ValidationError
    assert str(exc_info.value) == message
    assert exc_info.value.status_code == 400
    assert exc_info.value.to_payload() == {
        "error": message,
        "code": "validation_error",
    }


def test_serial_trace_quality_inspection_with_multiple_ncrs_is_not_duplicated(
    client,
    auth_headers,
):
    fixture = _create_serial_trace_fixture(client)

    with client.application.app_context():
        db = get_db()
        cursor = db.execute(
            "INSERT INTO quality_inspections "
            "(order_id, process_id, inspection_type, result, serial_no, created_at) "
            "VALUES (?, ?, 'in_process', 'fail', ?, '2026-11-04 00:00:00')",
            (
                fixture["order_id"],
                fixture["process_id"],
                fixture["serial_numbers"][0],
            ),
        )
        inspection_id = cursor.lastrowid
        db.execute(
            "INSERT INTO quality_nonconformances "
            "(ncr_no, inspection_id, order_id) VALUES (?, ?, ?)",
            ("TRACE-SERIAL-NCR-FIRST", inspection_id, fixture["order_id"]),
        )
        db.execute(
            "INSERT INTO quality_nonconformances "
            "(ncr_no, inspection_id, order_id) VALUES (?, ?, ?)",
            ("TRACE-SERIAL-NCR-LATEST", inspection_id, fixture["order_id"]),
        )
        db.commit()

    response = client.get(
        f"/api/trace/{fixture['serial_numbers'][0]}",
        headers=auth_headers,
    )

    assert response.status_code == 200, response.get_json()
    inspections = response.get_json()["serial_scope"]["quality_inspections"]
    assert len(inspections) == 1
    assert inspections[0]["id"] == inspection_id
    assert inspections[0]["ncr_no"] == "TRACE-SERIAL-NCR-LATEST"


@pytest.mark.parametrize("scope", ("order", "serial"))
def test_quality_trace_does_not_rescan_unrelated_ncrs_for_each_inspection(client, scope):
    fixture = _create_serial_trace_fixture(client)

    with client.application.app_context():
        db = get_db()
        inspection_ids = []
        for _ in range(200):
            cursor = db.execute(
                "INSERT INTO quality_inspections "
                "(order_id, process_id, inspection_type, result, serial_no, created_at) "
                "VALUES (?, ?, 'in_process', 'pass', ?, '2026-11-04 00:00:00')",
                (fixture["order_id"], fixture["process_id"], fixture["serial_numbers"][0]),
            )
            inspection_ids.append(cursor.lastrowid)

        other_order_id = create_order(db, [fixture["process_id"]])
        other_inspection_id = db.execute(
            "INSERT INTO quality_inspections "
            "(order_id, process_id, inspection_type, result) "
            "VALUES (?, ?, 'in_process', 'fail')",
            (other_order_id, fixture["process_id"]),
        ).lastrowid
        db.executemany(
            "INSERT INTO quality_nonconformances "
            "(ncr_no, inspection_id, order_id) VALUES (?, ?, ?)",
            (
                (f"TRACE-UNRELATED-{index}", other_inspection_id, other_order_id)
                for index in range(5000)
            ),
        )
        db.executemany(
            "INSERT INTO quality_nonconformances "
            "(ncr_no, inspection_id, order_id) VALUES (?, ?, ?)",
            (
                (number, inspection_ids[0], fixture["order_id"])
                for number in ("TRACE-PERF-FIRST", "TRACE-PERF-LATEST")
            ),
        )
        db.commit()

        # Bound SQLite work instead of wall-clock time: a repeated full NCR scan
        # exceeds one million VM instructions; one grouped scan has ample margin.
        progress_calls = 0

        def enforce_work_budget():
            nonlocal progress_calls
            progress_calls += 1
            return int(progress_calls >= 1000)

        db.set_progress_handler(enforce_work_budget, 1000)
        try:
            if scope == "order":
                rows = TraceRepository.find_quality_inspections_by_order(
                    fixture["order_id"], limit=200, db=db
                )
            else:
                rows = TraceRepository.find_quality_inspections_by_serial(
                    fixture["serial_numbers"][0], fixture["order_id"], db=db
                )
        finally:
            db.set_progress_handler(None, 0)

        assert [row["id"] for row in rows] == inspection_ids
        assert rows[0]["ncr_no"] == "TRACE-PERF-LATEST"
        assert all(row["ncr_no"] is None for row in rows[1:])


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
