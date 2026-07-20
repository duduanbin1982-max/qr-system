import pytest

from factories import WORKER_HASH, create_order, ensure_process, ensure_user
from modules.db import get_db
from modules.services.quality_service import QualityService
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
        with pytest.raises(ValueError, match="greater than 0"):
            ReworkService.create_rework(order_id, process_id, user_id, quantity)


def test_complete_rework_persists_result_when_quality_recheck_fails(client, monkeypatch):
    with client.application.app_context():
        db = get_db()
        order_id, process_id, user_id = _rework_context(db)
        rework_id = ReworkService.create_rework(order_id, process_id, user_id, 2, "焊点返修")

        def fail_recheck(*args, **kwargs):
            raise RuntimeError("inspection unavailable")

        monkeypatch.setattr(QualityService, "create_inspection", fail_recheck)
        ReworkService.complete_rework(rework_id, "", user_id, "ok", "复检合格")

        record = db.execute("SELECT * FROM rework_records WHERE id = ?", (rework_id,)).fetchone()
        assert record["status"] == "completed"
        assert record["completed_by"] == user_id
        assert record["result"] == "ok"
        assert record["result_remark"] == "复检合格"
        with pytest.raises(ValueError, match="already completed"):
            ReworkService.complete_rework(rework_id, "", user_id)


def test_batch_complete_reports_missing_and_completed_records(client, monkeypatch):
    with client.application.app_context():
        db = get_db()
        order_id, process_id, user_id = _rework_context(db)
        pending_id = ReworkService.create_rework(order_id, process_id, user_id, 1, "待完成")
        completed_id = ReworkService.create_rework(order_id, process_id, user_id, 1, "已完成")
        monkeypatch.setattr(QualityService, "create_inspection", lambda *args, **kwargs: None)
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
