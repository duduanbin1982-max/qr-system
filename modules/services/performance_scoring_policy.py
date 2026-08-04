"""Centralized performance scoring rules and calculations."""

from copy import deepcopy
import hashlib
import json

from modules.domain.performance_policy import (
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_INSUFFICIENT_DATA,
    REASON_INSUFFICIENT_WORK_DAYS,
    REASON_MISSING_POSITION,
    REASON_MISSING_POSITION_TARGET,
    REASON_POSITION_TARGET_MISMATCH,
    REASON_UNRESOLVED_DATA_EXCEPTION,
    REASON_ZERO_OUTPUT,
)


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
    BAD_QUALITY_EVENT_TYPES = {
        "scrap",
        "rework",
        "inspection",
        "inspection_failed",
        "inspection_failure",
        "quality_inspection_failure",
    }
    HANDOFF_EVENT_TYPES = {"handoff", "handoff_review", "process_handoff"}

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
    def score_worker(cls, rule, position_target, metrics, review=None, quality_facts=None):
        """Score one employee from immutable V2 inputs without database access."""
        normalized_rule = cls._normalize_rule(rule)
        normalized_target = cls._normalize_target(position_target)
        normalized_metrics = cls._normalize_metrics(metrics)
        normalized_review = cls._normalize_review(review)
        normalized_facts = cls._normalize_quality_facts(quality_facts)
        input_payload = {
            "rule": normalized_rule,
            "position_target": normalized_target,
            "metrics": normalized_metrics,
            "review": normalized_review,
            "quality_facts": normalized_facts,
        }
        input_json = cls.canonical_json(input_payload)
        input_digest = hashlib.sha256(input_json.encode("utf-8")).hexdigest()
        reason_code, reason = cls._eligibility_reason(
            normalized_target, normalized_metrics
        )
        if reason_code:
            return cls._insufficient_result(
                normalized_rule,
                normalized_target,
                normalized_metrics,
                reason_code,
                reason,
                input_json,
                input_digest,
            )

        review_values = cls._review_values(normalized_review, normalized_rule)
        output_weight = normalized_rule["weights"]["output"]
        output_score = min(
            output_weight,
            normalized_metrics["output_qty"]
            / normalized_target["target_output_qty"]
            * output_weight,
        )
        quality_score, quality_details = cls._score_v2_quality(
            normalized_metrics, normalized_facts, normalized_rule
        )
        delivery_score = cls._score_v2_delivery(normalized_metrics, normalized_rule)
        discipline_score = (
            normalized_rule["weights"]["discipline"]
            - review_values["discipline_deduction"]
        )
        improvement_score, improvement_details = cls._score_v2_improvement(
            normalized_metrics, review_values, normalized_rule
        )
        manual_adjustment = (
            review_values["manual_score"] - cls.MANUAL_SCORE_DEFAULT
        )
        output_score = round(output_score, 1)
        quality_score = round(quality_score, 1)
        delivery_score = round(delivery_score, 1)
        discipline_score = round(discipline_score, 1)
        improvement_score = round(improvement_score, 1)
        manual_adjustment = round(manual_adjustment, 1)
        total_score = cls.clamp(
            output_score
            + quality_score
            + delivery_score
            + discipline_score
            + improvement_score
            + manual_adjustment,
            0.0,
            100.0,
        )
        warning_level, default_reason = cls._warning_v2(
            total_score, normalized_rule
        )
        warning_reasons = cls._warning_reasons_v2(
            normalized_metrics,
            normalized_review,
            quality_details,
            improvement_details,
            review_values,
        )
        score_details = cls._score_details_v2(
            normalized_rule,
            normalized_target,
            normalized_metrics,
            quality_details,
            improvement_details,
            manual_adjustment,
        )

        return {
            "eligibility_status": ELIGIBILITY_ELIGIBLE,
            "eligibility_reason_code": "",
            "eligibility_reason": "",
            "output_score": output_score,
            "quality_score": quality_score,
            "delivery_score": delivery_score,
            "discipline_score": discipline_score,
            "improvement_score": improvement_score,
            "total_score": round(total_score, 1),
            "rank_no": None,
            "rank_total": None,
            "warning_level": warning_level,
            "warning_reason": "；".join(warning_reasons) or default_reason,
            "discipline_deduction": round(
                review_values["discipline_deduction"], 1
            ),
            "discipline_reason": normalized_review["discipline_reason"],
            "improvement_deduction": round(improvement_details["deduction"], 1),
            "improvement_reason": normalized_review["improvement_reason"],
            "manual_score": round(review_values["manual_score"], 1),
            "manual_adjustment": manual_adjustment,
            "manual_comment": normalized_review["manual_comment"],
            "rule_version_id": normalized_rule["id"],
            "position_target_version_id": normalized_target["id"],
            "score_details": score_details,
            "input_json": input_json,
            "input_digest": input_digest,
        }

    @staticmethod
    def canonical_json(value):
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @classmethod
    def _number(cls, value, field_name, default=None):
        if value is None and default is not None:
            return float(default)
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name}必须为数字") from exc
        if number != number or number in (float("inf"), float("-inf")):
            raise ValueError(f"{field_name}必须为有限数字")
        return number

    @staticmethod
    def _json_config(value, expected_type, field_name):
        if value is None:
            return None
        if isinstance(value, expected_type):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{field_name}不是有效 JSON") from exc
            if isinstance(parsed, expected_type):
                return parsed
        raise ValueError(f"{field_name}格式无效")

    @classmethod
    def _normalize_rule(cls, rule):
        if not isinstance(rule, dict):
            raise ValueError("绩效规则版本不能为空")
        source_weights = cls._json_config(
            rule.get("weights")
            if rule.get("weights") is not None
            else rule.get("weights_json"),
            dict,
            "绩效权重",
        ) or {}
        weights = {
            name: cls._number(
                source_weights.get(name, default), f"{name}评分权重"
            )
            for name, default in cls.SCORE_WEIGHTS.items()
        }
        if any(value < 0 for value in weights.values()) or round(sum(weights.values()), 6) != 100:
            raise ValueError("绩效五维权重必须为非负数且合计 100")
        scoring_parameters = cls._json_config(
            rule.get("scoring_parameters")
            if rule.get("scoring_parameters") is not None
            else rule.get("scoring_parameters_json"),
            dict,
            "绩效评分参数",
        ) or {}
        direct_handoff = cls._json_config(
            rule.get("handoff"), dict, "工序交接评分参数"
        ) or {}
        direct_improvement = cls._json_config(
            rule.get("improvement"), dict, "改进计划评分参数"
        ) or {}
        parameter_handoff = cls._json_config(
            scoring_parameters.get("handoff"), dict, "工序交接评分参数"
        ) or {}
        parameter_improvement = cls._json_config(
            scoring_parameters.get("improvement"), dict, "改进计划评分参数"
        ) or {}
        handoff = {
            **cls.rules()["handoff"],
            **parameter_handoff,
            **direct_handoff,
        }
        improvement = {
            **cls.rules()["improvement"],
            **parameter_improvement,
            **direct_improvement,
        }
        work_days_target = cls._number(
            rule.get(
                "work_days_target",
                scoring_parameters.get("work_days_target", cls.WORK_DAYS_TARGET),
            ),
            "交付目标工作日",
        )
        if work_days_target <= 0:
            raise ValueError("交付目标工作日必须大于 0")
        warning_levels = cls._json_config(
            rule.get("warning_levels")
            if rule.get("warning_levels") is not None
            else rule.get("warning_levels_json"),
            (list, tuple),
            "绩效等级阈值",
        ) or list(cls.WARNING_LEVELS)
        if not isinstance(warning_levels, (list, tuple)) or not warning_levels:
            raise ValueError("绩效等级阈值不能为空")
        normalized_levels = []
        for item in warning_levels:
            if not isinstance(item, dict):
                raise ValueError("绩效等级阈值格式无效")
            normalized_levels.append(
                {
                    "level": str(item.get("level") or "").strip(),
                    "min_score": cls._number(item.get("min_score"), "绩效等级阈值"),
                    "reason": str(item.get("reason") or "").strip(),
                }
            )
        normalized_levels.sort(key=lambda item: item["min_score"], reverse=True)
        return {
            "id": rule.get("id"),
            "version_code": str(rule.get("version_code") or "").strip(),
            "weights": weights,
            "work_days_target": work_days_target,
            "warning_levels": normalized_levels,
            "handoff": {
                "low_penalty_per_review": cls._number(
                    handoff.get("low_penalty_per_review"),
                    "低分交接单次扣分",
                    cls.HANDOFF_LOW_PENALTY_PER_REVIEW,
                ),
                "low_penalty_cap": cls._number(
                    handoff.get("low_penalty_cap"),
                    "低分交接扣分上限",
                    cls.HANDOFF_LOW_PENALTY_CAP,
                ),
                "avg_target": cls._number(
                    handoff.get("avg_target"),
                    "交接评价目标",
                    cls.HANDOFF_AVG_TARGET,
                ),
                "avg_penalty_factor": cls._number(
                    handoff.get("avg_penalty_factor"),
                    "交接均分扣分系数",
                    cls.HANDOFF_AVG_PENALTY_FACTOR,
                ),
                "avg_penalty_cap": cls._number(
                    handoff.get("avg_penalty_cap"),
                    "交接均分扣分上限",
                    cls.HANDOFF_AVG_PENALTY_CAP,
                ),
            },
            "improvement": {
                "open_plan_penalty_per_plan": cls._number(
                    improvement.get("open_plan_penalty_per_plan"),
                    "未关闭计划单项扣分",
                    cls.OPEN_PLAN_PENALTY_PER_PLAN,
                ),
                "open_plan_penalty_cap": cls._number(
                    improvement.get("open_plan_penalty_cap"),
                    "未关闭计划扣分上限",
                    cls.OPEN_PLAN_PENALTY_CAP,
                ),
                "failed_plan_penalty_per_plan": cls._number(
                    improvement.get("failed_plan_penalty_per_plan"),
                    "复评失败单项扣分",
                    cls.FAILED_PLAN_PENALTY_PER_PLAN,
                ),
                "failed_plan_penalty_cap": cls._number(
                    improvement.get("failed_plan_penalty_cap"),
                    "复评失败扣分上限",
                    cls.FAILED_PLAN_PENALTY_CAP,
                ),
                "completed_plan_bonus_per_plan": cls._number(
                    improvement.get("completed_plan_bonus_per_plan"),
                    "已完成计划单项加分",
                    cls.COMPLETED_PLAN_BONUS_PER_PLAN,
                ),
                "completed_plan_bonus_cap": cls._number(
                    improvement.get("completed_plan_bonus_cap"),
                    "已完成计划加分上限",
                    cls.COMPLETED_PLAN_BONUS_CAP,
                ),
            },
        }

    @classmethod
    def _normalize_target(cls, target):
        if target is None:
            return None
        if not isinstance(target, dict):
            raise ValueError("岗位目标版本格式无效")
        target_output = cls._number(
            target.get("target_output_qty"), "岗位目标产量"
        )
        minimum_days = cls._number(
            target.get("minimum_effective_work_days"), "最低有效报工日"
        )
        if target_output <= 0 or minimum_days <= 0:
            raise ValueError("岗位目标产量和最低有效报工日必须大于 0")
        return {
            "id": target.get("id"),
            "position_id": target.get("position_id"),
            "position_name_snapshot": str(
                target.get("position_name_snapshot") or ""
            ).strip(),
            "target_output_qty": target_output,
            "minimum_effective_work_days": minimum_days,
        }

    @classmethod
    def _normalize_metrics(cls, metrics):
        if not isinstance(metrics, dict):
            raise ValueError("绩效指标不能为空")
        position_id = metrics.get("position_id_snapshot")
        if position_id is None:
            position_id = metrics.get("position_id")
        unresolved_count = metrics.get("unresolved_exception_count", 0)
        if metrics.get("has_unresolved_exceptions"):
            unresolved_count = max(cls._number(unresolved_count, "未解决异常数量", 0), 1)
        normalized = {
            "user_id": metrics.get("user_id"),
            "position_id": position_id,
            "output_qty": cls._number(metrics.get("output_qty"), "有效产量", 0),
            "report_count": cls._number(metrics.get("report_count"), "报工数", 0),
            "work_days": cls._number(metrics.get("work_days"), "有效报工日", 0),
            "open_improvement_plans": cls._number(
                metrics.get("open_improvement_plans"), "未关闭改进计划数", 0
            ),
            "failed_improvement_plans": cls._number(
                metrics.get("failed_improvement_plans"), "复评失败计划数", 0
            ),
            "completed_improvement_plans": cls._number(
                metrics.get("completed_improvement_plans"), "已完成改进计划数", 0
            ),
            "unresolved_exception_count": cls._number(
                unresolved_count, "未解决异常数量", 0
            ),
        }
        nonnegative_fields = (
            "report_count",
            "open_improvement_plans",
            "failed_improvement_plans",
            "completed_improvement_plans",
            "unresolved_exception_count",
        )
        if any(normalized[field] < 0 for field in nonnegative_fields):
            raise ValueError("绩效指标计数不能为负数")
        return normalized

    @classmethod
    def _normalize_review(cls, review):
        if review is None:
            review = {}
        if not isinstance(review, dict):
            raise ValueError("主管复核输入格式无效")
        return {
            "discipline_deduction": cls._number(
                review.get("discipline_deduction"), "纪律扣分", 0
            ),
            "discipline_reason": str(review.get("discipline_reason") or "").strip(),
            "improvement_adjustment": cls._number(
                review.get("improvement_adjustment"), "改进调整", 0
            ),
            "improvement_reason": str(review.get("improvement_reason") or "").strip(),
            "manual_score": cls._number(
                review.get("manual_score"), "主管评议", cls.MANUAL_SCORE_DEFAULT
            ),
            "manual_comment": str(review.get("manual_comment") or "").strip(),
        }

    @classmethod
    def _normalize_quality_facts(cls, quality_facts):
        if quality_facts is None:
            quality_facts = []
        if not isinstance(quality_facts, (list, tuple)):
            raise ValueError("质量事实必须为列表")
        facts_by_identity = {}
        for fact in quality_facts:
            if not isinstance(fact, dict):
                raise ValueError("质量事实格式无效")
            identity = cls._quality_fact_identity(fact)
            event_type = str(
                fact.get("event_type") or fact.get("fact_type") or ""
            ).strip().lower().replace("-", "_")
            if not event_type:
                raise ValueError("质量事实缺少事件类型")
            if event_type not in cls.BAD_QUALITY_EVENT_TYPES | cls.HANDOFF_EVENT_TYPES:
                raise ValueError("质量事实事件类型不受支持")
            quantity = cls._number(fact.get("quantity"), "质量事件数量", 0)
            if quantity < 0:
                raise ValueError("质量事件数量不能为负数")
            rating = fact.get("rating")
            normalized_rating = (
                cls._number(rating, "交接评价分") if rating is not None else None
            )
            if normalized_rating is not None and not 1 <= normalized_rating <= 5:
                raise ValueError("交接评价分必须在 1 到 5 之间")
            normalized_fact = {
                "identity": identity,
                "event_type": event_type,
                "quantity": quantity,
                "rating": normalized_rating,
                "severity": str(fact.get("severity") or "").strip().lower(),
            }
            previous = facts_by_identity.get(identity)
            if previous is not None and previous != normalized_fact:
                raise ValueError("同一规范质量事件的事实内容冲突")
            facts_by_identity[identity] = normalized_fact
        normalized = list(facts_by_identity.values())
        normalized.sort(key=cls.canonical_json)
        return normalized

    @staticmethod
    def _quality_fact_identity(fact):
        canonical_id = fact.get("canonical_event_id")
        if canonical_id in (None, ""):
            canonical_id = fact.get("quality_event_id")
        if canonical_id not in (None, ""):
            return f"canonical:{canonical_id}"
        event_digest = fact.get("event_digest")
        if event_digest not in (None, ""):
            return f"digest:{event_digest}"
        source_type = fact.get("source_type")
        source_id = fact.get("source_id")
        if source_type not in (None, "") and source_id not in (None, ""):
            return f"source:{source_type}:{source_id}"
        raise ValueError("质量事实缺少稳定标识")

    @classmethod
    def _eligibility_reason(cls, target, metrics):
        if metrics["position_id"] in (None, ""):
            return REASON_MISSING_POSITION, "缺少可靠岗位快照"
        if target is None:
            return REASON_MISSING_POSITION_TARGET, "缺少已批准岗位目标"
        if target["position_id"] != metrics["position_id"]:
            return REASON_POSITION_TARGET_MISMATCH, "岗位目标与员工岗位快照不一致"
        if metrics["output_qty"] <= 0:
            return REASON_ZERO_OUTPUT, "有效产量必须大于零"
        if metrics["work_days"] < target["minimum_effective_work_days"]:
            return REASON_INSUFFICIENT_WORK_DAYS, "有效报工日未达到岗位最低要求"
        if metrics["unresolved_exception_count"] > 0:
            return REASON_UNRESOLVED_DATA_EXCEPTION, "存在未确认的绩效数据异常"
        return "", ""

    @staticmethod
    def _insufficient_result(
        rule, target, metrics, reason_code, reason, input_json, input_digest
    ):
        return {
            "eligibility_status": ELIGIBILITY_INSUFFICIENT_DATA,
            "eligibility_reason_code": reason_code,
            "eligibility_reason": reason,
            "output_score": None,
            "quality_score": None,
            "delivery_score": None,
            "discipline_score": None,
            "improvement_score": None,
            "total_score": None,
            "rank_no": None,
            "rank_total": None,
            "warning_level": None,
            "warning_reason": "",
            "discipline_deduction": None,
            "discipline_reason": "",
            "improvement_deduction": None,
            "improvement_reason": "",
            "manual_score": None,
            "manual_adjustment": None,
            "manual_comment": "",
            "rule_version_id": rule["id"],
            "position_target_version_id": target["id"] if target else None,
            "score_details": {
                "position_id": metrics["position_id"],
                "output_qty": metrics["output_qty"],
                "work_days": metrics["work_days"],
                "minimum_effective_work_days": (
                    target["minimum_effective_work_days"] if target else None
                ),
            },
            "input_json": input_json,
            "input_digest": input_digest,
        }

    @classmethod
    def _review_values(cls, review, rule):
        discipline_deduction = cls.clamp(
            review["discipline_deduction"],
            0.0,
            rule["weights"]["discipline"],
        )
        if discipline_deduction > 0 and not review["discipline_reason"]:
            raise ValueError("纪律扣分原因不能为空")
        improvement_adjustment = cls.clamp(
            review["improvement_adjustment"],
            cls.IMPROVEMENT_ADJUSTMENT_MIN,
            cls.IMPROVEMENT_ADJUSTMENT_MAX,
        )
        if improvement_adjustment != 0 and not review["improvement_reason"]:
            raise ValueError("改进调整原因不能为空")
        manual_score = cls.clamp(
            review["manual_score"], cls.MANUAL_SCORE_MIN, cls.MANUAL_SCORE_MAX
        )
        if manual_score < cls.MANUAL_SCORE_DEFAULT and not review["manual_comment"]:
            raise ValueError("主管评议说明不能为空")
        return {
            "discipline_deduction": discipline_deduction,
            "improvement_adjustment": improvement_adjustment,
            "manual_score": manual_score,
        }

    @classmethod
    def _score_v2_quality(cls, metrics, facts, rule):
        bad_qty = sum(
            fact["quantity"]
            for fact in facts
            if fact["event_type"] in cls.BAD_QUALITY_EVENT_TYPES
        )
        handoff_facts = [
            fact for fact in facts if fact["event_type"] in cls.HANDOFF_EVENT_TYPES
        ]
        ratings = [fact["rating"] for fact in handoff_facts if fact["rating"] is not None]
        low_count = sum(
            1
            for fact in handoff_facts
            if fact["severity"] in {"warning", "critical"}
            or (fact["rating"] is not None and fact["rating"] <= 2)
        )
        good_count = sum(
            1 for fact in handoff_facts if fact["rating"] is not None and fact["rating"] >= 4
        )
        avg_rating = sum(ratings) / len(ratings) if ratings else None
        handoff_penalty = cls._handoff_penalty_v2(
            low_count, avg_rating, rule["handoff"]
        )
        total_checked = metrics["output_qty"] + bad_qty
        quality_rate = (
            max(0.0, 1.0 - bad_qty / total_checked) if total_checked > 0 else 0.0
        )
        quality_score = cls.clamp(
            quality_rate * rule["weights"]["quality"] - handoff_penalty,
            0.0,
            rule["weights"]["quality"],
        )
        return quality_score, {
            "bad_qty": bad_qty,
            "quality_rate": quality_rate,
            "quality_event_count": len(facts),
            "quality_event_ids": [fact["identity"] for fact in facts],
            "handoff_review_count": len(handoff_facts),
            "handoff_avg_rating": avg_rating,
            "handoff_low_count": low_count,
            "handoff_good_count": good_count,
            "handoff_penalty": handoff_penalty,
        }

    @classmethod
    def _handoff_penalty_v2(cls, low_count, avg_rating, parameters):
        penalty = min(
            parameters["low_penalty_cap"],
            low_count * parameters["low_penalty_per_review"],
        )
        if avg_rating is not None and avg_rating < parameters["avg_target"]:
            penalty += min(
                parameters["avg_penalty_cap"],
                (parameters["avg_target"] - avg_rating)
                * parameters["avg_penalty_factor"],
            )
        return penalty

    @classmethod
    def _score_v2_delivery(cls, metrics, rule):
        return cls.clamp(
            metrics["work_days"]
            / rule["work_days_target"]
            * rule["weights"]["delivery"],
            0.0,
            rule["weights"]["delivery"],
        )

    @classmethod
    def _score_v2_improvement(cls, metrics, review_values, rule):
        parameters = rule["improvement"]
        open_penalty = min(
            parameters["open_plan_penalty_cap"],
            metrics["open_improvement_plans"]
            * parameters["open_plan_penalty_per_plan"],
        )
        failed_penalty = min(
            parameters["failed_plan_penalty_cap"],
            metrics["failed_improvement_plans"]
            * parameters["failed_plan_penalty_per_plan"],
        )
        completed_bonus = min(
            parameters["completed_plan_bonus_cap"],
            metrics["completed_improvement_plans"]
            * parameters["completed_plan_bonus_per_plan"],
        )
        deduction = max(
            0.0,
            open_penalty
            + failed_penalty
            - completed_bonus
            - review_values["improvement_adjustment"],
        )
        score = cls.clamp(
            rule["weights"]["improvement"] - deduction,
            0.0,
            rule["weights"]["improvement"],
        )
        return score, {
            "open_plan_penalty": open_penalty,
            "failed_plan_penalty": failed_penalty,
            "completed_plan_bonus": completed_bonus,
            "manual_adjustment": review_values["improvement_adjustment"],
            "deduction": deduction,
        }

    @staticmethod
    def _warning_v2(total_score, rule):
        for level in rule["warning_levels"]:
            if total_score >= level["min_score"]:
                return level["level"], level["reason"]
        last = rule["warning_levels"][-1]
        return last["level"], last["reason"]

    @classmethod
    def _warning_reasons_v2(
        cls, metrics, review, quality_details, improvement_details, review_values
    ):
        reasons = []
        if quality_details["bad_qty"]:
            reasons.append(f"质量扣项{quality_details['bad_qty']:g}件")
        if quality_details["handoff_low_count"]:
            reasons.append(f"工序质量低分{quality_details['handoff_low_count']}次")
        if metrics["work_days"] < 15:
            reasons.append(f"有效报工天数{metrics['work_days']:g}天")
        if review_values["discipline_deduction"]:
            reasons.append(review["discipline_reason"])
        if improvement_details["open_plan_penalty"]:
            reasons.append(f"未关闭改进计划{metrics['open_improvement_plans']:g}项")
        if improvement_details["failed_plan_penalty"]:
            reasons.append(f"复评未通过{metrics['failed_improvement_plans']:g}项")
        if review_values["manual_score"] < cls.MANUAL_SCORE_DEFAULT:
            reasons.append(review["manual_comment"])
        return reasons

    @classmethod
    def _score_details_v2(
        cls,
        rule,
        target,
        metrics,
        quality_details,
        improvement_details,
        manual_adjustment,
    ):
        return {
            "weights": rule["weights"],
            "position_id": metrics["position_id"],
            "output_qty": metrics["output_qty"],
            "report_count": metrics["report_count"],
            "work_days": metrics["work_days"],
            "target_output_qty": target["target_output_qty"],
            "minimum_effective_work_days": target["minimum_effective_work_days"],
            "work_days_target": rule["work_days_target"],
            "bad_qty": round(quality_details["bad_qty"], 4),
            "quality_rate": round(quality_details["quality_rate"], 6),
            "quality_event_count": quality_details["quality_event_count"],
            "quality_event_ids": quality_details["quality_event_ids"],
            "handoff_review_count": quality_details["handoff_review_count"],
            "handoff_avg_rating": quality_details["handoff_avg_rating"],
            "handoff_low_count": quality_details["handoff_low_count"],
            "handoff_good_count": quality_details["handoff_good_count"],
            "handoff_penalty": round(quality_details["handoff_penalty"], 4),
            "open_improvement_plans": metrics["open_improvement_plans"],
            "failed_improvement_plans": metrics["failed_improvement_plans"],
            "completed_improvement_plans": metrics["completed_improvement_plans"],
            "manual_improvement_adjustment": improvement_details["manual_adjustment"],
            "manual_adjustment": round(manual_adjustment, 4),
        }

    @classmethod
    def rank_position_results(cls, results, calculated_at):
        """Rank one complete eligible position group without mutating its inputs."""
        if not isinstance(results, (list, tuple)):
            raise ValueError("岗位绩效结果必须为列表")
        timestamp = str(calculated_at or "").strip()
        if not timestamp:
            raise ValueError("排名计算时间不能为空")
        normalized = []
        position_ids = set()
        user_ids = set()
        for result in results:
            if not isinstance(result, dict):
                raise ValueError("岗位绩效结果格式无效")
            if result.get("eligibility_status") != ELIGIBILITY_ELIGIBLE:
                raise ValueError("排名只能包含合格参评员工")
            position_id = result.get("position_id_snapshot")
            if position_id is None:
                position_id = result.get("position_id")
            if position_id in (None, ""):
                raise ValueError("排名结果缺少岗位快照")
            try:
                user_id = int(result.get("user_id"))
            except (TypeError, ValueError) as exc:
                raise ValueError("排名结果缺少稳定员工主键") from exc
            if user_id in user_ids:
                raise ValueError("排名结果包含重复员工")
            user_ids.add(user_id)
            position_ids.add(position_id)
            normalized.append(
                {
                    "user_id": user_id,
                    "position_id": position_id,
                    "total_score": cls._number(
                        result.get("total_score"), "绩效总分"
                    ),
                }
            )
        if len(position_ids) > 1:
            raise ValueError("一次排名只能包含同一岗位")
        ranking_input = sorted(normalized, key=lambda item: item["user_id"])
        ranking_json = cls.canonical_json(ranking_input)
        ranking_digest = hashlib.sha256(ranking_json.encode("utf-8")).hexdigest()
        calculation_group_json = cls.canonical_json(
            {"calculated_at": timestamp, "ranking": ranking_input}
        )
        calculation_group_id = hashlib.sha256(
            calculation_group_json.encode("utf-8")
        ).hexdigest()
        ordered = sorted(
            (deepcopy(item) for item in results),
            key=lambda item: (-float(item["total_score"]), int(item["user_id"])),
        )
        rank_total = len(ordered) if len(ordered) >= 3 else None
        previous_score = None
        current_rank = None
        ranked = []
        for index, item in enumerate(ordered, start=1):
            score = float(item["total_score"])
            if rank_total is not None and score != previous_score:
                current_rank = index
            item["rank_no"] = current_rank if rank_total is not None else None
            item["rank_total"] = rank_total
            item["calculated_at"] = timestamp
            item["ranking_digest"] = ranking_digest
            item["calculation_group_id"] = calculation_group_id
            ranked.append(item)
            previous_score = score
        return ranked

    @classmethod
    def score_legacy_worker(cls, metrics, max_output, review=None, handoff=None):
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
            return 0.0
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
            reasons.append(f"工序质量低分{quality_details['handoff_low_count']}次")
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
            "work_time_record_count": metrics.get("work_time_record_count", 0),
            "work_time_days": metrics.get("work_time_days", 0),
            "work_time_quantity": metrics.get("work_time_quantity", 0),
            "work_time_standard_minutes": metrics.get("work_time_standard_minutes", 0),
            "work_time_actual_minutes": metrics.get("work_time_actual_minutes", 0),
            "work_time_effective_minutes": metrics.get("work_time_effective_minutes", 0),
            "work_time_efficiency": metrics.get("work_time_efficiency", 0),
            "work_time_abnormal_count": metrics.get("work_time_abnormal_count", 0),
            "work_time_missing_standard_count": metrics.get("work_time_missing_standard_count", 0),
        }
