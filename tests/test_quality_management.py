"""Quality management closed-loop integration tests."""

from factories import create_inventory_item
from modules.db import get_db
from modules.domain.errors import ConflictError
from modules.services.quality_management_service import QualityManagementService
from quality_helpers import seed_quality_order, submit_quality_task


def test_quality_management_catalog_and_default_rules(client, auth_headers):
    dashboard = client.get("/api/quality-management/dashboard", headers=auth_headers)
    assert dashboard.status_code == 200
    assert dashboard.get_json()["tasks"]["pending"] == 0

    standards = client.get("/api/quality-management/standards?limit=100", headers=auth_headers)
    assert standards.status_code == 200
    assert {item["inspection_type"] for item in standards.get_json()["items"]} >= {
        "first_article", "in_process", "final", "outgoing", "rework_check"
    }

    rules = client.get("/api/quality-management/rules", headers=auth_headers).get_json()
    assert rules["first_article_gate"] == "hard"
    assert rules["final_gate"] == "hard"
    assert rules["shipment_gate"] == "hard"


def test_first_article_task_blocks_until_inspected(client, auth_headers):
    order_id, process_id, _ = seed_quality_order(client)
    with client.application.app_context():
        db = get_db()
        db.execute(
            "INSERT INTO work_records (order_id,process_id,user_id,type,quantity,status,created_at) "
            "VALUES (?,?,1,'normal',1,'approved',datetime('now','localtime'))",
            (order_id, process_id),
        )
        work_record_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("UPDATE order_processes SET completed=1 WHERE order_id=? AND process_id=?", (order_id, process_id))
        QualityManagementService.generate_for_report(order_id, process_id, work_record_id, "", 1, db)
        db.commit()
        task = db.execute(
            "SELECT * FROM quality_inspection_tasks WHERE order_id=? AND inspection_type='first_article'",
            (order_id,),
        ).fetchone()
        assert task and task["status"] == "pending"
        try:
            QualityManagementService.assert_report_allowed(order_id, process_id, db)
            assert False, "hard first-article gate should block"
        except ConflictError:
            pass
        task_id = task["id"]

    submit_quality_task(client, auth_headers, task_id)
    with client.application.app_context():
        QualityManagementService.assert_report_allowed(order_id, process_id, get_db())


def test_failed_inspection_creates_ncr_rework_and_reinspection(client, auth_headers):
    order_id, process_id, _ = seed_quality_order(client)
    manual = client.post(
        "/api/quality-management/tasks",
        headers=auth_headers,
        json={
            "order_id": order_id, "process_id": process_id, "inspection_type": "in_process",
            "sample_qty": 1, "gate_mode": "soft", "priority": "urgent",
        },
    )
    assert manual.status_code == 200, manual.get_json()
    failed = submit_quality_task(client, auth_headers, manual.get_json()["id"], "rework", 1, "severe")
    assert failed["ncr_id"]

    disposition = client.put(
        f"/api/quality-management/ncr/{failed['ncr_id']}/disposition",
        headers=auth_headers,
        json={"disposition": "rework", "corrective_action": "返修后复检"},
    )
    assert disposition.status_code == 200, disposition.get_json()
    rework_id = disposition.get_json()["rework_id"]
    assert rework_id

    with client.application.app_context():
        db = get_db()
        rework = db.execute(
            "SELECT quantity, source_ncr_id FROM rework_records WHERE id=?", (rework_id,)
        ).fetchone()
        process_totals = db.execute(
            "SELECT rework FROM order_processes WHERE order_id=? AND process_id=?",
            (order_id, process_id),
        ).fetchone()
        order_totals = db.execute(
            "SELECT rework FROM orders WHERE id=?", (order_id,)
        ).fetchone()
        assert rework["quantity"] == 1
        assert rework["source_ncr_id"] == failed["ncr_id"]
        assert process_totals["rework"] == 1
        assert order_totals["rework"] == 1
        db.execute(
            "UPDATE rework_records SET status='completed',completed_at=datetime('now','localtime') WHERE id=?",
            (rework_id,),
        )
        recheck_id = QualityManagementService.generate_for_rework(rework_id, 1, db)
        db.commit()
    assert recheck_id
    submit_quality_task(client, auth_headers, recheck_id)

    with client.application.app_context():
        ncr = get_db().execute("SELECT * FROM quality_nonconformances WHERE id=?", (failed["ncr_id"],)).fetchone()
        assert ncr["status"] == "closed"
        assert "复检通过" in ncr["verification_result"]


def test_final_gate_quarantines_inventory_and_releases_order(client, auth_headers):
    order_id, process_id, _ = seed_quality_order(client, quantity=1)
    with client.application.app_context():
        db = get_db()
        create_inventory_item(db, order_id=order_id, product_model="QM-TEST-001")
        db.execute(
            "INSERT INTO work_records (order_id,process_id,user_id,type,quantity,status,created_at) "
            "VALUES (?,?,1,'normal',1,'approved',datetime('now','localtime'))",
            (order_id, process_id),
        )
        work_record_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.execute("UPDATE order_processes SET completed=1 WHERE order_id=?", (order_id,))
        QualityManagementService.generate_for_report(order_id, process_id, work_record_id, "", 1, db)
        db.commit()
        final_task = db.execute(
            "SELECT * FROM quality_inspection_tasks WHERE order_id=? AND inspection_type='final'",
            (order_id,),
        ).fetchone()
        inventory = db.execute("SELECT * FROM inventory WHERE order_id=?", (order_id,)).fetchone()
        assert final_task and inventory["quality_status"] == "quarantined"
        task_id = final_task["id"]
        first_task_id = db.execute(
            "SELECT id FROM quality_inspection_tasks WHERE order_id=? AND inspection_type='first_article'",
            (order_id,),
        ).fetchone()[0]

    submit_quality_task(client, auth_headers, first_task_id)
    submit_quality_task(client, auth_headers, task_id)
    with client.application.app_context():
        db = get_db()
        assert db.execute("SELECT quality_status FROM inventory WHERE order_id=?", (order_id,)).fetchone()[0] == "released"
        assert db.execute("SELECT status FROM orders WHERE id=?", (order_id,)).fetchone()[0] == "completed"


def test_supplier_inspection_and_gauge_calibration(client, auth_headers):
    with client.application.app_context():
        db = get_db()
        supplier_id = db.execute("INSERT INTO suppliers (name) VALUES ('Quality Supplier')").lastrowid
        material_id = db.execute(
            "INSERT INTO materials (name,spec,unit,quantity,supplier_id) VALUES ('Quality Material','M1','件',0,?)",
            (supplier_id,),
        ).lastrowid
        db.commit()
    response = client.post(
        "/api/quality-management/supplier-inspections",
        headers=auth_headers,
        json={
            "supplier_id": supplier_id, "material_id": material_id, "batch_no": "BATCH-001",
            "quantity_checked": 10, "quantity_failed": 2, "result": "return", "score_total": 55,
            "defect_level": "severe", "defect_category": "material", "notes": "来料异常",
        },
    )
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["ncr_id"]

    gauge = client.post(
        "/api/quality-management/gauges",
        headers=auth_headers,
        json={"gauge_no": "G-001", "name": "游标卡尺", "calibration_cycle_days": 365},
    )
    assert gauge.status_code == 200, gauge.get_json()
    calibrated = client.post(
        f"/api/quality-management/gauges/{gauge.get_json()['id']}/calibrations",
        headers=auth_headers,
        json={
            "calibrated_at": "2026-07-23", "next_calibration_at": "2027-07-23",
            "result": "pass", "certificate_no": "CERT-001",
        },
    )
    assert calibrated.status_code == 200, calibrated.get_json()


def test_mobile_inspection_uses_task_ncr_and_trace_closed_loop(client, auth_headers):
    order_id, process_id, order = seed_quality_order(client)
    task = client.post(
        "/api/quality-management/tasks",
        headers=auth_headers,
        json={
            "order_id": order_id, "process_id": process_id,
            "inspection_type": "in_process", "sample_qty": 1,
        },
    )
    assert task.status_code == 200, task.get_json()
    task_id = task.get_json()["id"]

    submitted = client.post(
        "/api/inspection/submit",
        headers=auth_headers,
        json={
            "order_id": order_id, "order_no": order["order_no"],
            "product_code": order["product_code"], "process_id": process_id,
            "result": "rework", "remark": "移动端发现质量异常",
        },
    )
    assert submitted.status_code == 200, submitted.get_json()

    with client.application.app_context():
        db = get_db()
        task_row = db.execute(
            "SELECT status,inspection_id FROM quality_inspection_tasks WHERE id=?", (task_id,)
        ).fetchone()
        ncr = db.execute(
            "SELECT id,status FROM quality_nonconformances WHERE task_id=?", (task_id,)
        ).fetchone()
        assert task_row["status"] == "failed" and task_row["inspection_id"]
        assert ncr and ncr["status"] == "open"

    trace = client.get(f"/api/trace/order/{order['order_no']}", headers=auth_headers)
    assert trace.status_code == 200, trace.get_json()
    payload = trace.get_json()
    assert any(item["id"] == task_id for item in payload["quality_tasks"])
    assert any(item["task_no"] for item in payload["quality_nonconformances"])
