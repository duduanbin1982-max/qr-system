"""Pure policies for full-process quality evaluation decisions."""

from dataclasses import dataclass


LEGACY_DIMENSIONS = (
    ("processing_quality", "加工质量"),
    ("dimensional_accuracy", "尺寸或精度"),
    ("appearance_quality", "外观质量"),
    ("process_continuity", "工序可接续性"),
    ("cleanliness_protection", "清洁及防护"),
)


@dataclass(frozen=True)
class QualityEvaluationDecision:
    dimension_scores: dict
    legacy_dimensions: dict
    total_score: float
    grade: str
    issue_tags: list
    comment: str
    severity: str
    status: str


class QualityEvaluationPolicy:
    """Validate evaluation input and derive its authoritative outcome."""

    @staticmethod
    def score_threshold(value, default=60):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def positive_int(value, default=1):
        try:
            result = int(value)
        except (TypeError, ValueError):
            return default
        return result if result > 0 else default

    @staticmethod
    def rating(value, label):
        try:
            rating = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label}必须是1-5分") from exc
        if rating < 1 or rating > 5:
            raise ValueError(f"{label}必须是1-5分")
        return rating

    @staticmethod
    def grade(total_score):
        if total_score >= 90:
            return "优秀"
        if total_score >= 80:
            return "良好"
        if total_score >= 60:
            return "合格"
        if total_score >= 40:
            return "待改进"
        return "不合格"

    @classmethod
    def evaluate_dimensions(cls, entry, configured_dimensions, legacy_dimensions=LEGACY_DIMENSIONS):
        supplied = entry.get("dimension_scores")
        if not isinstance(supplied, dict):
            supplied = {
                key: entry.get(key)
                for key, _ in legacy_dimensions
                if entry.get(key) is not None
            }

        scores = {}
        weighted_total = 0
        weight_total = 0
        for dimension in configured_dimensions:
            key = dimension["key"]
            if key not in supplied and dimension.get("required", True):
                raise ValueError(f"{dimension['label']}必须评分")
            if key not in supplied:
                continue
            rating = cls.rating(supplied.get(key), dimension["label"])
            weight = cls.positive_int(dimension.get("weight"), 1)
            scores[key] = rating
            weighted_total += rating * weight
            weight_total += weight

        if not scores or weight_total <= 0:
            raise ValueError("至少填写一个评分维度")

        total_score = round(weighted_total / (5 * weight_total) * 100, 1)
        fallback_rating = max(1, min(5, round(total_score / 20)))
        legacy = {
            key: scores.get(key, fallback_rating)
            for key, _ in legacy_dimensions
        }
        return scores, legacy, total_score

    @staticmethod
    def normalize_issue_tags(value):
        if isinstance(value, str):
            value = [value.strip()] if value.strip() else []
        if not isinstance(value, list):
            raise ValueError("问题标签格式不正确")
        return [str(tag).strip() for tag in value if str(tag).strip()]

    @classmethod
    def decide(cls, entry, template_snapshot, rules, configured_dimensions):
        dimension_scores, legacy_dimensions, total_score = cls.evaluate_dimensions(
            entry,
            configured_dimensions,
        )
        issue_tags = cls.normalize_issue_tags(entry.get("issue_tags", []))
        comment = str(entry.get("comment") or "").strip()
        threshold = cls.score_threshold(
            template_snapshot.get("low_score_threshold"),
            rules["low_score_threshold"],
        )
        critical_threshold = cls.score_threshold(
            template_snapshot.get("critical_score_threshold"),
            rules["critical_score_threshold"],
        )
        critical_tags = set(
            template_snapshot.get("critical_issue_tags")
            or rules.get("critical_issue_tags")
            or []
        )
        if total_score < threshold and not (issue_tags or comment):
            raise ValueError("低分评价必须填写问题标签或备注")

        if total_score < critical_threshold or critical_tags.intersection(issue_tags):
            severity = "critical"
        elif total_score < threshold:
            severity = "warning"
        else:
            severity = "normal"
        status = (
            "pending_verification"
            if severity in {"warning", "critical"}
            else "confirmed"
        )
        return QualityEvaluationDecision(
            dimension_scores=dimension_scores,
            legacy_dimensions=legacy_dimensions,
            total_score=total_score,
            grade=cls.grade(total_score),
            issue_tags=issue_tags,
            comment=comment,
            severity=severity,
            status=status,
        )

    @classmethod
    def from_legacy(cls, rating, issue_tags, legacy_status, rules):
        normalized_rating = cls.rating(rating, "评分")
        total_score = normalized_rating * 20.0
        severity = (
            "warning"
            if total_score < rules["low_score_threshold"]
            else "normal"
        )
        return QualityEvaluationDecision(
            dimension_scores={key: normalized_rating for key, _ in LEGACY_DIMENSIONS},
            legacy_dimensions={key: normalized_rating for key, _ in LEGACY_DIMENSIONS},
            total_score=total_score,
            grade=cls.grade(total_score),
            issue_tags=cls.normalize_issue_tags(issue_tags),
            comment="",
            severity=severity,
            status="pending_verification" if legacy_status == "pending" else "confirmed",
        )
