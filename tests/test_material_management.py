import uuid

from factories import create_material
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
