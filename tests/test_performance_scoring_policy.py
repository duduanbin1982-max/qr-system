from copy import deepcopy
import json

import pytest

from modules.domain.performance_policy import (
    BATCH_STATUS_APPROVED,
    BATCH_STATUS_DRAFT,
    BATCH_STATUS_SUPERVISOR_REVIEW,
    ELIGIBILITY_INSUFFICIENT_DATA,
    PerformanceConflictError,
    assert_row_version,
    production_month_for_timestamp,
    require_row_version,
    validate_batch_transition,
    validate_production_month,
)
from modules.services.performance_scoring_policy import PerformanceScoringPolicy


def _rule():
    return {"id": 51, "version_code": "V2", **PerformanceScoringPolicy.rules()}


def _target(**overrides):
    target = {
        "id": 71,
        "position_id": 7,
        "position_name_snapshot": "焊接岗位",
        "target_output_qty": 100,
        "minimum_effective_work_days": 2,
    }
    target.update(overrides)
    return target


def _metrics(**overrides):
    metrics = {
        "user_id": 11,
        "position_id": 7,
        "output_qty": 50,
        "report_count": 2,
        "work_days": 2,
        "open_improvement_plans": 0,
        "failed_improvement_plans": 0,
        "completed_improvement_plans": 0,
        "unresolved_exception_count": 0,
    }
    metrics.update(overrides)
    return metrics


def test_output_score_uses_versioned_position_target():
    result = PerformanceScoringPolicy.score_worker(
        _rule(),
        _target(target_output_qty=200),
        _metrics(output_qty=50),
        {},
        [],
    )

    assert result["output_score"] == 8.8
    assert result["score_details"]["target_output_qty"] == 200.0
    assert "max_output" not in result["score_details"]


def test_legacy_compatibility_does_not_award_zero_output_full_points():
    result = PerformanceScoringPolicy.score_legacy_worker(
        {
            "output_qty": 0,
            "work_days": 0,
            "scrap_qty": 0,
            "rework_qty": 0,
            "inspection_failed_qty": 0,
            "open_improvement_plans": 0,
            "failed_improvement_plans": 0,
            "completed_improvement_plans": 0,
        },
        0,
        {},
        {},
    )

    assert result["output_score"] == 0.0
    assert result["warning_level"] != "green"


@pytest.mark.parametrize(
    ("target", "metrics", "reason_code"),
    [
        (_target(), _metrics(output_qty=0), "zero_output"),
        (_target(), _metrics(position_id=None), "missing_position"),
        (None, _metrics(), "missing_position_target"),
        (_target(minimum_effective_work_days=3), _metrics(work_days=2), "insufficient_work_days"),
        (_target(), _metrics(unresolved_exception_count=1), "unresolved_data_exception"),
    ],
)
def test_ineligible_inputs_return_no_score_grade_or_rank(target, metrics, reason_code):
    result = PerformanceScoringPolicy.score_worker(_rule(), target, metrics, {}, [])

    assert result["eligibility_status"] == ELIGIBILITY_INSUFFICIENT_DATA
    assert result["eligibility_reason_code"] == reason_code
    assert result["rule_version_id"] == 51
    for field in (
        "output_score",
        "quality_score",
        "delivery_score",
        "discipline_score",
        "improvement_score",
        "total_score",
        "warning_level",
        "rank_no",
        "rank_total",
    ):
        assert result[field] is None


def test_quality_facts_are_deduplicated_by_canonical_event():
    no_defects = PerformanceScoringPolicy.score_worker(
        _rule(), _target(), _metrics(output_qty=100), {}, []
    )
    defect = {
        "canonical_event_id": 9001,
        "event_type": "rework",
        "quantity": 10,
    }
    deduplicated = PerformanceScoringPolicy.score_worker(
        _rule(), _target(), _metrics(output_qty=100), {}, [defect, deepcopy(defect)]
    )

    assert no_defects["quality_score"] == 30.0
    assert no_defects["score_details"]["bad_qty"] == 0.0
    assert deduplicated["score_details"]["bad_qty"] == 10.0
    assert deduplicated["score_details"]["quality_event_count"] == 1
    assert deduplicated["quality_score"] == 27.3


def test_quality_facts_require_stable_identity_and_consistent_duplicates():
    with pytest.raises(ValueError, match="稳定标识"):
        PerformanceScoringPolicy.score_worker(
            _rule(),
            _target(),
            _metrics(),
            {},
            [{"event_type": "rework", "quantity": 1}],
        )
    with pytest.raises(ValueError, match="内容冲突"):
        PerformanceScoringPolicy.score_worker(
            _rule(),
            _target(),
            _metrics(),
            {},
            [
                {"canonical_event_id": 1, "event_type": "rework", "quantity": 1},
                {"quality_event_id": 1, "event_type": "rework", "quantity": 2},
            ],
        )
    with pytest.raises(ValueError, match="事件类型"):
        PerformanceScoringPolicy.score_worker(
            _rule(),
            _target(),
            _metrics(),
            {},
            [{"canonical_event_id": 2, "event_type": "unknown", "quantity": 1}],
        )


def test_dimension_scores_and_manual_adjustment_are_bounded():
    review = {
        "discipline_deduction": 99,
        "discipline_reason": "纪律扣分说明",
        "improvement_adjustment": -99,
        "improvement_reason": "改进扣分说明",
        "manual_score": -99,
        "manual_comment": "主管评议说明",
    }
    quality_facts = [
        {"canonical_event_id": 1, "event_type": "scrap", "quantity": 10000},
        {"canonical_event_id": 2, "event_type": "handoff_review", "rating": 1},
    ]
    result = PerformanceScoringPolicy.score_worker(
        _rule(),
        _target(),
        _metrics(
            output_qty=100,
            work_days=100,
            open_improvement_plans=100,
            failed_improvement_plans=100,
        ),
        review,
        quality_facts,
    )

    assert 0 <= result["quality_score"] <= 30
    assert result["delivery_score"] == 15.0
    assert result["discipline_score"] == 0.0
    assert result["improvement_score"] == 0.0
    assert result["manual_score"] == 0.0
    assert result["manual_adjustment"] == -10.0
    assert 0 <= result["total_score"] <= 100

    attempted_bonus = PerformanceScoringPolicy.score_worker(
        _rule(), _target(), _metrics(), {"manual_score": 99}, []
    )
    assert attempted_bonus["manual_score"] == 10.0
    assert attempted_bonus["manual_adjustment"] == 0.0
    assert attempted_bonus["total_score"] == round(
        attempted_bonus["output_score"]
        + attempted_bonus["quality_score"]
        + attempted_bonus["delivery_score"]
        + attempted_bonus["discipline_score"]
        + attempted_bonus["improvement_score"]
        + attempted_bonus["manual_adjustment"],
        1,
    )


@pytest.mark.parametrize(
    ("review", "message"),
    [
        ({"discipline_deduction": 1}, "纪律扣分原因"),
        ({"improvement_adjustment": -1}, "改进调整原因"),
        ({"manual_score": 9}, "主管评议说明"),
    ],
)
def test_review_deductions_require_reasons(review, message):
    with pytest.raises(ValueError, match=message):
        PerformanceScoringPolicy.score_worker(
            _rule(), _target(), _metrics(), review, []
        )


def test_rank_position_results_requires_three_eligible_workers():
    calculated_at = "2026-08-10 08:30:00"
    two_results = [
        {"user_id": 2, "position_id_snapshot": 7, "eligibility_status": "eligible", "total_score": 90},
        {"user_id": 1, "position_id_snapshot": 7, "eligibility_status": "eligible", "total_score": 80},
    ]
    unranked = PerformanceScoringPolicy.rank_position_results(two_results, calculated_at)

    assert [item["user_id"] for item in unranked] == [2, 1]
    assert all(item["rank_no"] is None and item["rank_total"] is None for item in unranked)
    assert {item["calculated_at"] for item in unranked} == {calculated_at}


def test_rank_position_results_uses_ties_and_stable_user_order():
    calculated_at = "2026-08-10 08:30:00"
    results = [
        {"user_id": 3, "position_id_snapshot": 7, "eligibility_status": "eligible", "total_score": 80},
        {"user_id": 2, "position_id_snapshot": 7, "eligibility_status": "eligible", "total_score": 90},
        {"user_id": 1, "position_id_snapshot": 7, "eligibility_status": "eligible", "total_score": 90},
        {"user_id": 4, "position_id_snapshot": 7, "eligibility_status": "eligible", "total_score": 70},
    ]
    ranked = PerformanceScoringPolicy.rank_position_results(results, calculated_at)

    assert [(item["user_id"], item["rank_no"]) for item in ranked] == [
        (1, 1),
        (2, 1),
        (3, 3),
        (4, 4),
    ]
    assert {item["rank_total"] for item in ranked} == {4}
    assert len({item["ranking_digest"] for item in ranked}) == 1
    assert len({item["calculation_group_id"] for item in ranked}) == 1
    assert {item["calculated_at"] for item in ranked} == {calculated_at}
    assert all("rank_no" not in item for item in results)


def test_production_month_validation_row_versions_and_transitions():
    assert validate_production_month("2026-07") == "2026-07"
    assert production_month_for_timestamp("2026-08-01 06:59:59") == "2026-07"
    assert production_month_for_timestamp("2026-08-01 07:00:00") == "2026-08"
    assert require_row_version("2") == 2
    assert assert_row_version(2, "2") == 2
    assert validate_batch_transition(
        BATCH_STATUS_DRAFT, BATCH_STATUS_SUPERVISOR_REVIEW
    ) == BATCH_STATUS_SUPERVISOR_REVIEW
    with pytest.raises(ValueError, match="YYYY-MM"):
        validate_production_month("2026-13")
    with pytest.raises(ValueError, match="row_version"):
        require_row_version(-1)
    with pytest.raises(PerformanceConflictError, match="刷新后重试"):
        assert_row_version(1, 2)
    with pytest.raises(PerformanceConflictError, match="状态转换"):
        validate_batch_transition(BATCH_STATUS_DRAFT, BATCH_STATUS_APPROVED)


def test_same_inputs_produce_same_canonical_json_and_digest():
    first_rule = _rule()
    second_rule = {key: first_rule[key] for key in reversed(first_rule)}
    first_target = _target()
    second_target = {key: first_target[key] for key in reversed(first_target)}
    first_metrics = _metrics()
    second_metrics = {key: first_metrics[key] for key in reversed(first_metrics)}
    first_facts = [
        {"canonical_event_id": 2, "event_type": "rework", "quantity": 1},
        {"canonical_event_id": 1, "event_type": "scrap", "quantity": 2},
    ]
    second_facts = list(reversed(first_facts))

    first = PerformanceScoringPolicy.score_worker(
        first_rule, first_target, first_metrics, {}, first_facts
    )
    second = PerformanceScoringPolicy.score_worker(
        second_rule, second_target, second_metrics, {}, second_facts
    )

    assert first["input_json"] == second["input_json"]
    assert first["input_digest"] == second["input_digest"]
    assert first["score_details"] == second["score_details"]


def test_database_rule_json_columns_normalize_to_same_scoring_input():
    expanded_rule = _rule()
    stored_rule = {
        "id": expanded_rule["id"],
        "version_code": expanded_rule["version_code"],
        "weights_json": json.dumps(expanded_rule["weights"]),
        "warning_levels_json": json.dumps(expanded_rule["warning_levels"]),
        "scoring_parameters_json": json.dumps(
            {
                "work_days_target": expanded_rule["work_days_target"],
                "handoff": expanded_rule["handoff"],
                "improvement": expanded_rule["improvement"],
            }
        ),
    }

    expanded = PerformanceScoringPolicy.score_worker(
        expanded_rule, _target(), _metrics(), {}, []
    )
    stored = PerformanceScoringPolicy.score_worker(
        stored_rule, _target(), _metrics(), {}, []
    )

    assert expanded["input_json"] == stored["input_json"]
    assert expanded["input_digest"] == stored["input_digest"]
