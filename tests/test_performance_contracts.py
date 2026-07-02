import json

from modules.db import get_db
from factories import ensure_user, WORKER_HASH
from modules.services.performance_service import PerformanceService


def _worker_id(db):
    ensure_user(db, "perfworker", WORKER_HASH, "绩效测试员工", "worker", "TEST-PERF-WORKER")
    row = db.execute("SELECT id FROM users WHERE username = 'perfworker'").fetchone()
    return row["id"]


def test_performance_generate_scores_and_improvement_plan(client, auth_headers):
    year_month = "2026-06"
    with client.application.app_context():
        db = get_db()
        user_id = _worker_id(db)
        process_id = db.execute("SELECT id FROM processes WHERE status='active' ORDER BY id LIMIT 1").fetchone()["id"]
        order_id = db.execute(
            "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status) "
            "VALUES ('TEST-PERF-001', 'Test Customer', 'Cross Module Product', 'XMOD-PERF', 10, 'producing')"
        ).lastrowid
        db.execute(
            "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, status, created_at) "
            "VALUES (?, ?, ?, 'normal', 5, 'approved', '2026-06-10 08:00:00')",
            (order_id, process_id, user_id),
        )
        db.commit()

    generate = client.post("/api/performance/generate", json={"year_month": year_month}, headers=auth_headers)
    assert generate.status_code == 200, generate.get_json()
    assert generate.get_json()["generated"] >= 1

    scores = client.get(f"/api/performance/scores?year_month={year_month}", headers=auth_headers)
    assert scores.status_code == 200, scores.get_json()
    payload = scores.get_json()
    assert "summary" in payload
    row = next(item for item in payload["items"] if item["user_id"] == user_id)
    assert row["output_qty"] == 5
    assert row["total_score"] >= 0
    assert row["warning_level"] in {"green", "yellow", "orange", "red"}

    plan = client.post(
        "/api/performance/plans",
        json={
            "score_id": row["id"],
            "user_id": user_id,
            "year_month": year_month,
            "warning_level": row["warning_level"],
            "reason": "测试预警原因",
            "goal": "提升稳定产出",
            "actions": "主管辅导并复评",
        },
        headers=auth_headers,
    )
    assert plan.status_code == 200, plan.get_json()
    plan_id = plan.get_json()["id"]

    update = client.put(
        f"/api/performance/plans/{plan_id}",
        json={"status": "closed", "review_result": "passed", "review_notes": "已完成复评"},
        headers=auth_headers,
    )
    assert update.status_code == 200, update.get_json()

    plans = client.get(f"/api/performance/plans?year_month={year_month}", headers=auth_headers)
    assert plans.status_code == 200, plans.get_json()
    saved = next(item for item in plans.get_json()["plans"] if item["id"] == plan_id)
    assert saved["status"] == "closed"
    assert saved["review_result"] == "passed"



def test_performance_review_inputs_recalculate_scores(client, auth_headers):
    year_month = "2026-07"
    with client.application.app_context():
        db = get_db()
        user_id = _worker_id(db)
        process_id = db.execute("SELECT id FROM processes WHERE status='active' ORDER BY id LIMIT 1").fetchone()["id"]
        order_id = db.execute(
            "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status) "
            "VALUES ('TEST-PERF-REVIEW-001', 'Test Customer', 'Cross Module Product', 'XMOD-PERF-R', 20, 'producing')"
        ).lastrowid
        db.execute(
            "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, status, created_at) "
            "VALUES (?, ?, ?, 'normal', 10, 'approved', '2026-07-10 08:00:00')",
            (order_id, process_id, user_id),
        )
        db.commit()

    generate = client.post("/api/performance/generate", json={"year_month": year_month}, headers=auth_headers)
    assert generate.status_code == 200, generate.get_json()

    before_payload = client.get(f"/api/performance/scores?year_month={year_month}", headers=auth_headers).get_json()
    before = next(item for item in before_payload["items"] if item["user_id"] == user_id)

    review = client.post(
        "/api/performance/reviews",
        json={
            "user_id": user_id,
            "year_month": year_month,
            "discipline_deduction": 3,
            "discipline_reason": "未按现场规范扫码",
            "improvement_adjustment": -1,
            "improvement_reason": "改进跟踪延期",
            "manual_score": 8,
            "manual_comment": "主管评议需继续辅导",
        },
        headers=auth_headers,
    )
    assert review.status_code == 200, review.get_json()

    after_payload = client.get(f"/api/performance/scores?year_month={year_month}", headers=auth_headers).get_json()
    after = next(item for item in after_payload["items"] if item["user_id"] == user_id)
    assert after["discipline_deduction"] == 3
    assert after["discipline_reason"] == "未按现场规范扫码"
    assert after["manual_score"] == 8
    assert after["manual_comment"] == "主管评议需继续辅导"
    assert after["score_details"]["manual_improvement_adjustment"] == -1
    assert after["total_score"] < before["total_score"]
    assert "未按现场规范扫码" in after["warning_reason"]



def test_handoff_review_from_next_process_affects_performance(client, auth_headers):
    year_month = PerformanceService.current_month()
    with client.application.app_context():
        db = get_db()
        prev_user_id = _worker_id(db)
        next_user_id = ensure_user(db, "perfnext", WORKER_HASH, "绩效下工序员工", "worker", "TEST-PERF-NEXT")
        process_rows = db.execute("SELECT id FROM processes WHERE status='active' ORDER BY id LIMIT 2").fetchall()
        if len(process_rows) < 2:
            p1 = db.execute(
                "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
                "VALUES ('Fixture Handoff A', 'pytest fixture process', 'fixture', 1, 'active', datetime('now','localtime'))"
            ).lastrowid
            p2 = db.execute(
                "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
                "VALUES ('Fixture Handoff B', 'pytest fixture process', 'fixture', 2, 'active', datetime('now','localtime'))"
            ).lastrowid
        else:
            p1, p2 = process_rows[0]["id"], process_rows[1]["id"]
        order_id = db.execute(
            "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status, qr_mode) "
            "VALUES ('TEST-HANDOFF-001', 'Test Customer', 'Cross Module Product', 'XMOD-HAND', 1, 'producing', 'serial')"
        ).lastrowid
        db.execute(
            "INSERT INTO order_processes (order_id, process_id, seq_order, status, completed, scrapped, rework) "
            "VALUES (?, ?, 1, 'pending', 0, 0, 0)",
            (order_id, p1),
        )
        db.execute(
            "INSERT INTO order_processes (order_id, process_id, seq_order, status, completed, scrapped, rework) "
            "VALUES (?, ?, 2, 'pending', 0, 0, 0)",
            (order_id, p2),
        )
        db.execute(
            "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, status, serial_no, created_at) "
            "VALUES (?, ?, ?, 'normal', 1, 'approved', 'TEST-HANDOFF-001-001', ?)",
            (order_id, p1, prev_user_id, year_month + '-01 08:00:00'),
        )
        db.execute(
            "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, status, serial_no, created_at) "
            "VALUES (?, ?, ?, 'normal', 1, 'approved', 'TEST-HANDOFF-001-001', ?)",
            (order_id, p2, next_user_id, year_month + '-02 08:00:00'),
        )
        db.commit()

    generate_before = client.post("/api/performance/generate", json={"year_month": year_month}, headers=auth_headers)
    assert generate_before.status_code == 200, generate_before.get_json()
    before = client.get(f"/api/performance/scores?year_month={year_month}", headers=auth_headers).get_json()
    before_row = next(item for item in before["items"] if item["user_id"] == prev_user_id)

    pending = client.get(
        f"/api/handoff-reviews/pending?order_id={order_id}&to_process_id={p2}&serial_no=TEST-HANDOFF-001-001",
        headers=auth_headers,
    )
    assert pending.status_code == 200, pending.get_json()
    assert pending.get_json()["required"] is True
    assert pending.get_json()["from_user_id"] == prev_user_id

    review = client.post(
        "/api/handoff-reviews",
        json={
            "order_id": order_id,
            "to_process_id": p2,
            "serial_no": "TEST-HANDOFF-001-001",
            "rating": 2,
            "issue_type": "外观问题",
            "comment": "接手发现毛刺明显",
        },
        headers=auth_headers,
    )
    assert review.status_code == 200, review.get_json()
    assert review.get_json()["status"] == "pending"

    update = client.put(
        f"/api/handoff-reviews/{review.get_json()['id']}/status",
        json={"status": "confirmed", "confirm_note": "确认属实"},
        headers=auth_headers,
    )
    assert update.status_code == 200, update.get_json()

    generate_after = client.post("/api/performance/generate", json={"year_month": year_month}, headers=auth_headers)
    assert generate_after.status_code == 200, generate_after.get_json()
    after = client.get(f"/api/performance/scores?year_month={year_month}", headers=auth_headers).get_json()
    after_row = next(item for item in after["items"] if item["user_id"] == prev_user_id)
    assert after_row["score_details"]["handoff_low_count"] == 1
    assert after_row["score_details"]["handoff_penalty"] > 0
    assert after_row["quality_score"] < before_row["quality_score"]

    reviews = client.get(f"/api/handoff-reviews?year_month={year_month}", headers=auth_headers)
    assert reviews.status_code == 200, reviews.get_json()
    assert reviews.get_json()["total"] >= 1


def test_order_mode_handoff_review_requires_clear_previous_worker(client, auth_headers):
    year_month = "2026-08"
    with client.application.app_context():
        db = get_db()
        first_prev_user = ensure_user(db, "perfprev1", WORKER_HASH, "绩效上一工序甲", "worker", "TEST-PERF-PREV-1")
        second_prev_user = ensure_user(db, "perfprev2", WORKER_HASH, "绩效上一工序乙", "worker", "TEST-PERF-PREV-2")
        process_rows = db.execute("SELECT id FROM processes WHERE status='active' ORDER BY id LIMIT 2").fetchall()
        if len(process_rows) < 2:
            p1 = db.execute(
                "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
                "VALUES ('Fixture Handoff C', 'pytest fixture process', 'fixture', 1, 'active', datetime('now','localtime'))"
            ).lastrowid
            p2 = db.execute(
                "INSERT INTO processes (name, description, category, seq_order, status, updated_at) "
                "VALUES ('Fixture Handoff D', 'pytest fixture process', 'fixture', 2, 'active', datetime('now','localtime'))"
            ).lastrowid
        else:
            p1, p2 = process_rows[0]["id"], process_rows[1]["id"]
        order_id = db.execute(
            "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status, qr_mode) "
            "VALUES ('TEST-HANDOFF-ORDER-001', 'Test Customer', 'Cross Module Product', 'XMOD-HAND-O', 10, 'producing', '')"
        ).lastrowid
        db.execute(
            "INSERT INTO order_processes (order_id, process_id, seq_order, status, completed, scrapped, rework) "
            "VALUES (?, ?, 1, 'pending', 0, 0, 0)",
            (order_id, p1),
        )
        db.execute(
            "INSERT INTO order_processes (order_id, process_id, seq_order, status, completed, scrapped, rework) "
            "VALUES (?, ?, 2, 'pending', 0, 0, 0)",
            (order_id, p2),
        )
        db.execute(
            "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, status, created_at) "
            "VALUES (?, ?, ?, 'normal', 4, 'approved', ?)",
            (order_id, p1, first_prev_user, year_month + '-01 08:00:00'),
        )
        db.execute(
            "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, status, created_at) "
            "VALUES (?, ?, ?, 'normal', 6, 'approved', ?)",
            (order_id, p1, second_prev_user, year_month + '-01 09:00:00'),
        )
        db.commit()

    pending = client.get(
        f"/api/handoff-reviews/pending?order_id={order_id}&to_process_id={p2}",
        headers=auth_headers,
    )
    assert pending.status_code == 200, pending.get_json()
    payload = pending.get_json()
    assert payload["required"] is False
    assert "无明确来源" in payload["reason"]


def test_performance_overview_falls_back_to_latest_scored_month(client, auth_headers):
    scored_month = "2026-06"
    empty_month = PerformanceService.current_month()
    with client.application.app_context():
        db = get_db()
        user_id = _worker_id(db)
        process_id = db.execute("SELECT id FROM processes WHERE status='active' ORDER BY id LIMIT 1").fetchone()["id"]
        order_id = db.execute(
            "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status) "
            "VALUES ('TEST-PERF-OVERVIEW-001', 'Test Customer', 'Performance Product', 'PERF-OV', 10, 'producing')"
        ).lastrowid
        db.execute(
            "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, status, created_at) "
            "VALUES (?, ?, ?, 'normal', 3, 'approved', ?)",
            (order_id, process_id, user_id, scored_month + "-10 08:00:00"),
        )
        db.execute(
            "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, status, created_at) "
            "VALUES (?, ?, ?, 'normal', 2, 'approved', ?)",
            (order_id, process_id, user_id, empty_month + "-10 08:00:00"),
        )
        db.commit()

    generate = client.post("/api/performance/generate", json={"year_month": scored_month}, headers=auth_headers)
    assert generate.status_code == 200, generate.get_json()

    overview = client.get(f"/api/performance/overview?year_month={empty_month}", headers=auth_headers)
    assert overview.status_code == 200, overview.get_json()
    payload = overview.get_json()
    assert payload["requested_month"] == empty_month
    assert payload["latest_score_month"] == scored_month
    assert payload["display_month"] == scored_month
    assert payload["requested_month_score_count"] == 0
    assert payload["requested_month_work_record_count"] >= 1


def test_performance_display_month_rule_is_explicit():
    assert PerformanceService.resolve_display_month("2026-07", "2026-06", 0) == "2026-06"
    assert PerformanceService.resolve_display_month("2026-07", "2026-06", 3) == "2026-07"
    assert PerformanceService.resolve_display_month("2026-07", "", 0) == "2026-07"


def test_performance_role_permission_seed_matches_catalog():
    from modules.permission_catalog import default_role_permission_additions

    manager_permissions = default_role_permission_additions("production_manager")
    assert "page:performance" in manager_permissions
    assert "performance:view" in manager_permissions
    assert "performance:create" in manager_permissions
    assert "performance:edit" in manager_permissions

    inspector_permissions = default_role_permission_additions("qc_inspector")
    assert inspector_permissions == ["page:performance", "performance:view"]


def test_performance_page_template_bindings_are_returned():
    from pathlib import Path

    source = Path("frontend/src/views/PerformancePage.vue").read_text(encoding="utf-8")
    assert "????" not in source
    assert "usePerformanceNotice(data)" in source
    assert "usePerformanceModals(data)" in source
    for binding in [
        "performanceNotice",
        "generateCurrentMonthScores",
        "...modals",
        "scoringFormula",
    ]:
        assert binding in source
