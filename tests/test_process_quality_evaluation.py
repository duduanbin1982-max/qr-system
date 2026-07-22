"""Full-process quality evaluation integration tests."""

import json
import uuid

from modules.db import get_db
from modules.domain.work_report import WorkReportCommand
from modules.services.process_quality_evaluation_service import ProcessQualityEvaluationService
from factories import WORKER_HASH, ensure_user


def _seed_serial_flow(client):
    suffix = uuid.uuid4().hex[:6].upper()
    with client.application.app_context():
        db = get_db()
        upstream_users = [
            ensure_user(db, f"pqe_up_{suffix.lower()}_{index}", WORKER_HASH, f"上游员工{index}", "worker", f"PQE-UP-{suffix}-{index}")
            for index in (1, 2)
        ]
        evaluator = db.execute("SELECT id FROM users WHERE username = 'testworker'").fetchone()
        assert evaluator
        process_ids = []
        for seq_order in (1, 2, 3):
            process_ids.append(db.execute(
                "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
                "VALUES (?, 'pytest fixture process', 'fixture', ?, 'active', datetime('now','localtime'))",
                (f"全流程评价工序{seq_order}-{suffix}", seq_order),
            ).lastrowid)
        order_no = f"TEST-PQE-{suffix}"
        serial_no = f"{order_no}-001"
        order_id = db.execute(
            "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status, qr_mode) "
            "VALUES (?, 'Test Customer', '评价产品', ?, 1, 'producing', 'serial')",
            (order_no, f"PQE-{suffix}"),
        ).lastrowid
        for index, process_id in enumerate(process_ids):
            completed = 1 if index < 2 else 0
            db.execute(
                "INSERT INTO order_processes (order_id, process_id, seq_order, status, completed, scrapped, rework) "
                "VALUES (?, ?, ?, ?, ?, 0, 0)",
                (order_id, process_id, index + 1, "completed" if completed else "pending", completed),
            )
        db.execute(
            "INSERT INTO product_items (serial_no, order_id, order_no, position_no, qr_content, status, current_process_id) "
            "VALUES (?, ?, ?, 1, ?, 'in_progress', ?)",
            (serial_no, order_id, order_no, json.dumps({"serial_no": serial_no}), process_ids[2]),
        )
        for process_id, user_id in zip(process_ids[:2], upstream_users):
            db.execute(
                "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, serial_no, status) "
                "VALUES (?, ?, ?, 'normal', 1, ?, 'approved')",
                (order_id, process_id, user_id, serial_no),
            )
        db.commit()
    return {
        "order_id": order_id,
        "order_no": order_no,
        "serial_no": serial_no,
        "process_ids": process_ids,
        "upstream_users": upstream_users,
        "evaluator_user_id": evaluator["id"],
    }


def _complete_serial_report(client, worker_auth_headers, flow):
    response = client.post(
        "/api/mobile/report",
        headers=worker_auth_headers,
        json={
            "order_id": flow["order_id"],
            "process_id": flow["process_ids"][2],
            "quantity": 1,
            "serial_no": flow["serial_no"],
            "report_type": "normal",
        },
    )
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _score_payload(task_id, score=5, issue_tags=None):
    return {
        "task_id": task_id,
        "processing_quality": score,
        "dimensional_accuracy": score,
        "appearance_quality": score,
        "process_continuity": score,
        "cleanliness_protection": score,
        "issue_tags": issue_tags or [],
        "comment": "",
    }


def test_approved_report_creates_all_upstream_evaluation_tasks(client, worker_auth_headers):
    flow = _seed_serial_flow(client)
    response = _complete_serial_report(client, worker_auth_headers, flow)
    assert response["quality_evaluation_pending_count"] == 2

    tasks = client.get(
        "/api/process-quality-evaluations/tasks",
        headers=worker_auth_headers,
    )
    assert tasks.status_code == 200, tasks.get_json()
    payload = tasks.get_json()
    assert payload["total"] == 2
    assert {item["target_process_id"] for item in payload["items"]} == set(flow["process_ids"][:2])
    required = [item for item in payload["items"] if item["is_required"]]
    assert len(required) == 1
    assert required[0]["target_process_id"] == flow["process_ids"][1]


def test_low_score_requires_reason_and_enters_verification(client, auth_headers, worker_auth_headers):
    flow = _seed_serial_flow(client)
    _complete_serial_report(client, worker_auth_headers, flow)
    tasks = client.get(
        "/api/process-quality-evaluations/tasks",
        headers=worker_auth_headers,
    ).get_json()["items"]
    task = tasks[0]

    invalid = client.post(
        "/api/process-quality-evaluations",
        headers=worker_auth_headers,
        json=_score_payload(task["id"], 2),
    )
    assert invalid.status_code == 400
    assert "问题标签" in invalid.get_json()["error"]

    created = client.post(
        "/api/process-quality-evaluations",
        headers=worker_auth_headers,
        json=_score_payload(task["id"], 2, ["尺寸问题"]),
    )
    assert created.status_code == 200, created.get_json()
    result = created.get_json()["items"][0]
    assert result["total_score"] == 40
    assert result["status"] == "pending_verification"

    reviewed = client.put(
        f"/api/process-quality-evaluations/{result['id']}/review",
        headers=auth_headers,
        json={"status": "confirmed", "note": "现场复核属实"},
    )
    assert reviewed.status_code == 200, reviewed.get_json()
    stats = client.get(
        f"/api/process-quality-evaluations/stats?year_month={task['created_at'][:7]}",
        headers=auth_headers,
    )
    assert stats.status_code == 200, stats.get_json()
    assert stats.get_json()["summary"]["total"] == 1


def test_confirmed_full_process_score_is_available_to_performance(client, worker_auth_headers):
    flow = _seed_serial_flow(client)
    _complete_serial_report(client, worker_auth_headers, flow)
    tasks = client.get(
        "/api/process-quality-evaluations/tasks",
        headers=worker_auth_headers,
    ).get_json()["items"]
    target_task = next(item for item in tasks if item["target_user_id"] == flow["upstream_users"][0])
    created = client.post(
        "/api/process-quality-evaluations",
        headers=worker_auth_headers,
        json=_score_payload(target_task["id"], 4),
    )
    assert created.status_code == 200, created.get_json()

    metrics = ProcessQualityEvaluationService.monthly_metrics(
        target_task["created_at"][:7]
    )
    assert metrics[flow["upstream_users"][0]]["review_count"] == 1
    assert metrics[flow["upstream_users"][0]]["avg_rating"] == 4


def test_order_mode_multiple_contributors_creates_process_level_task(client):
    suffix = uuid.uuid4().hex[:6].upper()
    with client.application.app_context():
        db = get_db()
        users = [
            ensure_user(db, f"pqe_batch_{suffix.lower()}_{index}", WORKER_HASH, f"批次员工{index}", "worker", f"PQE-B-{suffix}-{index}")
            for index in (1, 2, 3)
        ]
        process_ids = []
        for seq_order in (1, 2):
            process_ids.append(db.execute(
                "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
                "VALUES (?, 'pytest fixture process', 'fixture', ?, 'active', datetime('now','localtime'))",
                (f"订单评价工序{seq_order}-{suffix}", seq_order),
            ).lastrowid)
        order_id = db.execute(
            "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status, qr_mode) "
            "VALUES (?, 'Test Customer', '订单评价产品', ?, 10, 'producing', '')",
            (f"TEST-PQE-B-{suffix}", f"PQE-B-{suffix}"),
        ).lastrowid
        for seq_order, process_id in enumerate(process_ids, start=1):
            db.execute(
                "INSERT INTO order_processes (order_id, process_id, seq_order, status, completed, scrapped, rework) "
                "VALUES (?, ?, ?, 'pending', 0, 0, 0)",
                (order_id, process_id, seq_order),
            )
        for user_id, quantity in zip(users[:2], (4, 6)):
            db.execute(
                "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, status) "
                "VALUES (?, ?, ?, 'normal', ?, 'approved')",
                (order_id, process_ids[0], user_id, quantity),
            )
        trigger_id = db.execute(
            "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, status) "
            "VALUES (?, ?, ?, 'normal', 10, 'approved')",
            (order_id, process_ids[1], users[2]),
        ).lastrowid
        command = WorkReportCommand(
            report_type="normal",
            order_id=order_id,
            process_id=process_ids[1],
            user_id=users[2],
            user_name="批次员工3",
            quantity=10,
        )
        created = ProcessQualityEvaluationService.generate_tasks(command, trigger_id, db)
        db.commit()
        task = db.execute(
            "SELECT * FROM process_quality_evaluation_tasks WHERE trigger_work_record_id = ?",
            (trigger_id,),
        ).fetchone()

    assert created == 1
    assert task["attribution_type"] == "process"
    assert task["target_user_id"] is None
    assert task["quantity"] == 10
