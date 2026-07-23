"""Regression tests for quality review and NCR workflow."""

from factories import create_inventory_item
from modules.db import get_db
from quality_helpers import seed_quality_order, submit_quality_task


def test_manual_ncr_quarantines_inventory_and_records_disposition(client, auth_headers):
    order_id, process_id, _ = seed_quality_order(client, product_code="QM-REVIEW-001")
    with client.application.app_context():
        create_inventory_item(get_db(), order_id=order_id, product_model="QM-REVIEW-001")

    created = client.post(
        "/api/quality-management/ncr",
        headers=auth_headers,
        json={
            "order_id": order_id,
            "process_id": process_id,
            "defect_level": "severe",
            "defect_quantity": 1,
            "description": "手工登记尺寸异常",
        },
    )
    assert created.status_code == 200, created.get_json()
    ncr_id = created.get_json()["id"]

    with client.application.app_context():
        assert get_db().execute(
            "SELECT quality_status FROM inventory WHERE order_id=?", (order_id,)
        ).fetchone()[0] == "quarantined", "manual NCR must quarantine inventory"

    detail = client.get(f"/api/quality-management/ncr/{ncr_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.get_json()
    assert detail.get_json()["ncr"]["actions"][0]["action"] == "create", "manual NCR must record create action"

    disposed = client.put(
        f"/api/quality-management/ncr/{ncr_id}/disposition",
        headers=auth_headers,
        json={"disposition": "scrap", "note": "确认报废"},
    )
    assert disposed.status_code == 200, disposed.get_json()
    assert disposed.get_json()["status"] == "closed", "scrap disposition must close NCR"
    with client.application.app_context():
        assert get_db().execute(
            "SELECT quality_status FROM inventory WHERE order_id=?", (order_id,)
        ).fetchone()[0] == "nonconforming", "scrap disposition must mark inventory nonconforming"

    detail = client.get(f"/api/quality-management/ncr/{ncr_id}", headers=auth_headers)
    assert any(action["action"] == "disposition_scrap" for action in detail.get_json()["ncr"]["actions"]), "disposition must be visible in NCR timeline"


def test_rejected_inspection_creates_ncr_fails_task_and_quarantines_inventory(client, auth_headers):
    order_id, process_id, _ = seed_quality_order(client, product_code="QM-REVIEW-001")
    with client.application.app_context():
        create_inventory_item(get_db(), order_id=order_id, product_model="QM-REVIEW-001")

    task = client.post(
        "/api/quality-management/tasks",
        headers=auth_headers,
        json={
            "order_id": order_id,
            "process_id": process_id,
            "inspection_type": "in_process",
            "sample_qty": 1,
        },
    )
    assert task.status_code == 200, task.get_json()
    inspection_id = submit_quality_task(client, auth_headers, task.get_json()["id"])["inspection_id"]

    reviewed = client.post(
        f"/api/quality-management/inspections/{inspection_id}/review",
        headers=auth_headers,
        json={"status": "rejected", "note": "审核发现检验依据不足"},
    )
    assert reviewed.status_code == 200, reviewed.get_json()
    ncr_id = reviewed.get_json()["ncr_id"]
    assert ncr_id, "rejected inspection must create NCR"

    with client.application.app_context():
        db = get_db()
        assert db.execute(
            "SELECT status FROM quality_inspection_tasks WHERE id=?", (task.get_json()["id"],)
        ).fetchone()[0] == "failed"
        assert db.execute(
            "SELECT quality_status FROM inventory WHERE order_id=?", (order_id,)
        ).fetchone()[0] == "quarantined"
        inspection = db.execute(
            "SELECT review_status, review_note, quality_status FROM quality_inspections WHERE id=?",
            (inspection_id,),
        ).fetchone()
        assert tuple(inspection) == ("rejected", "审核发现检验依据不足", "nonconforming"), "review rejection must update inspection audit fields"

    detail = client.get(f"/api/quality-management/ncr/{ncr_id}", headers=auth_headers)
    assert detail.status_code == 200, detail.get_json()
    assert detail.get_json()["ncr"]["source_type"] == "inspection_review", "review rejection must identify its source"
    assert detail.get_json()["ncr"]["actions"][0]["action"] == "review_reject", "review rejection must record timeline action"


def test_rejected_inspection_requires_review_note(client, auth_headers):
    order_id, process_id, _ = seed_quality_order(client, product_code="QM-REVIEW-001")
    task = client.post(
        "/api/quality-management/tasks",
        headers=auth_headers,
        json={
            "order_id": order_id,
            "process_id": process_id,
            "inspection_type": "in_process",
            "sample_qty": 1,
        },
    )
    assert task.status_code == 200, task.get_json()
    inspection_id = submit_quality_task(client, auth_headers, task.get_json()["id"])["inspection_id"]
    response = client.post(
        f"/api/quality-management/inspections/{inspection_id}/review",
        headers=auth_headers,
        json={"status": "rejected", "note": ""},
    )
    assert response.status_code == 400, response.get_json()


def test_inspection_review_is_one_way_and_preserves_quality_hold(client, auth_headers):
    order_id, process_id, _ = seed_quality_order(client, product_code="QM-REVIEW-001")
    with client.application.app_context():
        create_inventory_item(get_db(), order_id=order_id, product_model="QM-REVIEW-001")

    task = client.post(
        "/api/quality-management/tasks",
        headers=auth_headers,
        json={"order_id": order_id, "process_id": process_id, "inspection_type": "final", "sample_qty": 1},
    )
    assert task.status_code == 200, task.get_json()
    inspection_id = submit_quality_task(client, auth_headers, task.get_json()["id"])["inspection_id"]
    rejected = client.post(
        f"/api/quality-management/inspections/{inspection_id}/review",
        headers=auth_headers,
        json={"status": "rejected", "note": "需要补充检验依据"},
    )
    assert rejected.status_code == 200, rejected.get_json()

    approved_again = client.post(
        f"/api/quality-management/inspections/{inspection_id}/review",
        headers=auth_headers,
        json={"status": "approved", "note": "不应允许反向审核"},
    )
    assert approved_again.status_code == 409, approved_again.get_json()

    with client.application.app_context():
        db = get_db()
        assert db.execute(
            "SELECT review_status FROM quality_inspections WHERE id=?", (inspection_id,)
        ).fetchone()[0] == "rejected", "rejected inspection must not be approved again"
        assert db.execute(
            "SELECT status FROM quality_nonconformances WHERE inspection_id=?", (inspection_id,)
        ).fetchone()[0] == "open", "reverse review must not close NCR"
        assert db.execute(
            "SELECT quality_status FROM inventory WHERE order_id=?", (order_id,)
        ).fetchone()[0] == "quarantined", "reverse review must preserve inventory hold"
