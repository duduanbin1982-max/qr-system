import uuid

from factories import (
    add_order_material,
    add_product_bom,
    create_material,
    create_order,
    ensure_process,
    ensure_product,
)
from modules.db import get_db


def _material_quantity(client, material_id):
    with client.application.app_context():
        return get_db().execute(
            "SELECT quantity FROM materials WHERE id = ?",
            (material_id,),
        ).fetchone()["quantity"]


def _create_material(client, quantity=10):
    with client.application.app_context():
        db = get_db()
        material_id = create_material(db, quantity=quantity)
        db.commit()
        return material_id


def test_create_material_records_opening_balance(client, auth_headers):
    response = client.post(
        "/api/materials",
        json={
            "name": f"Opening Material {uuid.uuid4().hex[:8]}",
            "quantity": 12.5,
            "unit": "kg",
        },
        headers=auth_headers,
    )

    assert response.status_code == 200, response.get_json()
    material_id = response.get_json()["id"]
    with client.application.app_context():
        log = get_db().execute(
            "SELECT * FROM material_logs WHERE material_id = ?",
            (material_id,),
        ).fetchone()
    assert log["type"] == "in"
    assert log["quantity"] == 12.5
    assert log["balance_before"] == 0
    assert log["balance_after"] == 12.5
    assert log["source_type"] == "opening_balance"
    assert log["operator_name"] == "Test Runner"
    assert log["operator_id"] is not None


def test_update_material_rejects_direct_quantity_changes(client, auth_headers):
    material_id = _create_material(client)

    response = client.put(
        f"/api/materials/{material_id}",
        json={"quantity": 99},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "库存数量请通过出入库功能调整"
    assert _material_quantity(client, material_id) == 10


def test_stock_change_records_authenticated_actor_and_balance_transition(
    client,
    auth_headers,
):
    material_id = _create_material(client)

    response = client.post(
        f"/api/materials/{material_id}/stock",
        json={
            "type": "out",
            "quantity": 3,
            "remark": "领料",
            "operator_name": "伪造姓名",
        },
        headers=auth_headers,
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["new_quantity"] == 7
    with client.application.app_context():
        log = get_db().execute(
            "SELECT * FROM material_logs WHERE material_id = ? ORDER BY id DESC LIMIT 1",
            (material_id,),
        ).fetchone()
    assert log["operator_name"] == "Test Runner"
    assert log["operator_id"] is not None
    assert log["balance_before"] == 10
    assert log["balance_after"] == 7
    assert log["source_type"] == "manual_stock"


def test_reversing_consumption_preserves_history_and_creates_reversal_log(
    client,
    auth_headers,
):
    material_id = _create_material(client)

    consume_response = client.post(
        f"/api/materials/{material_id}/consumptions",
        json={"quantity": 4, "notes": "试制领料"},
        headers=auth_headers,
    )
    assert consume_response.status_code == 200, consume_response.get_json()
    with client.application.app_context():
        consumption_id = get_db().execute(
            "SELECT id FROM material_consumptions WHERE material_id = ?",
            (material_id,),
        ).fetchone()["id"]

    reverse_response = client.delete(
        f"/api/material-consumptions/{consumption_id}",
        json={"reason": "录入错误"},
        headers=auth_headers,
    )

    assert reverse_response.status_code == 200, reverse_response.get_json()
    assert reverse_response.get_json()["new_quantity"] == 10
    with client.application.app_context():
        db = get_db()
        consumption = db.execute(
            "SELECT * FROM material_consumptions WHERE id = ?",
            (consumption_id,),
        ).fetchone()
        logs = db.execute(
            "SELECT * FROM material_logs WHERE material_id = ? ORDER BY id",
            (material_id,),
        ).fetchall()
    assert consumption["status"] == "reversed"
    assert consumption["reversal_reason"] == "录入错误"
    assert consumption["reversal_log_id"] == logs[-1]["id"]
    assert [log["type"] for log in logs] == ["out", "reversal"]
    assert logs[-1]["reversal_of_log_id"] == logs[0]["id"]
    assert logs[-1]["balance_before"] == 6
    assert logs[-1]["balance_after"] == 10

    duplicate_response = client.delete(
        f"/api/material-consumptions/{consumption_id}",
        json={"reason": "再次撤销"},
        headers=auth_headers,
    )
    assert duplicate_response.status_code == 409


def test_mobile_report_stock_shortage_returns_chinese_conflict_and_rolls_back(
    client,
    worker_auth_headers,
):
    suffix = uuid.uuid4().hex[:8]
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, name=f"Material Shortage Process {suffix}")
        order_id = create_order(
            db,
            [process_id],
            quantity=5,
            product_code=f"MATERIAL-SHORTAGE-{suffix}",
        )
        db.execute("UPDATE orders SET status = 'producing' WHERE id = ?", (order_id,))
        material_id = create_material(db, quantity=2, name=f"Short Wire {suffix}")
        add_order_material(db, order_id, material_id, process_id, quantity_per_unit=1)
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('auto_deduct_material', '1')"
        )
        db.commit()

    response = client.post(
        "/api/mobile/report",
        json={
            "order_id": order_id,
            "process_id": process_id,
            "quantity": 3,
            "report_type": "normal",
        },
        headers=worker_auth_headers,
    )

    assert response.status_code == 409, response.get_json()
    payload = response.get_json()
    assert payload.get("code") == "conflict", payload
    assert payload["error"].startswith("物料库存不足，报工未提交")
    assert payload["details"]["shortages"][0]["material_id"] == material_id
    with client.application.app_context():
        db = get_db()
        balance = db.execute(
            "SELECT quantity FROM materials WHERE id = ?",
            (material_id,),
        ).fetchone()["quantity"]
        process_completed = db.execute(
            "SELECT completed FROM order_processes WHERE order_id = ? AND process_id = ?",
            (order_id, process_id),
        ).fetchone()["completed"]
        report_count = db.execute(
            "SELECT COUNT(*) AS count FROM work_records WHERE order_id = ?",
            (order_id,),
        ).fetchone()["count"]
        consumption_count = db.execute(
            "SELECT COUNT(*) AS count FROM material_consumptions WHERE order_id = ?",
            (order_id,),
        ).fetchone()["count"]
    assert balance == 2
    assert process_completed == 0
    assert report_count == 0
    assert consumption_count == 0


def test_mobile_report_links_material_consumption_to_work_record(
    client,
    worker_auth_headers,
):
    suffix = uuid.uuid4().hex[:8]
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, name=f"Material Source Process {suffix}")
        order_id = create_order(
            db,
            [process_id],
            quantity=5,
            product_code=f"MATERIAL-SOURCE-{suffix}",
        )
        db.execute("UPDATE orders SET status = 'producing' WHERE id = ?", (order_id,))
        material_id = create_material(db, quantity=10, name=f"Source Material {suffix}")
        add_order_material(db, order_id, material_id, process_id, quantity_per_unit=1.5)
        db.execute(
            "INSERT OR REPLACE INTO system_settings (key, value) VALUES ('auto_deduct_material', '1')"
        )
        db.commit()

    response = client.post(
        "/api/mobile/report",
        json={
            "order_id": order_id,
            "process_id": process_id,
            "quantity": 2,
            "report_type": "normal",
        },
        headers=worker_auth_headers,
    )

    assert response.status_code == 200, response.get_json()
    with client.application.app_context():
        db = get_db()
        work_record = db.execute(
            "SELECT id FROM work_records WHERE order_id = ? AND process_id = ?",
            (order_id, process_id),
        ).fetchone()
        consumption = db.execute(
            "SELECT quantity, source_work_record_id FROM material_consumptions "
            "WHERE order_id = ? AND material_id = ?",
            (order_id, material_id),
        ).fetchone()
        balance = db.execute(
            "SELECT quantity FROM materials WHERE id = ?",
            (material_id,),
        ).fetchone()["quantity"]
    assert consumption["quantity"] == 3
    assert consumption["source_work_record_id"] == work_record["id"]
    assert balance == 7


def test_material_impact_counts_every_traceability_reference(client, auth_headers):
    suffix = uuid.uuid4().hex[:8]
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, name=f"Material Reference Process {suffix}")
        product_id = ensure_product(
            db,
            product_code=f"MATERIAL-REF-{suffix}",
            product_name=f"Material Reference Product {suffix}",
        )
        order_id = create_order(db, [process_id], product_code=f"MATERIAL-REF-{suffix}")
        material_id = create_material(db, name=f"Referenced Material {suffix}")
        add_product_bom(db, product_id, material_id, process_id)
        add_order_material(db, order_id, material_id, process_id)
        db.execute(
            "INSERT INTO material_consumptions (material_id, order_id, process_id, quantity) "
            "VALUES (?, ?, ?, 1)",
            (material_id, order_id, process_id),
        )
        db.execute(
            "INSERT INTO quality_inspection_tasks "
            "(task_no, trigger_key, inspection_type, material_id) VALUES (?, ?, 'incoming', ?)",
            (f"TASK-{suffix}", f"material-ref-{suffix}", material_id),
        )
        db.execute(
            "INSERT INTO quality_nonconformances (ncr_no, material_id) VALUES (?, ?)",
            (f"NCR-{suffix}", material_id),
        )
        supplier_id = db.execute(
            "INSERT INTO suppliers (name) VALUES (?)",
            (f"Reference Supplier {suffix}",),
        ).lastrowid
        db.execute(
            "INSERT INTO quality_supplier_inspections (supplier_id, material_id) VALUES (?, ?)",
            (supplier_id, material_id),
        )
        db.commit()

    impact = client.get(f"/api/materials/{material_id}/impact", headers=auth_headers)

    assert impact.status_code == 200, impact.get_json()
    assert impact.get_json()["refs"] == 6
    assert impact.get_json()["references"] == {
        "consumptions": 1,
        "product_bom": 1,
        "order_materials": 1,
        "inspection_tasks": 1,
        "nonconformances": 1,
        "supplier_inspections": 1,
    }
    deletion = client.delete(f"/api/materials/{material_id}", headers=auth_headers)
    assert deletion.status_code == 409, deletion.get_json()
    assert deletion.get_json()["details"]["references"] == impact.get_json()["references"]
    with client.application.app_context():
        assert get_db().execute(
            "SELECT id FROM materials WHERE id = ?",
            (material_id,),
        ).fetchone() is not None


def test_supplier_delete_blocks_quality_history_reference(client, auth_headers):
    suffix = uuid.uuid4().hex[:8]
    with client.application.app_context():
        db = get_db()
        supplier_id = db.execute(
            "INSERT INTO suppliers (name) VALUES (?)",
            (f"Quality Supplier {suffix}",),
        ).lastrowid
        db.execute(
            "INSERT INTO quality_supplier_inspections (supplier_id) VALUES (?)",
            (supplier_id,),
        )
        db.commit()

    response = client.delete(f"/api/suppliers/{supplier_id}", headers=auth_headers)

    assert response.status_code == 409, response.get_json()
    assert response.get_json()["details"]["references"] == {
        "materials": 0,
        "inspection_tasks": 0,
        "nonconformances": 0,
        "supplier_inspections": 1,
    }
