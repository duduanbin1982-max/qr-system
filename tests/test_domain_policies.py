from datetime import datetime

from modules.domain.order_focus import OrderFocusPolicy
from modules.domain.order_progress import OrderProgressPolicy
from modules.domain.work_time import WorkTimeRecordPolicy


def test_order_progress_policy_calculates_stuck_items_and_bottleneck():
    result = OrderProgressPolicy.build(
        order_id=7,
        order={
            "order_no": "ORDER-7",
            "product_name": "Test Product",
            "quantity": 2,
            "created_at": "2026-01-01 00:00:00",
            "deadline": "2026-01-03",
        },
        items=[
            {"serial_no": "S1", "current_process_id": 2, "status": "in_progress", "created_at": "2026-01-01 00:00:00"},
            {"serial_no": "S2", "current_process_id": 1, "status": "pending", "created_at": "2026-01-01 00:00:00"},
        ],
        processes=[
            {"process_id": 1, "process_name": "Cut", "seq_order": 1},
            {"process_id": 2, "process_name": "Weld", "seq_order": 2},
        ],
        work_records=[
            {"serial_no": "S1", "process_id": 1, "status": "completed", "created_at": "2026-01-01 08:00:00", "worker_name": "Worker"},
        ],
        standards={1: 10, 2: 20},
        sources={1: "standard", 2: "actual_history"},
        now=datetime(2026, 1, 2, 12, 0, 0),
        threshold=24,
    )

    assert result["summary"]["stuck_workpieces"] == 2
    assert result["summary"]["process_stats"][0]["backlog"] == 1
    assert result["analysis"]["bottlenecks"][0]["process_name"] == "Weld"
    assert result["analysis"]["deadline_risk"]["level"] == "medium"
    assert any("历史实际工时" in item for item in result["analysis"]["recommendations"])


def test_order_progress_policy_handles_order_mode_without_serial_items():
    result = OrderProgressPolicy.build(
        order_id=8,
        order={"order_no": "ORDER-8", "quantity": 10},
        items=[],
        processes=[],
        work_records=[],
        standards={},
        sources={},
        now=datetime(2026, 1, 2, 12, 0, 0),
        threshold=24,
    )

    assert result["analysis"]["tracking_mode"] == "order"
    assert "未生成单件序列号" in result["analysis"]["recommendations"][0]


def test_order_focus_policy_builds_hard_block_warning():
    warning = OrderFocusPolicy.priority_warning(
        {
            "id": 5,
            "order_no": "EARLY-5",
            "process_id": 9,
            "process_name": "Weld",
            "backlog": 3,
        },
        mode="hard",
        hard_block_enabled=True,
        bypass_allowed=False,
    )

    assert warning["blocking"] is True
    assert warning["severity"] == "danger"
    assert warning["recommended_backlog"] == 3
    assert "EARLY-5" in warning["message"]


def test_work_time_policy_calculates_actual_effective_and_standard_minutes():
    result = WorkTimeRecordPolicy.normalize(
        {
            "quantity": 2,
            "start_time": "2026-01-02 08:00:00",
            "end_time": "2026-01-02 09:30:00",
            "pause_minutes": 10,
            "status": "completed",
        },
        {
            "order_id": 1,
            "order_no": "ORDER-1",
            "process_id": 2,
            "process_name": "Weld",
            "user_id": 3,
            "user_name": "Worker",
            "standard_id": 4,
            "standard": {
                "setup_minutes": 5,
                "standard_minutes_per_unit": 10,
                "difficulty_factor": 1.2,
            },
        },
        creator_id=3,
        now_text="2026-01-02 10:00:00",
    )

    assert result["actual_minutes"] == 80
    assert result["effective_minutes"] == 80
    assert result["standard_minutes"] == 29
    assert result["review_status"] == "approved"
    assert result["standard_missing"] == 0


def test_work_time_policy_marks_completed_record_with_abnormal_reason_pending():
    result = WorkTimeRecordPolicy.normalize(
        {
            "start_time": "2026-01-02 08:00:00",
            "end_time": "2026-01-02 09:00:00",
            "status": "completed",
            "abnormal_reason": "设备故障",
        },
        {
            "process_id": 2,
            "process_name": "Weld",
            "user_id": 3,
            "user_name": "Worker",
            "standard": None,
        },
        creator_id=3,
        now_text="2026-01-02 10:00:00",
    )

    assert result["status"] == "abnormal"
    assert result["review_status"] == "pending"
    assert result["standard_missing"] == 1
