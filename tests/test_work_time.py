import json

from modules.db import get_db


def _fixture_ids(client, test_order_id):
    with client.application.app_context():
        db = get_db()
        process = db.execute(
            "SELECT process_id FROM order_processes WHERE order_id = ? ORDER BY seq_order LIMIT 1",
            (test_order_id,),
        ).fetchone()
        route = db.execute(
            "INSERT INTO process_routes (name, description, category, updated_at) "
            "VALUES ('Fixture Work Time Route', 'pytest fixture route', 'fixture', datetime('now','localtime'))"
        )
        route_id = route.lastrowid
        db.execute(
            "INSERT INTO process_route_items (route_id, process_id, seq_order, required_audit) "
            "VALUES (?, ?, 0, 0)",
            (route_id, process["process_id"]),
        )
        db.execute(
            "UPDATE orders SET route_id = ?, "
            "product_code = COALESCE(NULLIF(product_code, ''), 'WT-PROD'), "
            "product_name = COALESCE(NULLIF(product_name, ''), '工时测试产品') "
            "WHERE id = ?",
            (route_id, test_order_id),
        )
        db.commit()
        user = db.execute(
            "SELECT id FROM users WHERE username = 'testrunner'",
        ).fetchone()
        order = db.execute(
            "SELECT order_no, product_code, product_name FROM orders WHERE id = ?",
            (test_order_id,),
        ).fetchone()
        return {
            "route_id": route_id,
            "process_id": process["process_id"],
            "user_id": user["id"],
            "order_no": order["order_no"],
            "product_code": order["product_code"],
            "product_name": order["product_name"],
        }


def test_work_time_standard_record_and_review_flow(client, auth_headers, test_order_id):
    ids = _fixture_ids(client, test_order_id)

    standard_response = client.post(
        "/api/work-time/standards",
        json={
            "route_id": ids["route_id"],
            "process_id": ids["process_id"],
            "standard_minutes_per_unit": 15,
            "setup_minutes": 5,
            "difficulty_factor": 1,
            "effective_from": "2026-01-01",
            "status": "active",
        },
        headers=auth_headers,
    )
    assert standard_response.status_code == 200, standard_response.get_json()
    standard_id = standard_response.get_json()["id"]

    standards = client.get(
        f"/api/work-time/standards?route_id={ids['route_id']}",
        headers=auth_headers,
    )
    assert standards.status_code == 200, standards.get_json()
    assert any(item["id"] == standard_id for item in standards.get_json()["items"])

    record_response = client.post(
        "/api/work-time/records",
        json={
            "order_id": test_order_id,
            "process_id": ids["process_id"],
            "user_id": ids["user_id"],
            "standard_id": standard_id,
            "quantity": 2,
            "start_time": "2026-01-02 08:00:00",
            "end_time": "2026-01-02 09:30:00",
            "pause_minutes": 10,
            "abnormal_reason": "设备调试等待",
        },
        headers=auth_headers,
    )
    assert record_response.status_code == 200, record_response.get_json()
    record_id = record_response.get_json()["id"]

    records = client.get("/api/work-time/records?review_status=pending", headers=auth_headers)
    assert records.status_code == 200, records.get_json()
    record = next(item for item in records.get_json()["items"] if item["id"] == record_id)
    assert record["actual_minutes"] == 80
    assert record["standard_minutes"] == 35
    assert record["standard_missing"] == 0
    assert record["route_id"] == ids["route_id"]
    assert record["route_name"] == "Fixture Work Time Route"
    assert record["product_code"] == ids["product_code"]
    assert record["product_name"] == ids["product_name"]
    assert record["review_status"] == "pending"
    assert record["status"] == "abnormal"

    review_response = client.post(
        f"/api/work-time/records/{record_id}/review",
        json={
            "effective_minutes": 75,
            "review_status": "approved",
            "review_note": "扣除设备等待 5 分钟",
        },
        headers=auth_headers,
    )
    assert review_response.status_code == 200, review_response.get_json()

    reviewed = client.get("/api/work-time/records?review_status=approved", headers=auth_headers)
    assert reviewed.status_code == 200, reviewed.get_json()
    record = next(item for item in reviewed.get_json()["items"] if item["id"] == record_id)
    assert record["effective_minutes"] == 75
    assert record["review_status"] == "approved"
    assert record["status"] == "completed"

    stats = client.get("/api/work-time/stats", headers=auth_headers)
    assert stats.status_code == 200, stats.get_json()
    assert stats.get_json()["records_total"] >= 1
    assert stats.get_json()["standards_active"] >= 1


def test_work_time_standard_requires_positive_minutes(client, auth_headers, test_order_id):
    ids = _fixture_ids(client, test_order_id)

    response = client.post(
        "/api/work-time/standards",
        json={
            "route_id": ids["route_id"],
            "process_id": ids["process_id"],
            "standard_minutes_per_unit": 0,
        },
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "单件标准工时" in response.get_json()["error"]


def test_work_time_standard_rejects_process_outside_route(client, auth_headers, test_order_id):
    ids = _fixture_ids(client, test_order_id)
    with client.application.app_context():
        db = get_db()
        cursor = db.execute(
            "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
            "VALUES ('Fixture Other Process', 'pytest fixture process', 'fixture', 99, 'active', datetime('now','localtime'))"
        )
        other_process_id = cursor.lastrowid
        db.commit()

    response = client.post(
        "/api/work-time/standards",
        json={
            "route_id": ids["route_id"],
            "process_id": other_process_id,
            "standard_minutes_per_unit": 10,
        },
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "不属于该工序路线" in response.get_json()["error"]



def test_work_time_route_batch_standard_groups_by_route(client, auth_headers, test_order_id):
    ids = _fixture_ids(client, test_order_id)
    with client.application.app_context():
        db = get_db()
        cursor = db.execute(
            "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
            "VALUES ('Fixture Batch Process', 'pytest fixture process', 'fixture', 100, 'active', datetime('now','localtime'))"
        )
        second_process_id = cursor.lastrowid
        db.execute(
            "INSERT INTO process_route_items (route_id, process_id, seq_order, required_audit) "
            "VALUES (?, ?, 1, 0)",
            (ids["route_id"], second_process_id),
        )
        db.commit()

    response = client.post(
        "/api/work-time/standards/route",
        json={
            "route_id": ids["route_id"],
            "effective_from": "2026-01-01",
            "items": [
                {
                    "process_id": ids["process_id"],
                    "enabled": True,
                    "standard_minutes_per_unit": 12,
                    "setup_minutes": 3,
                    "difficulty_factor": 1,
                    "remark": "first process",
                },
                {
                    "process_id": second_process_id,
                    "enabled": True,
                    "standard_minutes_per_unit": 8,
                    "setup_minutes": 1,
                    "difficulty_factor": 1.2,
                    "remark": "second process",
                },
            ],
        },
        headers=auth_headers,
    )
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["created"] == 2

    standards = client.get(
        f"/api/work-time/standards?route_id={ids['route_id']}",
        headers=auth_headers,
    )
    assert standards.status_code == 200, standards.get_json()
    payload = standards.get_json()
    assert len(payload["items"]) == 2
    assert len(payload["route_groups"]) == 1
    group = payload["route_groups"][0]
    assert group["route_id"] == ids["route_id"]
    assert group["process_count"] == 2
    assert group["active_count"] == 2
    assert [item["route_seq_order"] for item in group["items"]] == [0, 1]



def test_work_time_route_batch_rejects_empty_process_item(client, auth_headers, test_order_id):
    ids = _fixture_ids(client, test_order_id)

    response = client.post(
        "/api/work-time/standards/route",
        json={"route_id": ids["route_id"], "items": [{}]},
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "缺少工序" in response.get_json()["error"]


def test_work_time_route_batch_requires_edit_permission(client, test_order_id):
    ids = _fixture_ids(client, test_order_id)
    username = "worktime_create_only"
    password = "Test@1234"
    with client.application.app_context():
        import bcrypt
        db = get_db()
        role_id = db.execute(
            "INSERT INTO roles (name, code, description, permissions, status, level) "
            "VALUES (?, ?, ?, ?, 'active', 1)",
            (
                "工时新增测试角色",
                "worktime_create_only",
                "pytest work time create only",
                json.dumps(["work_time:view", "work_time:create"], ensure_ascii=False),
            ),
        ).lastrowid
        user_id = db.execute(
            "INSERT INTO users (username, password, name, role, status, password_version, employee_no) "
            "VALUES (?, ?, ?, ?, 'active', 2, ?)",
            (
                username,
                bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
                "Work Time Create Only",
                "worktime_create_only",
                "TEST-WT-CREATE-ONLY",
            ),
        ).lastrowid
        db.execute("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", (user_id, role_id))
        db.commit()

    login = client.post("/api/auth/login", json={"username": username, "password": password})
    token = login.get_json()["user"]["token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.post(
        "/api/work-time/standards/route",
        json={
            "route_id": ids["route_id"],
            "items": [
                {
                    "process_id": ids["process_id"],
                    "enabled": True,
                    "standard_minutes_per_unit": 10,
                    "setup_minutes": 0,
                    "difficulty_factor": 1,
                }
            ],
        },
        headers=headers,
    )

    assert response.status_code == 403


def test_work_time_standard_routes_include_unconfigured_route_processes(client, auth_headers, test_order_id):
    ids = _fixture_ids(client, test_order_id)

    response = client.get(
        f"/api/work-time/standards/routes?route_id={ids['route_id']}",
        headers=auth_headers,
    )

    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert payload["total"] == 1
    assert len(payload["route_groups"]) == 1
    group = payload["route_groups"][0]
    assert group["route_id"] == ids["route_id"]
    assert group["process_count"] == 1
    assert group["configured_count"] == 0
    assert group["items"][0]["process_id"] == ids["process_id"]
    assert group["items"][0]["id"] is None



def test_work_time_record_rejects_process_outside_order_route(client, auth_headers, test_order_id):
    ids = _fixture_ids(client, test_order_id)
    with client.application.app_context():
        db = get_db()
        other_process_id = db.execute(
            "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
            "VALUES ('Fixture Outside Work Time Process', 'pytest fixture process', 'fixture', 199, 'active', datetime('now','localtime'))"
        ).lastrowid
        db.commit()

    response = client.post(
        "/api/work-time/records",
        json={
            "order_id": test_order_id,
            "process_id": other_process_id,
            "user_id": ids["user_id"],
            "quantity": 1,
            "start_time": "2026-01-03 08:00:00",
            "end_time": "2026-01-03 08:30:00",
        },
        headers=auth_headers,
    )

    assert response.status_code == 400
    assert "不属于该订单" in response.get_json()["error"]


def test_work_time_record_allows_missing_standard_and_marks_snapshot(client, auth_headers, test_order_id):
    ids = _fixture_ids(client, test_order_id)

    response = client.post(
        "/api/work-time/records",
        json={
            "order_id": test_order_id,
            "process_id": ids["process_id"],
            "user_id": ids["user_id"],
            "quantity": 3,
            "start_time": "2026-01-04 08:00:00",
            "end_time": "2026-01-04 09:00:00",
        },
        headers=auth_headers,
    )

    assert response.status_code == 200, response.get_json()
    record_id = response.get_json()["id"]
    records = client.get("/api/work-time/records?standard_missing=1", headers=auth_headers)
    assert records.status_code == 200, records.get_json()
    record = next(item for item in records.get_json()["items"] if item["id"] == record_id)
    assert record["standard_missing"] == 1
    assert record["standard_minutes"] == 0
    assert record["route_id"] == ids["route_id"]
    assert record["product_code"] == ids["product_code"]


def test_work_time_daily_stats_and_performance_metrics_include_approved_records(client, auth_headers, test_order_id):
    ids = _fixture_ids(client, test_order_id)
    standard_response = client.post(
        "/api/work-time/standards",
        json={
            "route_id": ids["route_id"],
            "process_id": ids["process_id"],
            "standard_minutes_per_unit": 20,
            "setup_minutes": 0,
            "difficulty_factor": 1,
            "effective_from": "2026-01-01",
            "status": "active",
        },
        headers=auth_headers,
    )
    assert standard_response.status_code == 200, standard_response.get_json()
    record_response = client.post(
        "/api/work-time/records",
        json={
            "order_id": test_order_id,
            "process_id": ids["process_id"],
            "user_id": ids["user_id"],
            "quantity": 2,
            "start_time": "2026-01-05 08:00:00",
            "end_time": "2026-01-05 09:00:00",
        },
        headers=auth_headers,
    )
    assert record_response.status_code == 200, record_response.get_json()

    daily = client.get("/api/stats/daily?date=2026-01-05", headers=auth_headers)
    assert daily.status_code == 200, daily.get_json()
    work_time_summary = daily.get_json()["work_time_summary"]
    assert work_time_summary["record_count"] >= 1
    assert work_time_summary["effective_minutes"] >= 60
    assert work_time_summary["efficiency"] > 0

    from modules.services.performance_service import PerformanceService
    with client.application.app_context():
        metrics = PerformanceService.worker_month_metrics(ids["user_id"], "2026-01")
    assert metrics["work_time_record_count"] >= 1
    assert metrics["work_time_effective_minutes"] >= 60
    assert metrics["work_time_efficiency"] > 0
