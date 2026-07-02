"""Centralized performance scoring rules and calculations."""


class PerformanceScoringPolicy:
    SCORE_WEIGHTS = {
        "output": 35.0,
        "quality": 30.0,
        "delivery": 15.0,
        "discipline": 10.0,
        "improvement": 10.0,
    }
    WORK_DAYS_TARGET = 22.0
    WARNING_LEVELS = (
        {"level": "green", "min_score": 80.0, "reason": "达标"},
        {"level": "yellow", "min_score": 70.0, "reason": "低于优秀线，建议主管关注"},
        {"level": "orange", "min_score": 60.0, "reason": "低于岗位目标，建议制定改进计划"},
        {"level": "red", "min_score": 0.0, "reason": "显著低于岗位目标，需培训/帮扶/复评闭环"},
    )
    HANDOFF_LOW_PENALTY_PER_REVIEW = 2.0
    HANDOFF_LOW_PENALTY_CAP = 8.0
    HANDOFF_AVG_TARGET = 4.0
    HANDOFF_AVG_PENALTY_FACTOR = 2.0
    HANDOFF_AVG_PENALTY_CAP = 4.0
    OPEN_PLAN_PENALTY_PER_PLAN = 2.0
    OPEN_PLAN_PENALTY_CAP = 6.0
    FAILED_PLAN_PENALTY_PER_PLAN = 3.0
    FAILED_PLAN_PENALTY_CAP = 6.0
    COMPLETED_PLAN_BONUS_PER_PLAN = 1.0
    COMPLETED_PLAN_BONUS_CAP = 2.0
    IMPROVEMENT_ADJUSTMENT_MIN = -5.0
    IMPROVEMENT_ADJUSTMENT_MAX = 5.0
    MANUAL_SCORE_MIN = 0.0
    MANUAL_SCORE_MAX = 10.0
    MANUAL_SCORE_DEFAULT = 10.0

    @classmethod
    def rules(cls):
        return {
            "weights": {
                key: int(value) if float(value).is_integer() else value
                for key, value in cls.SCORE_WEIGHTS.items()
            },
            "work_days_target": int(cls.WORK_DAYS_TARGET),
            "warning_levels": list(cls.WARNING_LEVELS),
            "handoff": {
                "low_penalty_per_review": cls.HANDOFF_LOW_PENALTY_PER_REVIEW,
                "low_penalty_cap": cls.HANDOFF_LOW_PENALTY_CAP,
                "avg_target": cls.HANDOFF_AVG_TARGET,
                "avg_penalty_factor": cls.HANDOFF_AVG_PENALTY_FACTOR,
                "avg_penalty_cap": cls.HANDOFF_AVG_PENALTY_CAP,
            },
            "improvement": {
                "open_plan_penalty_per_plan": cls.OPEN_PLAN_PENALTY_PER_PLAN,
                "open_plan_penalty_cap": cls.OPEN_PLAN_PENALTY_CAP,
                "failed_plan_penalty_per_plan": cls.FAILED_PLAN_PENALTY_PER_PLAN,
                "failed_plan_penalty_cap": cls.FAILED_PLAN_PENALTY_CAP,
                "completed_plan_bonus_per_plan": cls.COMPLETED_PLAN_BONUS_PER_PLAN,
                "completed_plan_bonus_cap": cls.COMPLETED_PLAN_BONUS_CAP,
                "manual_adjustment_range": f"{int(cls.IMPROVEMENT_ADJUSTMENT_MIN)}~{int(cls.IMPROVEMENT_ADJUSTMENT_MAX)}",
            },
            "manual_score_range": f"{int(cls.MANUAL_SCORE_MIN)}~{int(cls.MANUAL_SCORE_MAX)}",
            "manual_adjustment_range": f"-{int(cls.MANUAL_SCORE_MAX)}~0",
        }

    @staticmethod
    def as_float(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def clamp(value, minimum=0.0, maximum=100.0):
        return max(minimum, min(maximum, value))

    @classmethod
    def score_worker(cls, metrics, max_output, review=None, handoff=None):
        review = review or {}
        handoff = handoff or {}
        output_score = cls._score_output(metrics, max_output)
        quality_score, quality_details = cls._score_quality(metrics, handoff)
        delivery_score = cls._score_delivery(metrics)
        discipline_score, discipline_deduction = cls._score_discipline(review)
        improvement_score, improvement_details = cls._score_improvement(metrics, review)
        manual_score, manual_delta = cls._score_manual(review)
        total_score = cls.clamp(
            output_score + quality_score + delivery_score + discipline_score + improvement_score + manual_delta,
            0.0,
            100.0,
        )
        level, default_reason = cls._warning(total_score)
        reasons = cls._warning_reasons(metrics, review, quality_details, improvement_details, discipline_deduction, manual_score)

        return {
            "output_score": round(output_score, 1),
            "quality_score": round(quality_score, 1),
            "delivery_score": round(delivery_score, 1),
            "discipline_score": round(discipline_score, 1),
            "improvement_score": round(improvement_score, 1),
            "total_score": round(total_score, 1),
            "warning_level": level,
            "warning_reason": "；".join(reasons) or default_reason,
            "discipline_deduction": round(discipline_deduction, 1),
            "discipline_reason": review.get("discipline_reason", ""),
            "improvement_deduction": round(improvement_details["deduction"], 1),
            "improvement_reason": review.get("improvement_reason", ""),
            "manual_score": round(manual_score, 1),
            "manual_comment": review.get("manual_comment", ""),
            "score_details": cls._score_details(metrics, max_output, handoff, quality_details, improvement_details, manual_delta),
            "reviewed_by": review.get("reviewed_by"),
            "reviewed_at": review.get("updated_at") or review.get("created_at") or "",
        }

    @classmethod
    def _score_output(cls, metrics, max_output):
        if max_output <= 0:
            return cls.SCORE_WEIGHTS["output"]
        return min(cls.SCORE_WEIGHTS["output"], metrics["output_qty"] / max_output * cls.SCORE_WEIGHTS["output"])

    @classmethod
    def _score_quality(cls, metrics, handoff):
        bad_qty = metrics["scrap_qty"] + metrics["rework_qty"] + metrics["inspection_failed_qty"]
        total_checked = metrics["output_qty"] + bad_qty
        quality_rate = 1.0 if total_checked <= 0 else max(0.0, 1.0 - bad_qty / total_checked)
        handoff_low_count = int(handoff.get("low_count") or 0)
        handoff_penalty = cls._handoff_penalty(handoff_low_count, handoff.get("avg_rating"))
        quality_score = max(0.0, quality_rate * cls.SCORE_WEIGHTS["quality"] - handoff_penalty)
        return quality_score, {
            "bad_qty": bad_qty,
            "quality_rate": quality_rate,
            "handoff_low_count": handoff_low_count,
            "handoff_penalty": handoff_penalty,
        }

    @classmethod
    def _handoff_penalty(cls, low_count, avg_rating):
        penalty = min(cls.HANDOFF_LOW_PENALTY_CAP, low_count * cls.HANDOFF_LOW_PENALTY_PER_REVIEW)
        if avg_rating is None:
            return penalty
        avg_value = cls.as_float(avg_rating, cls.HANDOFF_AVG_TARGET)
        if avg_value < cls.HANDOFF_AVG_TARGET:
            penalty += min(
                cls.HANDOFF_AVG_PENALTY_CAP,
                (cls.HANDOFF_AVG_TARGET - avg_value) * cls.HANDOFF_AVG_PENALTY_FACTOR,
            )
        return penalty

    @classmethod
    def _score_delivery(cls, metrics):
        if not metrics["work_days"]:
            return 0.0
        return min(cls.SCORE_WEIGHTS["delivery"], metrics["work_days"] / cls.WORK_DAYS_TARGET * cls.SCORE_WEIGHTS["delivery"])

    @classmethod
    def _score_discipline(cls, review):
        deduction = cls.clamp(cls.as_float(review.get("discipline_deduction")), 0.0, cls.SCORE_WEIGHTS["discipline"])
        return cls.SCORE_WEIGHTS["discipline"] - deduction, deduction

    @classmethod
    def _score_improvement(cls, metrics, review):
        open_penalty = min(cls.OPEN_PLAN_PENALTY_CAP, metrics.get("open_improvement_plans", 0) * cls.OPEN_PLAN_PENALTY_PER_PLAN)
        failed_penalty = min(cls.FAILED_PLAN_PENALTY_CAP, metrics.get("failed_improvement_plans", 0) * cls.FAILED_PLAN_PENALTY_PER_PLAN)
        completed_bonus = min(cls.COMPLETED_PLAN_BONUS_CAP, metrics.get("completed_improvement_plans", 0) * cls.COMPLETED_PLAN_BONUS_PER_PLAN)
        manual_adjustment = cls.clamp(
            cls.as_float(review.get("improvement_adjustment")),
            cls.IMPROVEMENT_ADJUSTMENT_MIN,
            cls.IMPROVEMENT_ADJUSTMENT_MAX,
        )
        deduction = max(0.0, open_penalty + failed_penalty - completed_bonus - manual_adjustment)
        score = cls.clamp(cls.SCORE_WEIGHTS["improvement"] - deduction, 0.0, cls.SCORE_WEIGHTS["improvement"])
        return score, {
            "open_plan_penalty": open_penalty,
            "failed_plan_penalty": failed_penalty,
            "completed_plan_bonus": completed_bonus,
            "manual_adjustment": manual_adjustment,
            "deduction": deduction,
        }

    @classmethod
    def _score_manual(cls, review):
        manual_score = cls.clamp(
            cls.as_float(review.get("manual_score"), cls.MANUAL_SCORE_DEFAULT),
            cls.MANUAL_SCORE_MIN,
            cls.MANUAL_SCORE_MAX,
        )
        return manual_score, manual_score - cls.MANUAL_SCORE_DEFAULT

    @classmethod
    def _warning(cls, total_score):
        for level in cls.WARNING_LEVELS:
            if total_score >= level["min_score"]:
                return level["level"], level["reason"]
        return cls.WARNING_LEVELS[-1]["level"], cls.WARNING_LEVELS[-1]["reason"]

    @classmethod
    def _warning_reasons(cls, metrics, review, quality_details, improvement_details, discipline_deduction, manual_score):
        reasons = []
        if quality_details["bad_qty"]:
            reasons.append(f"质量扣项{quality_details['bad_qty']}件")
        if quality_details["handoff_low_count"]:
            reasons.append(f"交接低分{quality_details['handoff_low_count']}次")
        if metrics["work_days"] < 15:
            reasons.append(f"有效报工天数{metrics['work_days']}天")
        if discipline_deduction:
            reasons.append(review.get("discipline_reason") or f"纪律扣{discipline_deduction:g}分")
        if improvement_details["open_plan_penalty"]:
            reasons.append(f"未关闭改进计划{metrics.get('open_improvement_plans', 0)}项")
        if improvement_details["failed_plan_penalty"]:
            reasons.append(f"复评未通过{metrics.get('failed_improvement_plans', 0)}项")
        if manual_score < cls.MANUAL_SCORE_DEFAULT:
            reasons.append(review.get("manual_comment") or f"主管评议扣{cls.MANUAL_SCORE_DEFAULT - manual_score:g}分")
        return reasons

    @classmethod
    def _score_details(cls, metrics, max_output, handoff, quality_details, improvement_details, manual_delta):
        return {
            "weights": cls.rules()["weights"] | {"manual_adjustment_range": cls.rules()["manual_adjustment_range"]},
            "bad_qty": quality_details["bad_qty"],
            "quality_rate": round(quality_details["quality_rate"], 4),
            "handoff_review_count": int(handoff.get("review_count") or 0),
            "handoff_avg_rating": handoff.get("avg_rating"),
            "handoff_low_count": quality_details["handoff_low_count"],
            "handoff_good_count": int(handoff.get("good_count") or 0),
            "handoff_penalty": round(quality_details["handoff_penalty"], 1),
            "max_output": max_output,
            "open_improvement_plans": metrics.get("open_improvement_plans", 0),
            "failed_improvement_plans": metrics.get("failed_improvement_plans", 0),
            "completed_improvement_plans": metrics.get("completed_improvement_plans", 0),
            "manual_improvement_adjustment": improvement_details["manual_adjustment"],
            "manual_delta": round(manual_delta, 1),
        }
