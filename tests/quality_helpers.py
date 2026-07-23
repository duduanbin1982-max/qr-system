"""Shared quality workflow fixtures."""

from factories import create_order, ensure_process
from modules.db import get_db


def seed_quality_order(client, process_name="Quality Gate Process", quantity=3, product_code="QM-TEST-001"):
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, process_name)
        order_id = create_order(db, [process_id], quantity=quantity, product_code=product_code)
        order = db.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        return order_id, process_id, dict(order)


def submit_quality_task(client, auth_headers, task_id, result="pass", failed=0, defect_level=""):
    detail = client.get(f"/api/quality-management/tasks/{task_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.get_json()
    task = detail.get_json()["task"]
    measurements = []
    for item in task.get("standard_items", []):
        value = True
        if item["item_type"] == "score":
            value = item["weight"]
        elif item["item_type"] == "numeric":
            value = item["nominal_value"] or item["lower_limit"] or item["upper_limit"] or 1
        elif item["item_type"] == "text":
            value = "符合"
        measurements.append({"item_id": item["id"], "item_code": item["item_code"], "value": value})
    response = client.post(
        f"/api/quality-management/tasks/{task_id}/inspect",
        headers=auth_headers,
        json={
            "quantity_checked": task["sample_qty"],
            "quantity_failed": failed,
            "result": result,
            "defect_level": defect_level,
            "defect_category": "dimension" if result != "pass" else "",
            "notes": "quality management integration test",
            "measurements": measurements,
        },
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()
