import uuid

from factories import create_inventory_item, create_material, create_order, ensure_process
from modules.db import get_db


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
    assert payload["order"]["order_no"] == fixture["order_no"]
    assert len(payload["work_records"]) == 1
    assert payload["work_records"][0]["quantity"] == 1


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
    assert [row["source_work_record_id"] for row in serial_scope["material_consumptions"]] == [
        fixture["work_record_ids"][0]
    ]
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
