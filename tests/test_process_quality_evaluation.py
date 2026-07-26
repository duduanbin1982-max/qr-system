"""Full-process quality evaluation integration tests."""

import json
import uuid

import pytest

from modules.db import get_db
from modules.domain.errors import ConflictError
from modules.domain.work_report import WorkReportCommand
from modules.services.process_quality_evaluation_service import ProcessQualityEvaluationService
from modules.services.quality_management_service import QualityManagementService
from factories import WORKER_HASH, WORKER_PASS, ensure_user


def _seed_serial_flow(client):
    suffix = uuid.uuid4().hex[:6].upper()
    upstream_usernames = [f"pqe_up_{suffix.lower()}_{index}" for index in (1, 2)]
    with client.application.app_context():
        db = get_db()
        upstream_users = [
            ensure_user(db, username, WORKER_HASH, f"上游员工{index}", "worker", f"PQE-UP-{suffix}-{index}")
            for index, username in enumerate(upstream_usernames, start=1)
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
        "upstream_usernames": upstream_usernames,
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


def _login_headers(client, username):
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": WORKER_PASS},
    )
    assert response.status_code == 200, response.get_json()
    return {"Authorization": f"Bearer {response.get_json()['user']['token']}"}


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
    assert all("target_user_id" not in item for item in payload["items"])
    assert all("target_user_name" not in item for item in payload["items"])
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
    target_task = next(item for item in tasks if item["target_process_id"] == flow["process_ids"][0])
    created = client.post(
        "/api/process-quality-evaluations",
        headers=worker_auth_headers,
        json=_score_payload(target_task["id"], 4),
    )
    assert created.status_code == 200, created.get_json()

    ProcessQualityEvaluationService.save_rules({"minimum_samples_for_performance": 1})
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


def test_optional_history_task_can_be_skipped_but_required_task_cannot(client, worker_auth_headers):
    flow = _seed_serial_flow(client)
    _complete_serial_report(client, worker_auth_headers, flow)
    tasks = client.get(
        "/api/process-quality-evaluations/tasks", headers=worker_auth_headers
    ).get_json()["items"]
    required = next(item for item in tasks if item["is_required"])
    optional = next(item for item in tasks if not item["is_required"])

    blocked = client.post(
        f"/api/process-quality-evaluations/tasks/{required['id']}/skip",
        headers=worker_auth_headers,
        json={"reason": "不评价"},
    )
    assert blocked.status_code == 400
    skipped = client.post(
        f"/api/process-quality-evaluations/tasks/{optional['id']}/skip",
        headers=worker_auth_headers,
        json={"reason": "未发现历史工序问题"},
    )
    assert skipped.status_code == 200, skipped.get_json()
    remaining = client.get(
        "/api/process-quality-evaluations/tasks", headers=worker_auth_headers
    ).get_json()["items"]
    assert [item["id"] for item in remaining] == [required["id"]]


def test_pending_required_evaluation_blocks_next_normal_report(client, worker_auth_headers):
    flow = _seed_serial_flow(client)
    _complete_serial_report(client, worker_auth_headers, flow)
    suffix = uuid.uuid4().hex[:6].upper()
    with client.application.app_context():
        db = get_db()
        process_id = db.execute(
            "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
            "VALUES (?, 'pytest fixture process', 'fixture', 1, 'active', datetime('now','localtime'))",
            (f"必评门禁测试工序-{suffix}",),
        ).lastrowid
        order_id = db.execute(
            "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status, qr_mode) "
            "VALUES (?, 'Test Customer', '必评门禁产品', ?, 1, 'producing', '')",
            (f"TEST-PQE-GATE-{suffix}", f"PQE-GATE-{suffix}"),
        ).lastrowid
        db.execute(
            "INSERT INTO order_processes (order_id, process_id, seq_order, status, completed, scrapped, rework) "
            "VALUES (?, ?, 1, 'pending', 0, 0, 0)",
            (order_id, process_id),
        )
        db.commit()

    blocked = client.post(
        "/api/mobile/report",
        headers=worker_auth_headers,
        json={
            "order_id": order_id,
            "process_id": process_id,
            "quantity": 1,
            "report_type": "normal",
        },
    )

    assert blocked.status_code == 409, blocked.get_json()
    payload = blocked.get_json()
    assert "未完成的必评任务" in payload["error"]
    assert payload["code"] == "quality_evaluation_required"
    assert payload["action"] == "open_quality_evaluation"
    assert payload["details"]["pending_required_count"] == 1
    assert payload["details"]["first_task_id"] > 0
    assert payload["details"]["order_no"] == flow["order_no"]


def test_quality_admin_can_waive_required_tasks_by_order_and_release_gate(
    client, auth_headers, worker_auth_headers
):
    flow = _seed_serial_flow(client)
    _complete_serial_report(client, worker_auth_headers, flow)
    tasks_response = client.get(
        "/api/process-quality-evaluations/tasks", headers=worker_auth_headers
    )
    assert tasks_response.status_code == 200, tasks_response.get_json()
    task_payload = tasks_response.get_json()
    required_task = next(item for item in task_payload["items"] if item["is_required"])
    assert task_payload["pending_required_count"] == 1

    denied = client.post(
        "/api/process-quality-evaluations/tasks/waive",
        headers=worker_auth_headers,
        json={
            "task_ids": [required_task["id"]],
            "reason_code": "emergency_authorized_release",
            "reason": "worker cannot waive",
        },
    )
    assert denied.status_code == 403

    missing_reason = client.post(
        "/api/process-quality-evaluations/tasks/waive",
        headers=auth_headers,
        json={"task_ids": [required_task["id"]]},
    )
    assert missing_reason.status_code == 400

    summary_before = client.get(
        "/api/process-quality-evaluations/tasks/disposal-summary", headers=auth_headers
    )
    assert summary_before.status_code == 200, summary_before.get_json()
    assert summary_before.get_json()["required_pending"] >= 1

    waived = client.post(
        "/api/process-quality-evaluations/tasks/waive",
        headers=auth_headers,
        json={
            "order_id": flow["order_id"],
            "required_only": True,
            "reason_code": "emergency_authorized_release",
            "reason": "紧急订单经生产负责人确认授权继续报工",
        },
    )
    assert waived.status_code == 200, waived.get_json()
    assert waived.get_json()["count"] == 1
    assert waived.get_json()["task_ids"] == [required_task["id"]]

    waived_tasks = client.get(
        "/api/process-quality-evaluations/tasks?scope=all&status=waived",
        headers=auth_headers,
    )
    assert waived_tasks.status_code == 200, waived_tasks.get_json()
    waived_task = next(item for item in waived_tasks.get_json()["items"] if item["id"] == required_task["id"])
    assert waived_task["waiver_reason_code"] == "emergency_authorized_release"
    assert waived_task["waiver_reason"] == "紧急订单经生产负责人确认授权继续报工"
    assert waived_task["waived_by_name"]

    with client.application.app_context():
        db = get_db()
        audit = db.execute(
            "SELECT action, reason_code, reason "
            "FROM process_quality_evaluation_task_audits WHERE task_id = ?",
            (required_task["id"],),
        ).fetchone()
    assert audit["action"] == "waived"
    assert audit["reason_code"] == "emergency_authorized_release"
    assert audit["reason"] == "紧急订单经生产负责人确认授权继续报工"

    suffix = uuid.uuid4().hex[:6].upper()
    with client.application.app_context():
        db = get_db()
        order_id = db.execute(
            "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status, qr_mode) "
            "VALUES (?, 'Test Customer', 'gate release product', ?, 1, 'producing', '')",
            (f"TEST-PQE-WAIVE-{suffix}", f"PQE-WAIVE-{suffix}"),
        ).lastrowid
        db.execute(
            "INSERT INTO order_processes (order_id, process_id, seq_order, status, completed, scrapped, rework) "
            "VALUES (?, ?, 1, 'pending', 0, 0, 0)",
            (order_id, flow["process_ids"][2]),
        )
        db.commit()

    released = client.post(
        "/api/mobile/report",
        headers=worker_auth_headers,
        json={
            "order_id": order_id,
            "process_id": flow["process_ids"][2],
            "quantity": 1,
            "report_type": "normal",
        },
    )
    assert released.status_code == 200, released.get_json()


def test_quality_inspector_can_waive_historical_but_not_live_tasks(client, worker_auth_headers):
    flow = _seed_serial_flow(client)
    _complete_serial_report(client, worker_auth_headers, flow)
    task = next(
        item for item in client.get(
            "/api/process-quality-evaluations/tasks", headers=worker_auth_headers
        ).get_json()["items"]
        if item["is_required"]
    )
    suffix = uuid.uuid4().hex[:6].lower()
    username = f"pqe_qc_{suffix}"
    with client.application.app_context():
        db = get_db()
        ensure_user(
            db, username, WORKER_HASH, "评价任务质检员", "qc_inspector", f"PQE-QC-{suffix}"
        )
    qc_headers = _login_headers(client, username)

    summary = client.get(
        "/api/process-quality-evaluations/tasks/disposal-summary", headers=qc_headers
    )
    assert summary.status_code == 200, summary.get_json()
    assert summary.get_json()["waiver_policy"]["can_waive_live"] is False

    live_denied = client.post(
        "/api/process-quality-evaluations/tasks/waive",
        headers=qc_headers,
        json={
            "task_ids": [task["id"]],
            "reason_code": "task_generated_in_error",
            "reason": "现场核实该任务由重复报工错误生成",
        },
    )
    assert live_denied.status_code == 403, live_denied.get_json()

    with client.application.app_context():
        db = get_db()
        db.execute(
            "UPDATE orders SET status = 'completed' WHERE id = ?",
            (flow["order_id"],),
        )
        db.commit()

    historical_waived = client.post(
        "/api/process-quality-evaluations/tasks/waive",
        headers=qc_headers,
        json={
            "task_ids": [task["id"]],
            "reason_code": "completed_order_history",
            "reason": "订单完工后的历史遗留任务",
        },
    )
    assert historical_waived.status_code == 200, historical_waived.get_json()
    assert historical_waived.get_json()["waiver_scope"] == "historical"

    with client.application.app_context():
        db = get_db()
        db.execute("DELETE FROM orders WHERE id = ?", (flow["order_id"],))
        db.commit()
        assert db.execute(
            "SELECT id FROM process_quality_evaluation_tasks WHERE id = ?", (task["id"],)
        ).fetchone() is None
        audit = db.execute(
            "SELECT * FROM process_quality_evaluation_task_audits WHERE task_id = ?",
            (task["id"],),
        ).fetchone()
        assert audit["order_no"] == flow["order_no"]
        assert audit["target_process_name"]
        assert audit["evaluator_name"] == "Test Worker"
        assert audit["operator_name"] == "评价任务质检员"
        assert audit["reason_code"] == "completed_order_history"

    audit_response = client.get(
        f"/api/process-quality-evaluations/tasks/audits?keyword={flow['order_no']}",
        headers=qc_headers,
    )
    assert audit_response.status_code == 200, audit_response.get_json()
    audit_item = audit_response.get_json()["items"][0]
    assert audit_item["audit_record"] == 1
    assert audit_item["order_no"] == flow["order_no"]
    assert audit_item["waiver_reason_code"] == "completed_order_history"


def test_process_template_drives_dynamic_weighted_dimensions(client, auth_headers, worker_auth_headers):
    flow = _seed_serial_flow(client)
    created_template = client.post(
        "/api/process-quality-evaluations/templates",
        headers=auth_headers,
        json={
            "name": "钻孔接手评价",
            "process_id": flow["process_ids"][1],
            "dimensions": [
                {"key": "hole_size", "label": "孔径", "weight": 3, "required": True},
                {"key": "burr", "label": "毛刺", "weight": 1, "required": True},
            ],
            "issue_tags": ["孔径超差", "毛刺"],
            "critical_issue_tags": ["孔径严重超差"],
            "low_score_threshold": 60,
            "critical_score_threshold": 40,
            "status": "active",
        },
    )
    assert created_template.status_code == 200, created_template.get_json()
    _complete_serial_report(client, worker_auth_headers, flow)
    task = next(
        item for item in client.get(
            "/api/process-quality-evaluations/tasks", headers=worker_auth_headers
        ).get_json()["items"]
        if item["target_process_id"] == flow["process_ids"][1]
    )
    assert [item["key"] for item in task["template_snapshot"]["dimensions"]] == ["hole_size", "burr"]

    submitted = client.post(
        "/api/process-quality-evaluations",
        headers=worker_auth_headers,
        json={
            "task_id": task["id"],
            "dimension_scores": {"hole_size": 5, "burr": 1},
            "issue_tags": [],
            "comment": "",
        },
    )
    assert submitted.status_code == 200, submitted.get_json()
    assert submitted.get_json()["items"][0]["total_score"] == 80


def test_optional_template_dimension_can_be_omitted():
    scores, _, total_score = ProcessQualityEvaluationService._evaluate_dimensions(
        {"dimension_scores": {"required_quality": 4}},
        {
            "dimensions": [
                {
                    "key": "required_quality",
                    "label": "必评质量",
                    "weight": 1,
                    "required": True,
                },
                {
                    "key": "optional_appearance",
                    "label": "选评外观",
                    "weight": 1,
                    "required": False,
                },
            ]
        },
    )

    assert scores == {"required_quality": 4}
    assert total_score == 80


def test_saving_active_template_deactivates_previous_template_in_same_scope(
    client, auth_headers
):
    suffix = uuid.uuid4().hex[:6].upper()
    with client.application.app_context():
        db = get_db()
        process_id = db.execute(
            "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
            "VALUES (?, 'pytest fixture process', 'fixture', 1, 'active', datetime('now','localtime'))",
            (f"模板唯一性工序-{suffix}",),
        ).lastrowid
        db.commit()
    payload = {
        "process_id": process_id,
        "dimensions": [
            {"key": "quality", "label": "质量", "weight": 1, "required": True}
        ],
        "issue_tags": [],
        "critical_issue_tags": [],
        "low_score_threshold": 60,
        "critical_score_threshold": 40,
        "status": "active",
    }
    first = client.post(
        "/api/process-quality-evaluations/templates",
        headers=auth_headers,
        json={**payload, "name": "第一版模板"},
    ).get_json()["id"]
    second = client.post(
        "/api/process-quality-evaluations/templates",
        headers=auth_headers,
        json={**payload, "name": "第二版模板"},
    ).get_json()["id"]

    templates = client.get(
        "/api/process-quality-evaluations/templates", headers=auth_headers
    ).get_json()["items"]
    status_by_id = {item["id"]: item["status"] for item in templates}
    assert status_by_id[first] == "inactive"
    assert status_by_id[second] == "active"


def test_route_template_rejects_process_outside_selected_route(client, auth_headers):
    suffix = uuid.uuid4().hex[:6].upper()
    with client.application.app_context():
        db = get_db()
        process_id = db.execute(
            "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
            "VALUES (?, 'pytest fixture process', 'fixture', 1, 'active', datetime('now','localtime'))",
            (f"路线外工序-{suffix}",),
        ).lastrowid
        route_id = db.execute(
            "INSERT INTO process_routes (name, description, status, category, updated_at) "
            "VALUES (?, 'pytest fixture route', 'active', 'fixture', datetime('now','localtime'))",
            (f"评价模板路线-{suffix}",),
        ).lastrowid
        db.commit()

    response = client.post(
        "/api/process-quality-evaluations/templates",
        headers=auth_headers,
        json={
            "name": "错误路线模板",
            "route_id": route_id,
            "process_id": process_id,
            "dimensions": [
                {"key": "quality", "label": "质量", "weight": 1, "required": True}
            ],
            "low_score_threshold": 60,
            "critical_score_threshold": 40,
            "status": "active",
        },
    )

    assert response.status_code == 400
    assert "不属于该工序路线" in response.get_json()["error"]


def test_pending_appeal_is_excluded_from_performance_and_can_be_accepted(
    client, auth_headers, worker_auth_headers
):
    flow = _seed_serial_flow(client)
    ProcessQualityEvaluationService.save_rules({"minimum_samples_for_performance": 1})
    _complete_serial_report(client, worker_auth_headers, flow)
    task = next(
        item for item in client.get(
            "/api/process-quality-evaluations/tasks", headers=worker_auth_headers
        ).get_json()["items"]
        if item["target_process_id"] == flow["process_ids"][0]
    )
    created = client.post(
        "/api/process-quality-evaluations",
        headers=worker_auth_headers,
        json=_score_payload(task["id"], 4),
    ).get_json()["items"][0]
    month = task["created_at"][:7]
    assert flow["upstream_users"][0] in ProcessQualityEvaluationService.monthly_metrics(month)

    target_headers = _login_headers(client, flow["upstream_usernames"][0])
    appeal = client.post(
        f"/api/process-quality-evaluations/{created['id']}/appeals",
        headers=target_headers,
        json={"reason": "该工件在接手后发生二次碰伤"},
    )
    assert appeal.status_code == 200, appeal.get_json()
    assert flow["upstream_users"][0] not in ProcessQualityEvaluationService.monthly_metrics(month)

    reviewed = client.put(
        f"/api/process-quality-evaluations/appeals/{appeal.get_json()['id']}/review",
        headers=auth_headers,
        json={"status": "accepted", "note": "现场记录证明申诉成立"},
    )
    assert reviewed.status_code == 200, reviewed.get_json()
    record = client.get(
        f"/api/process-quality-evaluations?year_month={month}", headers=auth_headers
    ).get_json()["items"][0]
    assert record["status"] == "rejected"
    assert record["appeal_status"] == "accepted"


def test_single_confirmed_evaluation_does_not_enter_performance_before_minimum_samples(
    client, worker_auth_headers
):
    flow = _seed_serial_flow(client)
    _complete_serial_report(client, worker_auth_headers, flow)
    task = next(
        item for item in client.get(
            "/api/process-quality-evaluations/tasks", headers=worker_auth_headers
        ).get_json()["items"]
        if item["target_process_id"] == flow["process_ids"][0]
    )
    submitted = client.post(
        "/api/process-quality-evaluations",
        headers=worker_auth_headers,
        json=_score_payload(task["id"], 4),
    )
    assert submitted.status_code == 200, submitted.get_json()
    assert flow["upstream_users"][0] not in ProcessQualityEvaluationService.monthly_metrics(
        task["created_at"][:7]
    )


def test_critical_evaluation_creates_hard_quality_verification_task(
    client, worker_auth_headers
):
    flow = _seed_serial_flow(client)
    _complete_serial_report(client, worker_auth_headers, flow)
    task = client.get(
        "/api/process-quality-evaluations/tasks", headers=worker_auth_headers
    ).get_json()["items"][0]
    submitted = client.post(
        "/api/process-quality-evaluations",
        headers=worker_auth_headers,
        json=_score_payload(task["id"], 1, ["严重尺寸超差"]),
    )
    assert submitted.status_code == 200, submitted.get_json()
    result = submitted.get_json()["items"][0]
    assert result["severity"] == "critical"
    with client.application.app_context():
        quality_task = get_db().execute(
            "SELECT gate_mode, priority FROM quality_inspection_tasks WHERE source_evaluation_id = ?",
            (result["id"],),
        ).fetchone()
    assert quality_task
    assert quality_task["gate_mode"] == "hard"
    assert quality_task["priority"] == "urgent"
    ProcessQualityEvaluationService.save_rules(
        {"low_score_threshold": 10, "critical_score_threshold": 5}
    )
    assert ProcessQualityEvaluationService.stats()["summary"]["low_score_count"] == 1
    with client.application.app_context(), pytest.raises(
        ConflictError, match="工序质量核验任务"
    ):
        QualityManagementService.assert_report_allowed(
            flow["order_id"], task["target_process_id"]
        )


def test_rejected_evaluation_cancels_quality_task(
    client, auth_headers, worker_auth_headers
):
    flow = _seed_serial_flow(client)
    _complete_serial_report(client, worker_auth_headers, flow)
    task = client.get(
        "/api/process-quality-evaluations/tasks", headers=worker_auth_headers
    ).get_json()["items"][0]
    created = client.post(
        "/api/process-quality-evaluations",
        headers=worker_auth_headers,
        json=_score_payload(task["id"], 1, ["严重尺寸超差"]),
    ).get_json()["items"][0]

    reviewed = client.put(
        f"/api/process-quality-evaluations/{created['id']}/review",
        headers=auth_headers,
        json={"status": "rejected", "note": "现场复核不属于上道工序责任"},
    )

    assert reviewed.status_code == 200, reviewed.get_json()
    with client.application.app_context():
        quality_task = get_db().execute(
            "SELECT status, cancel_reason, cancelled_at FROM quality_inspection_tasks "
            "WHERE source_evaluation_id = ?",
            (created["id"],),
        ).fetchone()
    assert quality_task["status"] == "cancelled"
    assert "关联评价已被驳回" in quality_task["cancel_reason"]
    assert quality_task["cancelled_at"]
    stats = client.get(
        "/api/process-quality-evaluations/stats", headers=auth_headers
    ).get_json()
    assert stats["summary"]["total"] == 0
    assert stats["processes"] == []
    assert stats["evaluators"] == []


def test_accepted_appeal_cancels_existing_quality_task(
    client, auth_headers, worker_auth_headers
):
    flow = _seed_serial_flow(client)
    _complete_serial_report(client, worker_auth_headers, flow)
    task = next(
        item for item in client.get(
            "/api/process-quality-evaluations/tasks", headers=worker_auth_headers
        ).get_json()["items"]
        if item["target_process_id"] == flow["process_ids"][0]
    )
    created = client.post(
        "/api/process-quality-evaluations",
        headers=worker_auth_headers,
        json=_score_payload(task["id"], 2, ["尺寸问题"]),
    ).get_json()["items"][0]
    confirmed = client.put(
        f"/api/process-quality-evaluations/{created['id']}/review",
        headers=auth_headers,
        json={"status": "confirmed", "note": "暂按现场检查结果确认"},
    )
    assert confirmed.status_code == 200, confirmed.get_json()
    target_headers = _login_headers(client, flow["upstream_usernames"][0])
    appeal = client.post(
        f"/api/process-quality-evaluations/{created['id']}/appeals",
        headers=target_headers,
        json={"reason": "复核记录显示问题在后续搬运中产生"},
    )
    reviewed = client.put(
        f"/api/process-quality-evaluations/appeals/{appeal.get_json()['id']}/review",
        headers=auth_headers,
        json={"status": "accepted", "note": "申诉证据完整，确认不归责上道工序"},
    )

    assert reviewed.status_code == 200, reviewed.get_json()
    with client.application.app_context():
        quality_task = get_db().execute(
            "SELECT status, cancel_reason FROM quality_inspection_tasks "
            "WHERE source_evaluation_id = ?",
            (created["id"],),
        ).fetchone()
    assert quality_task["status"] == "cancelled"
    assert "申诉成立" in quality_task["cancel_reason"]
