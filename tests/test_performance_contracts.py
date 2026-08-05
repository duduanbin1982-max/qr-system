import json

from modules.db import get_db
from factories import ensure_user, WORKER_HASH
from modules.services.performance_service import PerformanceService
from modules.services.process_quality_evaluation_service import ProcessQualityEvaluationService


def _worker_id(db):
    ensure_user(db, "perfworker", WORKER_HASH, "绩效测试员工", "worker", "TEST-PERF-WORKER")
    row = db.execute("SELECT id FROM users WHERE username = 'perfworker'").fetchone()
    return row["id"]


def _seed_performance_record(
    client,
    year_month="2026-06",
    quantity=5,
    username="perfworker",
    order_no="TEST-PERF-001",
):
    with client.application.app_context():
        db = get_db()
        ensure_user(db, username, WORKER_HASH, "绩效测试员工", "worker", "TEST-PERF-WORKER")
        user_id = db.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()["id"]
        process_id = db.execute("SELECT id FROM processes WHERE status='active' ORDER BY id LIMIT 1").fetchone()["id"]
        order_id = db.execute(
            "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status) "
            "VALUES (?, 'Test Customer', 'Cross Module Product', 'XMOD-PERF', 20, 'producing')",
            (order_no,),
        ).lastrowid
        db.execute(
            "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, status, created_at) "
            "VALUES (?, ?, ?, 'normal', ?, 'approved', ?)",
            (order_id, process_id, user_id, quantity, year_month + "-10 08:00:00"),
        )
        db.commit()
    return user_id


def test_performance_generate_scores(client, auth_headers):
    year_month = "2026-06"
    user_id = _seed_performance_record(client, year_month)

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


def test_performance_improvement_plan_lifecycle(client, auth_headers):
    year_month = "2026-06"
    user_id = _seed_performance_record(client, year_month)
    generate = client.post("/api/performance/generate", json={"year_month": year_month}, headers=auth_headers)
    assert generate.status_code == 200, generate.get_json()
    scores = client.get(f"/api/performance/scores?year_month={year_month}", headers=auth_headers)
    row = next(item for item in scores.get_json()["items"] if item["user_id"] == user_id)

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


def test_rework_records_affect_performance_quality_score(client, auth_headers):
    year_month = "2026-09"
    with client.application.app_context():
        db = get_db()
        user_id = ensure_user(db, "perfrework", WORKER_HASH, "绩效返工员工", "worker", "TEST-PERF-REWORK")
        process_id = db.execute("SELECT id FROM processes WHERE status='active' ORDER BY id LIMIT 1").fetchone()["id"]
        order_id = db.execute(
            "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status) "
            "VALUES ('TEST-PERF-REWORK-001', 'Test Customer', 'Cross Module Product', 'XMOD-PERF-RW', 20, 'producing')"
        ).lastrowid
        db.execute(
            "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, status, created_at) "
            "VALUES (?, ?, ?, 'normal', 10, 'approved', '2026-09-10 08:00:00')",
            (order_id, process_id, user_id),
        )
        db.execute(
            "INSERT INTO rework_records (order_id, process_id, user_id, quantity, reason, created_at) "
            "VALUES (?, ?, ?, 3, '返工计分测试', '2026-09-10 09:00:00')",
            (order_id, process_id, user_id),
        )
        db.commit()

    generate = client.post("/api/performance/generate", json={"year_month": year_month}, headers=auth_headers)
    assert generate.status_code == 200, generate.get_json()

    payload = client.get(f"/api/performance/scores?year_month={year_month}", headers=auth_headers).get_json()
    row = next(item for item in payload["items"] if item["user_id"] == user_id)
    assert row["rework_qty"] == 3
    assert row["score_details"]["bad_qty"] == 3
    assert row["quality_score"] < 30
    assert "质量扣项3件" in row["warning_reason"]


def _seed_position_performance(client, year_month="2026-11"):
    with client.application.app_context():
        db = get_db()
        welding_position = db.execute(
            "INSERT INTO positions (name, description, status) VALUES ('绩效焊接岗位', 'pytest fixture process', 'active')"
        ).lastrowid
        assembly_position = db.execute(
            "INSERT INTO positions (name, description, status) VALUES ('绩效装配岗位', 'pytest fixture process', 'active')"
        ).lastrowid
        welding_low = ensure_user(db, "perfweldlow", WORKER_HASH, "绩效焊接低产", "worker", "TEST-PERF-WELD-L")
        welding_high = ensure_user(db, "perfweldhigh", WORKER_HASH, "绩效焊接高产", "worker", "TEST-PERF-WELD-H")
        assembly_worker = ensure_user(db, "perfassembly", WORKER_HASH, "绩效装配员工", "worker", "TEST-PERF-ASM")
        db.execute("UPDATE users SET position_id = ? WHERE id IN (?, ?)", (welding_position, welding_low, welding_high))
        db.execute("UPDATE users SET position_id = ? WHERE id = ?", (assembly_position, assembly_worker))
        process_id = db.execute("SELECT id FROM processes WHERE status='active' ORDER BY id LIMIT 1").fetchone()["id"]
        for order_no, user_id, quantity in [
            ("TEST-PERF-POS-WL", welding_low, 5),
            ("TEST-PERF-POS-WH", welding_high, 10),
            ("TEST-PERF-POS-ASM", assembly_worker, 2),
        ]:
            order_id = db.execute(
                "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status) "
                "VALUES (?, 'Test Customer', 'Cross Module Product', 'XMOD-PERF-POS', 20, 'producing')",
                (order_no,),
            ).lastrowid
            db.execute(
                "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, status, created_at) "
                "VALUES (?, ?, ?, 'normal', ?, 'approved', '2026-11-10 08:00:00')",
                (order_id, process_id, user_id, quantity),
            )
        db.commit()
    return welding_position, assembly_position, welding_low, welding_high, assembly_worker


def test_performance_scores_use_position_max_output_and_rank(client, auth_headers):
    year_month = "2026-11"
    welding_position, assembly_position, welding_low, welding_high, assembly_worker = _seed_position_performance(
        client, year_month
    )
    generate = client.post("/api/performance/generate", json={"year_month": year_month}, headers=auth_headers)
    assert generate.status_code == 200, generate.get_json()

    payload = client.get(f"/api/performance/scores?year_month={year_month}", headers=auth_headers).get_json()
    rows = {item["user_id"]: item for item in payload["items"]}
    assert rows[welding_low]["score_details"]["position_max_output"] == 10
    assert rows[welding_high]["score_details"]["position_max_output"] == 10
    assert rows[assembly_worker]["score_details"]["position_max_output"] == 2
    assert rows[assembly_worker]["output_score"] == 35
    assert rows[welding_low]["output_score"] < rows[welding_high]["output_score"]
    assert rows[assembly_worker]["rank_no"] == 1
    assert rows[assembly_worker]["rank_total"] == 1
    assert rows[welding_high]["rank_no"] == 1
    assert rows[welding_high]["rank_total"] == 2


def test_performance_scores_filter_by_position(client, auth_headers):
    year_month = "2026-11"
    welding_position, _assembly_position, welding_low, welding_high, _assembly_worker = _seed_position_performance(
        client, year_month
    )
    generate = client.post("/api/performance/generate", json={"year_month": year_month}, headers=auth_headers)
    assert generate.status_code == 200, generate.get_json()

    filtered = client.get(
        f"/api/performance/scores?year_month={year_month}&position_id={welding_position}",
        headers=auth_headers,
    ).get_json()
    assert filtered["summary"]["total"] == 2
    assert filtered["all_summary"]["total"] >= 3
    assert {item["user_id"] for item in filtered["items"]} == {welding_low, welding_high}
    assert any(option["id"] == welding_position for option in filtered["position_options"])



def test_inspection_failures_are_attributed_to_actual_worker_not_inspector(client, auth_headers):
    year_month = "2026-10"
    serial_no = "TEST-PERF-QC-001-001"
    with client.application.app_context():
        db = get_db()
        worker_id = ensure_user(db, "perfqcworker", WORKER_HASH, "绩效抽检员工", "worker", "TEST-PERF-QC-W")
        inspector_id = ensure_user(db, "perfqcinspector", WORKER_HASH, "绩效抽检员", "qc_inspector", "TEST-PERF-QC-I")
        process_id = db.execute("SELECT id FROM processes WHERE status='active' ORDER BY id LIMIT 1").fetchone()["id"]
        order_id = db.execute(
            "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status, qr_mode) "
            "VALUES ('TEST-PERF-QC-001', 'Test Customer', 'Cross Module Product', 'XMOD-PERF-QC', 1, 'producing', 'serial')"
        ).lastrowid
        db.execute(
            "INSERT INTO order_processes (order_id, process_id, seq_order, status, completed, scrapped, rework) "
            "VALUES (?, ?, 1, 'pending', 0, 0, 0)",
            (order_id, process_id),
        )
        db.execute(
            "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, status, serial_no, created_at) "
            "VALUES (?, ?, ?, 'normal', 1, 'approved', ?, '2026-10-10 08:00:00')",
            (order_id, process_id, worker_id, serial_no),
        )
        db.execute(
            "INSERT INTO quality_inspections ("
            "order_id, process_id, inspection_type, inspector_id, quantity_checked, quantity_passed, "
            "quantity_failed, result, serial_no, inspected_at"
            ") VALUES (?, ?, 'in_process', ?, 1, 0, 1, 'fail', ?, '2026-10-10 09:00:00')",
            (order_id, process_id, inspector_id, serial_no),
        )
        db.commit()

    generate = client.post("/api/performance/generate", json={"year_month": year_month}, headers=auth_headers)
    assert generate.status_code == 200, generate.get_json()

    payload = client.get(f"/api/performance/scores?year_month={year_month}", headers=auth_headers).get_json()
    worker_row = next(item for item in payload["items"] if item["user_id"] == worker_id)
    assert worker_row["inspection_failed_qty"] == 1
    assert worker_row["score_details"]["bad_qty"] == 1
    assert worker_row["quality_score"] < 30
    assert all(item["user_id"] != inspector_id for item in payload["items"])



def _seed_handoff_performance(client, year_month=None, order_mode=False):
    year_month = year_month or PerformanceService.current_month()
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
        order_no = "TEST-HANDOFF-ORDER-001" if order_mode else "TEST-HANDOFF-001"
        order_id = db.execute(
            "INSERT INTO orders (order_no, customer, product_name, product_code, quantity, status, qr_mode) "
            "VALUES (?, 'Test Customer', 'Cross Module Product', 'XMOD-HAND', ?, 'producing', ?)",
            (order_no, 10 if order_mode else 1, "" if order_mode else "serial"),
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
        if order_mode:
            db.execute(
                "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, status, created_at) "
                "VALUES (?, ?, ?, 'normal', 4, 'approved', ?)",
                (order_id, p1, prev_user_id, year_month + '-01 08:00:00'),
            )
            db.execute(
                "INSERT INTO work_records (order_id, process_id, user_id, type, quantity, status, created_at) "
                "VALUES (?, ?, ?, 'normal', 6, 'approved', ?)",
                (order_id, p1, next_user_id, year_month + '-01 09:00:00'),
            )
        else:
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
    return {
        "year_month": year_month,
        "order_id": order_id,
        "to_process_id": p2,
        "previous_user_id": prev_user_id,
        "serial_no": "TEST-HANDOFF-001-001",
    }


def _generate_performance_scores(client, auth_headers, year_month):
    response = client.post(
        "/api/performance/generate",
        json={"year_month": year_month},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.get_json()
    return client.get(
        f"/api/performance/scores?year_month={year_month}", headers=auth_headers
    ).get_json()


def _confirm_handoff_review(client, auth_headers, data):
    review = client.post(
        "/api/handoff-reviews",
        json={
            "order_id": data["order_id"],
            "to_process_id": data["to_process_id"],
            "serial_no": data["serial_no"],
            "rating": 2,
            "issue_type": "外观问题",
            "comment": "接手发现毛刺明显",
        },
        headers=auth_headers,
    )
    assert review.status_code == 200, review.get_json()
    review_payload = review.get_json()
    review_id = review_payload["id"]
    update = client.put(
        f"/api/handoff-reviews/{review_id}/status",
        json={"status": "confirmed", "confirm_note": "确认属实"},
        headers=auth_headers,
    )
    assert update.status_code == 200, update.get_json()
    return review_payload


def test_handoff_review_identifies_previous_worker(client, auth_headers):
    data = _seed_handoff_performance(client)
    pending = client.get(
        f"/api/handoff-reviews/pending?order_id={data['order_id']}"
        f"&to_process_id={data['to_process_id']}&serial_no={data['serial_no']}",
        headers=auth_headers,
    )
    assert pending.status_code == 200, pending.get_json()
    assert pending.get_json()["required"] is True
    assert pending.get_json()["from_user_id"] == data["previous_user_id"]


def test_handoff_review_penalizes_previous_worker(client, auth_headers):
    data = _seed_handoff_performance(client)
    ProcessQualityEvaluationService.save_rules({"minimum_samples_for_performance": 1})
    before = _generate_performance_scores(client, auth_headers, data["year_month"])
    before_row = next(
        item for item in before["items"] if item["user_id"] == data["previous_user_id"]
    )
    _confirm_handoff_review(client, auth_headers, data)
    after = _generate_performance_scores(client, auth_headers, data["year_month"])
    after_row = next(
        item for item in after["items"] if item["user_id"] == data["previous_user_id"]
    )
    assert after_row["score_details"]["handoff_low_count"] == 1
    assert after_row["score_details"]["handoff_penalty"] > 0
    assert after_row["quality_score"] < before_row["quality_score"]

    reviews = client.get(
        f"/api/handoff-reviews?year_month={data['year_month']}", headers=auth_headers
    )
    assert reviews.status_code == 200, reviews.get_json()
    assert reviews.get_json()["total"] >= 1


def test_legacy_handoff_review_is_backed_by_authoritative_evaluation(client, auth_headers):
    data = _seed_handoff_performance(client)
    review = client.post(
        "/api/handoff-reviews",
        json={
            "order_id": data["order_id"],
            "to_process_id": data["to_process_id"],
            "serial_no": data["serial_no"],
            "rating": 2,
            "issue_type": "外观问题",
            "comment": "兼容接口评价",
        },
        headers=auth_headers,
    )
    assert review.status_code == 200, review.get_json()
    assert review.headers["Deprecation"] == "true"
    payload = review.get_json()
    assert payload["evaluation_id"]

    confirmed = client.put(
        f"/api/process-quality-evaluations/{payload['evaluation_id']}/review",
        json={"status": "confirmed", "note": "新模型核验"},
        headers=auth_headers,
    )
    assert confirmed.status_code == 200, confirmed.get_json()

    with client.application.app_context():
        db = get_db()
        legacy = db.execute(
            "SELECT status FROM process_handoff_reviews WHERE id = ?", (payload["id"],)
        ).fetchone()
        evaluation = db.execute(
            "SELECT status FROM process_quality_evaluations WHERE id = ?", (payload["evaluation_id"],)
        ).fetchone()
        event_sources = db.execute(
            "SELECT source.source_type,source.quality_event_id "
            "FROM performance_quality_event_sources source WHERE "
            "(source.source_type='process_quality_evaluation' AND source.source_id=?) OR "
            "(source.source_type='process_handoff_review' AND source.source_id=?)",
            (payload["evaluation_id"], payload["id"]),
        ).fetchall()
        assert legacy["status"] == "confirmed"
        assert evaluation["status"] == "confirmed"
        assert {row["source_type"] for row in event_sources} == {
            "process_quality_evaluation",
            "process_handoff_review",
        }
        assert len({row["quality_event_id"] for row in event_sources}) == 1


def test_order_mode_handoff_review_requires_clear_previous_worker(client, auth_headers):
    data = _seed_handoff_performance(client, "2026-08", order_mode=True)
    pending = client.get(
        f"/api/handoff-reviews/pending?order_id={data['order_id']}"
        f"&to_process_id={data['to_process_id']}",
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
    assert "performance:view_department" in manager_permissions
    assert "performance:review_department" in manager_permissions
    assert "performance:view_all" not in manager_permissions

    inspector_permissions = default_role_permission_additions("qc_inspector")
    assert "page:performance" in inspector_permissions
    assert "performance:view_self" in inspector_permissions
    assert "performance:view_all" not in inspector_permissions
    assert "page:process-quality-evaluation" in inspector_permissions
    assert "process_quality_evaluation:review" in inspector_permissions
