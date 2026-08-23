import inspect
import json

from modules.db import get_db
from factories import ensure_user, WORKER_HASH, WORKER_PASS
from modules.services.performance_service import PerformanceService


def test_v2_fact_collection_has_no_legacy_calendar_month_dependency():
    from modules.repositories.performance_fact_repository import PerformanceFactRepository
    from modules.repositories.performance_repository import PerformanceRepository
    from modules.services.performance_fact_collector import PerformanceFactCollector

    repository_source = inspect.getsource(PerformanceFactRepository)
    collector_source = inspect.getsource(PerformanceFactCollector)
    assert " LIKE " not in repository_source
    assert "DATE(" not in repository_source.upper()
    assert "reporting_month_bounds" in collector_source
    assert "PerformanceRepository" not in collector_source
    assert "Legacy V1" in (PerformanceRepository.worker_month_metrics.__doc__ or "")


def test_performance_ledger_responsibilities_have_stable_module_boundaries():
    from modules.services.performance_ledger_service import PerformanceLedgerService

    assert PerformanceLedgerService.create_batch.__func__.__module__.endswith(
        "performance_ledger_service"
    )
    assert PerformanceLedgerService.submit_approval.__func__.__module__.endswith(
        "performance_ledger_workflow"
    )
    assert PerformanceLedgerService.save_supervisor_review.__func__.__module__.endswith(
        "performance_ledger_review"
    )
    assert PerformanceLedgerService.list_batches.__func__.__module__.endswith(
        "performance_ledger_queries"
    )
    assert PerformanceLedgerService._score_candidates.__func__.__module__.endswith(
        "performance_ledger_scoring"
    )


def _worker_id(db):
    ensure_user(db, "perfworker", WORKER_HASH, "绩效测试员工", "worker", "TEST-PERF-WORKER")
    row = db.execute("SELECT id FROM users WHERE username = 'perfworker'").fetchone()
    return row["id"]


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
    stale_legacy_write = client.put(
        f"/api/handoff-reviews/{payload['id']}/status",
        json={"status": "rejected", "confirm_note": "旧接口重复处理终态评价"},
        headers=auth_headers,
    )
    assert stale_legacy_write.status_code == 409
    assert stale_legacy_write.get_json()["code"] == "conflict"

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


def test_legacy_handoff_status_rejects_old_performance_edit_permission(client):
    username = "legacy_perf_editor"
    with client.application.app_context():
        db = get_db()
        user_id = ensure_user(
            db, username, WORKER_HASH, "旧绩效编辑用户", "worker", "TEST-LEGACY-PERF"
        )
        role_id = db.execute(
            "INSERT INTO roles (name, code, description, permissions, status, level) "
            "VALUES (?, ?, ?, ?, 'active', 1)",
            (
                "旧绩效编辑角色",
                "legacy_performance_editor",
                "仅保留旧 performance:edit 权限",
                json.dumps(["performance:edit"]),
            ),
        ).lastrowid
        db.execute("DELETE FROM user_roles WHERE user_id = ?", (user_id,))
        db.execute(
            "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
            (user_id, role_id),
        )
        db.commit()
    login = client.post(
        "/api/auth/login", json={"username": username, "password": WORKER_PASS}
    )
    assert login.status_code == 200, login.get_json()
    headers = {"Authorization": f"Bearer {login.get_json()['user']['token']}"}

    response = client.put(
        "/api/handoff-reviews/999999/status",
        headers=headers,
        json={"status": "confirmed", "confirm_note": "不应获得新版评价复核权限"},
    )

    assert response.status_code == 403


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
