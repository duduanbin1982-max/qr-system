import pytest

from modules.domain.quality_evaluation import QualityEvaluationPolicy


DIMENSIONS = [
    {"key": "required_quality", "label": "必评质量", "weight": 2, "required": True},
    {"key": "optional_appearance", "label": "选评外观", "weight": 1, "required": False},
]


def _rules():
    return {
        "low_score_threshold": 60,
        "critical_score_threshold": 40,
        "critical_issue_tags": ["严重尺寸超差"],
    }


def test_quality_evaluation_policy_calculates_weighted_decision_without_database():
    decision = QualityEvaluationPolicy.decide(
        {
            "dimension_scores": {"required_quality": 5, "optional_appearance": 2},
            "issue_tags": [],
            "comment": "",
        },
        {"low_score_threshold": 60, "critical_score_threshold": 40},
        _rules(),
        DIMENSIONS,
    )

    assert decision.total_score == 80
    assert decision.grade == "良好"
    assert decision.severity == "normal"
    assert decision.status == "confirmed"


def test_quality_evaluation_policy_requires_reason_for_low_score():
    with pytest.raises(ValueError, match="低分评价必须填写"):
        QualityEvaluationPolicy.decide(
            {"dimension_scores": {"required_quality": 2}},
            {"low_score_threshold": 60, "critical_score_threshold": 40},
            _rules(),
            DIMENSIONS,
        )


def test_quality_evaluation_policy_marks_critical_tag_for_verification():
    decision = QualityEvaluationPolicy.decide(
        {
            "dimension_scores": {"required_quality": 5},
            "issue_tags": ["严重尺寸超差"],
        },
        {"low_score_threshold": 60, "critical_score_threshold": 40},
        _rules(),
        DIMENSIONS,
    )

    assert decision.severity == "critical"
    assert decision.status == "pending_verification"


def test_quality_evaluation_policy_accepts_missing_optional_dimension():
    scores, _, total_score = QualityEvaluationPolicy.evaluate_dimensions(
        {"dimension_scores": {"required_quality": 4}},
        DIMENSIONS,
    )

    assert scores == {"required_quality": 4}
    assert total_score == 80


def test_quality_evaluation_policy_converts_legacy_review():
    decision = QualityEvaluationPolicy.from_legacy(
        2,
        ["表面缺陷"],
        "pending",
        _rules(),
    )

    assert decision.total_score == 40
    assert decision.grade == "待改进"
    assert decision.severity == "warning"
    assert decision.status == "pending_verification"
