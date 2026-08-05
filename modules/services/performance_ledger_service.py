"""Generate immutable, versioned performance batches from frozen facts."""

from collections import defaultdict
from datetime import datetime
import json

from modules.domain.errors import ConflictError, NotFoundError
from modules.domain.performance_policy import (
    ELIGIBILITY_ELIGIBLE,
    validate_production_month,
)
from modules.domain.reporting_day import reporting_month_bounds
from modules.repositories.performance_configuration_repository import (
    PerformanceConfigurationRepository,
)
from modules.repositories.performance_ledger_repository import (
    PerformanceLedgerRepository,
)
from modules.services import BaseService
from modules.services.performance_authorization_service import (
    PerformanceAuthorizationService,
)
from modules.services.performance_fact_collector import PerformanceFactCollector
from modules.services.performance_scoring_policy import PerformanceScoringPolicy


class PerformanceLedgerService:
    @staticmethod
    def _canonical(value):
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @staticmethod
    def _json_object(value):
        if isinstance(value, dict):
            return dict(value)
        try:
            parsed = json.loads(value or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("绩效事实 JSON 无效") from exc
        if not isinstance(parsed, dict):
            raise ValueError("绩效事实 JSON 必须是对象")
        return parsed

    @staticmethod
    def _require_preparer(actor):
        if not PerformanceAuthorizationService.can_perform(actor, "prepare"):
            raise PermissionError("performance:prepare permission is required")
        actor_id = (actor or {}).get("id")
        if actor_id is None:
            raise PermissionError("绩效制单人不存在")
        return int(actor_id), str(
            (actor or {}).get("name") or (actor or {}).get("username") or ""
        )

    @classmethod
    def create_batch(cls, data, actor, db=None):
        """Create one batch atomically; an explicit db is owned by its caller."""
        if not isinstance(data, dict):
            raise ValueError("绩效批次参数无效")
        actor_id, actor_name = cls._require_preparer(actor)
        production_month = validate_production_month(data.get("production_month"))
        idempotency_key = str(data.get("idempotency_key") or "").strip()
        if not idempotency_key:
            raise ValueError("绩效批次幂等键不能为空")
        if len(idempotency_key) > 200:
            raise ValueError("绩效批次幂等键过长")
        command = {
            "production_month": production_month,
            "idempotency_key": idempotency_key,
            "source_cutoff_at": str(data.get("source_cutoff_at") or "").strip(),
            "revision_reason": str(data.get("revision_reason") or "").strip(),
            "rule_version_id": data.get("rule_version_id"),
            "request_id": str(data.get("request_id") or "").strip(),
        }
        if db is not None:
            return cls._create_txn(command, actor_id, actor_name, db)
        with BaseService.transaction() as txn:
            return cls._create_txn(command, actor_id, actor_name, txn)

    @classmethod
    def _create_txn(cls, command, actor_id, actor_name, db):
        existing = PerformanceLedgerRepository.batch_by_idempotency_key(
            command["idempotency_key"], db=db
        )
        if existing:
            if existing["production_month"] != command["production_month"]:
                raise ConflictError("同一绩效幂等键不能用于不同生产月份")
            result = PerformanceLedgerRepository.batch_summary(existing["id"], db=db)
            result["idempotent_replay"] = True
            return result

        rule = PerformanceConfigurationRepository.published_rule_for_month(
            command["production_month"], db=db
        )
        if not rule:
            raise NotFoundError("未找到当月已发布的绩效规则")
        requested_rule_id = command.get("rule_version_id")
        if requested_rule_id not in (None, ""):
            try:
                requested_rule_id = int(requested_rule_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("绩效规则版本无效") from exc
            if requested_rule_id != int(rule["id"]):
                raise ConflictError("指定绩效规则不是该月生效的已发布版本")

        period_start, period_end = reporting_month_bounds(command["production_month"])
        source_cutoff_at = command["source_cutoff_at"] or (
            PerformanceLedgerRepository.database_now(db=db)
        )
        try:
            datetime.fromisoformat(source_cutoff_at)
        except ValueError as exc:
            raise ValueError("绩效来源截止时间无效") from exc
        if source_cutoff_at < period_start:
            raise ValueError("绩效来源截止时间不能早于生产月开始时间")

        current_approved = PerformanceLedgerRepository.current_approved_batch(
            command["production_month"], db=db
        )
        version = PerformanceLedgerRepository.next_version(
            command["production_month"], db=db
        )
        batch_id = PerformanceLedgerRepository.insert_batch(
            {
                "production_month": command["production_month"],
                "version": version,
                "period_start": period_start,
                "period_end": period_end,
                "source_cutoff_at": source_cutoff_at,
                "rule_version_id": rule["id"],
                "idempotency_key": command["idempotency_key"],
                "prepared_by": actor_id,
                "prepared_by_name": actor_name,
                "supersedes_batch_id": (
                    current_approved["id"] if current_approved else None
                ),
                "revision_reason": command["revision_reason"],
            },
            db,
        )
        collection = PerformanceFactCollector.collect(batch_id, db=db)
        contexts = cls._candidate_contexts(
            batch_id,
            command["production_month"],
            collection["candidate_user_ids"],
            collection["facts"],
            db,
        )
        pending_counts = PerformanceLedgerRepository.pending_exception_counts(
            batch_id, db=db
        )
        calculated_at = PerformanceLedgerRepository.database_now(db=db)
        results = cls._score_candidates(
            rule, contexts, pending_counts, calculated_at
        )
        for result in sorted(results, key=lambda item: int(item["user_id"])):
            PerformanceLedgerRepository.insert_score_revision(
                cls._score_payload(batch_id, result, actor_id, actor_name), db
            )

        summary_payload = {
            "production_month": command["production_month"],
            "version": version,
            "source_cutoff_at": source_cutoff_at,
            "input_digest": collection["input_digest"],
            "fact_count": collection["fact_count"],
            "candidate_count": len(contexts),
            "score_count": len(results),
            "eligible_count": sum(
                item["eligibility_status"] == ELIGIBILITY_ELIGIBLE
                for item in results
            ),
        }
        PerformanceLedgerRepository.insert_batch_event(
            {
                "batch_id": batch_id,
                "event_type": "batch_generated",
                "from_status": "",
                "to_status": "draft",
                "operator_id": actor_id,
                "operator_name": actor_name,
                "reason": command["revision_reason"],
                "payload_json": cls._canonical(summary_payload),
                "request_id": command["request_id"],
                "idempotency_key": "performance-batch-generated:"
                + command["idempotency_key"],
            },
            db,
        )
        result = PerformanceLedgerRepository.batch_summary(batch_id, db=db)
        result["idempotent_replay"] = False
        return result

    @classmethod
    def _candidate_contexts(
        cls, batch_id, production_month, candidate_user_ids, facts, db
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

            if len(position_ids) > 1:
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
            if position_id is None:
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
            if len(department_ids) > 1:
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
                target = PerformanceConfigurationRepository.approved_target_for_month(
                    position_id, production_month, db=db
                )
                if not target:
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
                    "position_name_snapshot": (
                        representative.get("position_name_snapshot", "")
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
    def _score_candidates(cls, rule, contexts, pending_counts, calculated_at):
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
                review=None,
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
    def _score_payload(cls, batch_id, result, actor_id, actor_name):
        metrics = result["metrics"]
        return {
            "batch_id": batch_id,
            "user_id": result["user_id"],
            "revision": 1,
            "employee_name_snapshot": result["employee_name_snapshot"],
            "employee_no_snapshot": result["employee_no_snapshot"],
            "role_type_snapshot": result["role_type_snapshot"],
            "department_id_snapshot": result["department_id_snapshot"],
            "department_name_snapshot": result["department_name_snapshot"],
            "position_id_snapshot": result["position_id_snapshot"],
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
            "discipline_deduction": result.get("discipline_deduction") or 0,
            "discipline_reason": result.get("discipline_reason") or "",
            "improvement_deduction": result.get("improvement_deduction") or 0,
            "improvement_reason": result.get("improvement_reason") or "",
            "manual_score": (
                result.get("manual_score")
                if result.get("manual_score") is not None
                else PerformanceScoringPolicy.MANUAL_SCORE_DEFAULT
            ),
            "manual_comment": result.get("manual_comment") or "",
            "score_details_json": cls._canonical(result["score_details"]),
            "rule_version_id": result["rule_version_id"],
            "position_target_version_id": result["position_target_version_id"],
            "review_revision_id": None,
            "input_digest": result["input_digest"],
            "ranking_digest": result.get("ranking_digest") or "",
            "calculation_group_id": result.get("calculation_group_id") or "",
            "calculated_at": result["calculated_at"],
            "created_by": actor_id,
            "created_by_name": actor_name,
        }
