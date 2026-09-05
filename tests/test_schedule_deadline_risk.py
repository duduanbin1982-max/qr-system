from datetime import datetime

from modules.domain.schedule_deadline_risk import ScheduleDeadlineRiskPolicy


BASE_NOW = datetime(2026, 9, 4, 10, 0)


def test_late_precision_completion_reports_delay_minutes_and_high_risk():
    result = ScheduleDeadlineRiskPolicy.evaluate(
        deadline_text="2026-09-04",
        projected_completion_at="2026-09-05 02:30",
        now=BASE_NOW,
    )

    assert result["level"] == "high"
    assert result["delay_minutes"] == 150
    assert result["slack_minutes"] == -150
    assert "晚于交期" in result["reason"]


def test_blocked_schedule_is_high_risk_with_source_reason():
    result = ScheduleDeadlineRiskPolicy.evaluate(
        deadline_text="2026-09-20",
        projected_completion_at="",
        now=BASE_NOW,
        blocked_count=1,
        blocked_reasons=("未配置标准工时",),
    )

    assert result["level"] == "high"
    assert result["delay_minutes"] == 0
    assert result["reason"] == "排程被阻断：未配置标准工时"


def test_conflict_without_delay_is_medium_and_conflict_with_delay_is_high():
    safe = ScheduleDeadlineRiskPolicy.evaluate(
        deadline_text="2026-09-20",
        projected_completion_at="2026-09-10 10:00",
        now=BASE_NOW,
        conflict_count=2,
    )
    late = ScheduleDeadlineRiskPolicy.evaluate(
        deadline_text="2026-09-04",
        projected_completion_at="2026-09-05 10:00",
        now=BASE_NOW,
        conflict_count=2,
    )

    assert safe["level"] == "medium"
    assert late["level"] == "high"
    assert late["delay_minutes"] == 600


def test_completed_order_has_no_risk_even_when_projected_time_is_late():
    result = ScheduleDeadlineRiskPolicy.evaluate(
        deadline_text="2026-09-01",
        projected_completion_at="2026-09-03 10:00",
        now=BASE_NOW,
        completed=True,
    )

    assert result["level"] == "none"
    assert result["delay_minutes"] == 0
    assert result["reason"] == "订单已完成"


def test_missing_deadline_is_explicitly_unassessed():
    result = ScheduleDeadlineRiskPolicy.evaluate(
        projected_completion_at="2026-09-05 10:00",
        now=BASE_NOW,
    )

    assert result["level"] == "none"
    assert result["delay_minutes"] == 0
    assert "未设置交期" in result["reason"]
