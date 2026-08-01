import pytest
from concurrent.futures import ThreadPoolExecutor

from factories import WORKER_HASH, create_order, ensure_process, ensure_user
from modules.db import get_db
from modules.domain.errors import ConflictError, ValidationError
from modules.services.rework_service import ReworkService


def _rework_context(db):
    process_id = ensure_process(db, "返修测试工序")
    order_id = create_order(db, [process_id], quantity=20)
    user_id = ensure_user(
        db, "reworkworker", WORKER_HASH, "返修员工", "worker", "RW-001", "员工组"
    )
    return order_id, process_id, user_id


def test_create_rework_updates_process_and_order_totals(client):
    with client.application.app_context():
        db = get_db()
        order_id, process_id, user_id = _rework_context(db)
        rework_id = ReworkService.create_rework(order_id, process_id, user_id, 3, "尺寸偏差")

        record = db.execute("SELECT * FROM rework_records WHERE id = ?", (rework_id,)).fetchone()
        process = db.execute(
            "SELECT rework FROM order_processes WHERE order_id = ? AND process_id = ?",
            (order_id, process_id),
        ).fetchone()
        order = db.execute("SELECT rework FROM orders WHERE id = ?", (order_id,)).fetchone()
        assert record["status"] == "pending"
        assert record["reason"] == "尺寸偏差"
        assert process["rework"] == 3
        assert order["rework"] == 3


@pytest.mark.parametrize("quantity", [0, -1])
def test_create_rework_rejects_non_positive_quantity(client, quantity):
    with client.application.app_context():
        db = get_db()
        order_id, process_id, user_id = _rework_context(db)
        with pytest.raises(ValidationError, match="返工数量"):
            ReworkService.create_rework(order_id, process_id, user_id, quantity)


def test_create_rework_rejects_process_outside_order_without_partial_writes(client):
    with client.application.app_context():
        db = get_db()
        order_id, process_id, user_id = _rework_context(db)
        unrelated_process_id = ensure_process(db, "非订单返修工序", seq_order=99)

        with pytest.raises(ValidationError, match="不在订单工艺路线"):
            ReworkService.create_rework(
                order_id, unrelated_process_id, user_id, 2, "非法工序"
            )

        assert db.execute("SELECT COUNT(*) FROM rework_records").fetchone()[0] == 0
        process = db.execute(
            "SELECT rework FROM order_processes WHERE order_id = ? AND process_id = ?",
            (order_id, process_id),
        ).fetchone()
        order = db.execute("SELECT rework FROM orders WHERE id = ?", (order_id,)).fetchone()
        assert process["rework"] == 0
        assert order["rework"] == 0


def test_complete_rework_persists_result_and_rejects_repeat(client):
    with client.application.app_context():
        db = get_db()
        order_id, process_id, user_id = _rework_context(db)
        rework_id = ReworkService.create_rework(order_id, process_id, user_id, 2, "焊点返修")

        ReworkService.complete_rework(rework_id, "", user_id, "ok", "复检合格")

        record = db.execute("SELECT * FROM rework_records WHERE id = ?", (rework_id,)).fetchone()
        assert record["status"] == "completed"
        assert record["completed_by"] == user_id
        assert record["result"] == "ok"
        assert record["result_remark"] == "复检合格"
        with pytest.raises(ConflictError, match="已完成"):
            ReworkService.complete_rework(rework_id, "", user_id, "ok")


def test_complete_rework_is_atomic_under_concurrent_requests(client):
    with client.application.app_context():
        db = get_db()
        order_id, process_id, user_id = _rework_context(db)
        rework_id = ReworkService.create_rework(order_id, process_id, user_id, 1, "并发返工")

    def complete_once(result):
        with client.application.app_context():
            try:
                ReworkService.complete_rework(rework_id, "", user_id, result)
                return "completed"
            except ConflictError:
                return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(complete_once, ["ok", "scrap"]))

    assert sorted(outcomes) == ["completed", "conflict"]
    with client.application.app_context():
        record = get_db().execute(
            "SELECT status, result FROM rework_records WHERE id = ?", (rework_id,)
        ).fetchone()
        assert record["status"] == "completed"
        assert record["result"] in {"ok", "scrap"}


def test_batch_complete_reports_missing_and_completed_records(client, monkeypatch):
    with client.application.app_context():
        db = get_db()
        order_id, process_id, user_id = _rework_context(db)
        pending_id = ReworkService.create_rework(order_id, process_id, user_id, 1, "待完成")
        completed_id = ReworkService.create_rework(order_id, process_id, user_id, 1, "已完成")
        ReworkService.complete_rework(completed_id, "", user_id, "ok")

        result = ReworkService.batch_complete(
            [pending_id, completed_id, 999999], "批量处理", user_id, "ok"
        )
        assert result["completed"] == 1
        assert {item["id"] for item in result["errors"]} == {completed_id, 999999}


def test_rework_filters_stats_and_export_reflect_records(client):
    with client.application.app_context():
        db = get_db()
        order_id, process_id, user_id = _rework_context(db)
        ReworkService.create_rework(order_id, process_id, user_id, 4, "表面划伤")

        listed = ReworkService.list_rework(
            status="pending", search="返修员工", worker_id=user_id, process_id=process_id
        )
        assert listed["total"] == 1
        assert listed["items"][0]["quantity"] == 4
        assert ReworkService.get_stats()["pending_qty"] == 4
        output = ReworkService.export_rework(status="pending", worker_id=user_id)
        assert output.getbuffer().nbytes > 0


def test_completed_rework_reason_is_read_only(client):
    with client.application.app_context():
        db = get_db()
        order_id, process_id, user_id = _rework_context(db)
        rework_id = ReworkService.create_rework(order_id, process_id, user_id, 1, "原始原因")
        ReworkService.complete_rework(rework_id, "", user_id, "ok")

        with pytest.raises(ConflictError, match="不能修改"):
            ReworkService.update_rework(rework_id, "篡改原因")

        reason = db.execute(
            "SELECT reason FROM rework_records WHERE id = ?", (rework_id,)
        ).fetchone()["reason"]
        assert reason == "原始原因"


def test_worker_stats_use_worker_identity_instead_of_duplicate_names(client):
    with client.application.app_context():
        db = get_db()
        process_id = ensure_process(db, "重名员工统计工序")
        first_order = create_order(db, [process_id], quantity=20)
        second_order = create_order(db, [process_id], quantity=20)
        first_user = ensure_user(
            db, "same-name-worker-1", WORKER_HASH, "同名员工", "worker", "RW-SAME-1", "员工组"
        )
        second_user = ensure_user(
            db, "same-name-worker-2", WORKER_HASH, "同名员工", "worker", "RW-SAME-2", "员工组"
        )
        ReworkService.create_rework(first_order, process_id, first_user, 2, "第一人")
        ReworkService.create_rework(second_order, process_id, second_user, 3, "第二人")
        db.execute(
            "INSERT INTO work_records (order_id, process_id, user_id, quantity, type, status) "
            "VALUES (?, ?, ?, 10, 'normal', 'approved')",
            (first_order, process_id, first_user),
        )
        db.execute(
            "INSERT INTO work_records (order_id, process_id, user_id, quantity, type, status) "
            "VALUES (?, ?, ?, 20, 'normal', 'approved')",
            (second_order, process_id, second_user),
        )
        db.commit()

        stats = {item["worker_id"]: item for item in ReworkService.worker_rework_stats()}
        assert stats[first_user]["total_qty"] == 10
        assert stats[first_user]["rate"] == 20.0
        assert stats[second_user]["total_qty"] == 20
        assert stats[second_user]["rate"] == 15.0


def test_rework_routes_validate_invariants_and_http_statuses(client, auth_headers):
    with client.application.app_context():
        db = get_db()
        order_id, process_id, _ = _rework_context(db)
        unrelated_process_id = ensure_process(db, "接口非法返修工序", seq_order=98)

    invalid_process = client.post(
        "/api/rework",
        headers=auth_headers,
        json={
            "order_id": order_id,
            "process_id": unrelated_process_id,
            "quantity": 1,
            "reason": "非法工序",
        },
    )
    assert invalid_process.status_code == 400, invalid_process.get_json()
    assert invalid_process.get_json()["code"] == "validation_error"

    created = client.post(
        "/api/rework",
        headers=auth_headers,
        json={
            "order_id": order_id,
            "process_id": process_id,
            "quantity": 1,
            "reason": "接口返工",
        },
    )
    assert created.status_code == 200, created.get_json()
    rework_id = created.get_json()["id"]

    invalid_result = client.post(
        f"/api/rework/{rework_id}/complete",
        headers=auth_headers,
        json={"result": "unknown"},
    )
    assert invalid_result.status_code == 400, invalid_result.get_json()

    completed = client.post(
        f"/api/rework/{rework_id}/complete",
        headers=auth_headers,
        json={"result": "ok", "result_remark": "完成"},
    )
    assert completed.status_code == 200, completed.get_json()

    repeated = client.post(
        f"/api/rework/{rework_id}/complete",
        headers=auth_headers,
        json={"result": "scrap"},
    )
    assert repeated.status_code == 409, repeated.get_json()
    assert repeated.get_json()["code"] == "conflict"

    edit_completed = client.put(
        f"/api/rework/{rework_id}",
        headers=auth_headers,
        json={"reason": "不允许修改"},
    )
    assert edit_completed.status_code == 409, edit_completed.get_json()

    missing = client.put(
        "/api/rework/999999",
        headers=auth_headers,
        json={"reason": "不存在"},
    )
    assert missing.status_code == 404, missing.get_json()
