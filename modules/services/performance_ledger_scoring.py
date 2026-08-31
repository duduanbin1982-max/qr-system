"""Candidate aggregation and deterministic scoring for performance batches."""

from collections import defaultdict

from modules.domain.performance_policy import ELIGIBILITY_ELIGIBLE
from modules.domain.reporting_day import reporting_month_bounds
from modules.repositories.performance_configuration_repository import (
    PerformanceConfigurationRepository,
)
from modules.repositories.performance_ledger_repository import (
    PerformanceLedgerRepository,
)
from modules.services.performance_scoring_policy import PerformanceScoringPolicy
from modules.services.position_snapshot_service import PositionSnapshotService


class PerformanceLedgerScoringMixin:
    @staticmethod
    def _score_revision_changed(previous, result):
        if previous is None:
            return True
        fields = (
            "position_id_snapshot",
            "position_version_id_snapshot",
            "position_name_snapshot",
            "eligibility_status",
            "eligibility_reason_code",
            "eligibility_reason",
            "output_score",
            "quality_score",
            "delivery_score",
            "discipline_score",
            "improvement_score",
            "total_score",
            "rank_no",
            "rank_total",
            "warning_level",
            "warning_reason",
            "discipline_deduction",
            "discipline_reason",
            "improvement_deduction",
            "improvement_reason",
            "manual_score",
            "manual_comment",
        )
        for field in fields:
            old_value = previous.get(field)
            new_value = result.get(field)
            if isinstance(old_value, float) or isinstance(new_value, float):
                if old_value is None or new_value is None:
                    if old_value != new_value:
                        return True
                elif round(float(old_value), 6) != round(float(new_value), 6):
                    return True
            elif old_value != new_value:
                return True
        return False

    @classmethod
    def _candidate_contexts(
        cls,
        batch_id,
        production_month,
        candidate_user_ids,
        facts,
        db,
        *,
        target_by_position=None,
        record_exceptions=True,
    ):
        facts_by_user = defaultdict(list)
        for fact in facts:
            if fact.get("user_id") is not None:
                facts_by_user[int(fact["user_id"])].append(fact)

        contexts = []
        for user_id in sorted(int(value) for value in candidate_user_ids):
            user_facts = facts_by_user[user_id]
            position_ids = sorted(
                {
                    int(fact["position_id_snapshot"])
                    for fact in user_facts
                    if fact.get("position_id_snapshot") is not None
                }
            )
            department_ids = sorted(
                {
                    int(fact["department_id_snapshot"])
                    for fact in user_facts
                    if fact.get("department_id_snapshot") is not None
                }
            )
            position_id = position_ids[0] if len(position_ids) == 1 else None
            department_id = department_ids[0] if len(department_ids) == 1 else None
            representative = cls._representative_fact(user_facts, position_id)
            position_version = None
            if position_id is not None and any(
                fact.get("position_version_id") is not None
                for fact in user_facts
                if fact.get("position_id_snapshot") == position_id
            ):
                _, period_end = reporting_month_bounds(production_month)
                position_version = PositionSnapshotService.version_at(
                    position_id, period_end, db=db
                )

            if record_exceptions and len(position_ids) > 1:
                cls._insert_candidate_exception(
                    batch_id,
                    user_id,
                    "ambiguous_position_snapshot",
                    {
                        "user_id": user_id,
                        "position_ids": position_ids,
                        "production_month": production_month,
                    },
                    db,
                )
            if record_exceptions and position_id is None:
                cls._insert_candidate_exception(
                    batch_id,
                    user_id,
                    "missing_position_snapshot",
                    {
                        "user_id": user_id,
                        "observed_position_ids": position_ids,
                        "production_month": production_month,
                    },
                    db,
                )
            if record_exceptions and len(department_ids) > 1:
                cls._insert_candidate_exception(
                    batch_id,
                    user_id,
                    "ambiguous_department_snapshot",
                    {
                        "user_id": user_id,
                        "department_ids": department_ids,
                        "production_month": production_month,
                    },
                    db,
                )

            target = None
            if position_id is not None:
                if target_by_position and position_id in target_by_position:
                    target = target_by_position[position_id]
                else:
                    target = PerformanceConfigurationRepository.approved_target_for_month(
                        position_id, production_month, db=db
                    )
                if record_exceptions and not target:
                    cls._insert_candidate_exception(
                        batch_id,
                        user_id,
                        "missing_position_target",
                        {
                            "user_id": user_id,
                            "position_id": position_id,
                            "position_name_snapshot": representative.get(
                                "position_name_snapshot", ""
                            ),
                            "production_month": production_month,
                        },
                        db,
                    )

            metrics, quality_facts, quality_totals = cls._aggregate_facts(user_facts)
            metrics.update(
                {
                    "user_id": user_id,
                    "position_id_snapshot": position_id,
                }
            )
            contexts.append(
                {
                    "user_id": user_id,
                    "employee_name_snapshot": representative.get(
                        "employee_name_snapshot", ""
                    ),
                    "employee_no_snapshot": representative.get(
                        "employee_no_snapshot", ""
                    ),
                    "role_type_snapshot": "",
                    "department_id_snapshot": department_id,
                    "department_name_snapshot": (
                        representative.get("department_name_snapshot", "")
                        if department_id is not None
                        else ""
                    ),
                    "position_id_snapshot": position_id,
                    "position_version_id_snapshot": (
                        position_version["id"] if position_version else None
                    ),
                    "position_name_snapshot": (
                        (
                            position_version["name"]
                            if position_version
                            else representative.get("position_name_snapshot", "")
                        )
                        if position_id is not None
                        else ""
                    ),
                    "target": target,
                    "metrics": metrics,
                    "quality_facts": quality_facts,
                    **quality_totals,
                }
            )
        return contexts

    @staticmethod
    def _representative_fact(facts, position_id):
        ordered = sorted(
            facts,
            key=lambda item: (
                item.get("business_at") or "",
                item.get("fact_type") or "",
                item.get("source_type") or "",
                int(item.get("source_id") or 0),
            ),
        )
        if position_id is not None:
            for fact in ordered:
                if fact.get("position_id_snapshot") == position_id:
                    return fact
        return ordered[0] if ordered else {}

    @classmethod
    def _insert_candidate_exception(
        cls, batch_id, user_id, exception_type, snapshot, db
    ):
        PerformanceLedgerRepository.insert_exception(
            {
                "batch_id": batch_id,
                "user_id": user_id,
                "exception_type": exception_type,
                "source_type": "user",
                "source_id": user_id,
                "snapshot_json": cls._canonical(snapshot),
            },
            db,
        )

    @classmethod
    def _aggregate_facts(cls, facts):
        output_qty = 0.0
        report_count = 0
        work_days = set()
        open_plans = 0
        failed_plans = 0
        completed_plans = 0
        scrap_qty = 0.0
        rework_qty = 0.0
        inspection_failed_qty = 0.0
        quality_facts = []

        for fact in facts:
            payload = cls._json_object(fact.get("payload_json"))
            if fact.get("fact_type") == "work":
                record_type = str(payload.get("record_type") or "normal").lower()
                if record_type == "normal":
                    output_qty += float(fact.get("quantity") or 0)
                    report_count += 1
                    production_day = str(payload.get("production_day") or "").strip()
                    if production_day:
                        work_days.add(production_day)
            elif fact.get("fact_type") == "quality_event":
                event_type = str(payload.get("event_type") or "").strip().lower()
                event_type = event_type.replace("-", "_")
                snapshot = payload.get("snapshot")
                if not isinstance(snapshot, dict):
                    snapshot = {}
                severity = str(
                    payload.get("evaluation_severity")
                    or snapshot.get("severity")
                    or snapshot.get("defect_level")
                    or ""
                )
                quantity = float(fact.get("quantity") or 0)
                quality_facts.append(
                    {
                        "canonical_event_id": fact.get("canonical_event_id"),
                        "source_type": fact.get("source_type"),
                        "source_id": fact.get("source_id"),
                        "event_type": event_type,
                        "quantity": quantity,
                        "rating": payload.get("rating"),
                        "severity": severity,
                    }
                )
                if event_type == "scrap":
                    scrap_qty += quantity
                elif event_type == "rework":
                    rework_qty += quantity
                elif event_type in PerformanceScoringPolicy.BAD_QUALITY_EVENT_TYPES:
                    inspection_failed_qty += quantity
            elif fact.get("fact_type") == "plan_status":
                status = str(payload.get("status") or "").strip().lower()
                if status == "active":
                    open_plans += 1
                elif status == "reassessment_pending":
                    failed_plans += 1
                elif status == "closed":
                    completed_plans += 1

        number = lambda value: int(value) if float(value).is_integer() else value
        return (
            {
                "output_qty": number(output_qty),
                "report_count": report_count,
                "work_days": len(work_days),
                "open_improvement_plans": open_plans,
                "failed_improvement_plans": failed_plans,
                "completed_improvement_plans": completed_plans,
            },
            quality_facts,
            {
                "scrap_qty": number(scrap_qty),
                "rework_qty": number(rework_qty),
                "inspection_failed_qty": number(inspection_failed_qty),
            },
        )

    @classmethod
    def _score_candidates(
        cls,
        rule,
        contexts,
        pending_counts,
        calculated_at,
        review_by_user=None,
    ):
        review_by_user = review_by_user or {}
        results = []
        eligible_by_position = defaultdict(list)
        for context in contexts:
            metrics = dict(context["metrics"])
            metrics["unresolved_exception_count"] = pending_counts.get(
                context["user_id"], 0
            )
            score = PerformanceScoringPolicy.score_worker(
                rule,
                context["target"],
                metrics,
                review=review_by_user.get(context["user_id"]),
                quality_facts=context["quality_facts"],
            )
            result = {
                **context,
                **score,
                "metrics": metrics,
                "calculated_at": calculated_at,
                "ranking_digest": "",
                "calculation_group_id": "",
            }
            if result["eligibility_status"] == ELIGIBILITY_ELIGIBLE:
                eligible_by_position[result["position_id_snapshot"]].append(result)
            else:
                results.append(result)

        for position_id in sorted(eligible_by_position):
            results.extend(
                PerformanceScoringPolicy.rank_position_results(
                    eligible_by_position[position_id], calculated_at
                )
            )
        return results

    @classmethod
    def _score_payload(
        cls,
        batch_id,
        result,
        actor_id,
        actor_name,
        *,
        revision=1,
        review_revision_id=None,
        review=None,
    ):
        metrics = result["metrics"]
        review = review or {}
        return {
            "batch_id": batch_id,
            "user_id": result["user_id"],
            "revision": revision,
            "employee_name_snapshot": result["employee_name_snapshot"],
            "employee_no_snapshot": result["employee_no_snapshot"],
            "role_type_snapshot": result["role_type_snapshot"],
            "department_id_snapshot": result["department_id_snapshot"],
            "department_name_snapshot": result["department_name_snapshot"],
            "position_id_snapshot": result["position_id_snapshot"],
            "position_version_id_snapshot": result.get(
                "position_version_id_snapshot"
            ),
            "position_name_snapshot": result["position_name_snapshot"],
            "eligibility_status": result["eligibility_status"],
            "eligibility_reason_code": result["eligibility_reason_code"],
            "eligibility_reason": result["eligibility_reason"],
            "output_qty": metrics["output_qty"],
            "report_count": metrics["report_count"],
            "work_days": metrics["work_days"],
            "scrap_qty": result["scrap_qty"],
            "rework_qty": result["rework_qty"],
            "inspection_failed_qty": result["inspection_failed_qty"],
            "output_score": result["output_score"],
            "quality_score": result["quality_score"],
            "delivery_score": result["delivery_score"],
            "discipline_score": result["discipline_score"],
            "improvement_score": result["improvement_score"],
            "total_score": result["total_score"],
            "rank_no": result["rank_no"],
            "rank_total": result["rank_total"],
            "warning_level": result["warning_level"],
            "warning_reason": result["warning_reason"],
            "discipline_deduction": result.get("discipline_deduction")
            if result.get("discipline_deduction") is not None
            else review.get("discipline_deduction", 0),
            "discipline_reason": result.get("discipline_reason")
            or review.get("discipline_reason", ""),
            "improvement_deduction": result.get("improvement_deduction")
            if result.get("improvement_deduction") is not None
            else review.get("improvement_adjustment", 0),
            "improvement_reason": result.get("improvement_reason")
            or review.get("improvement_reason", ""),
            "manual_score": (
                result.get("manual_score")
                if result.get("manual_score") is not None
                else review.get(
                    "manual_score", PerformanceScoringPolicy.MANUAL_SCORE_DEFAULT
                )
            ),
            "manual_comment": result.get("manual_comment")
            or review.get("manual_comment", ""),
            "score_details_json": cls._canonical(result["score_details"]),
            "rule_version_id": result["rule_version_id"],
            "position_target_version_id": result["position_target_version_id"],
            "review_revision_id": review_revision_id,
            "input_digest": result["input_digest"],
            "ranking_digest": result.get("ranking_digest") or "",
            "calculation_group_id": result.get("calculation_group_id") or "",
            "calculated_at": result["calculated_at"],
            "created_by": actor_id,
            "created_by_name": actor_name,
        }
