"""Generate immutable, versioned performance batches from frozen facts."""

from datetime import datetime
import json

from modules.domain import evidence_protocol
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
from modules.services.performance_ledger_queries import PerformanceLedgerQueryMixin
from modules.services.performance_ledger_review import PerformanceLedgerReviewMixin
from modules.services.performance_ledger_scoring import PerformanceLedgerScoringMixin
from modules.services.performance_ledger_workflow import PerformanceLedgerWorkflowMixin


class PerformanceLedgerService(
    PerformanceLedgerWorkflowMixin,
    PerformanceLedgerReviewMixin,
    PerformanceLedgerQueryMixin,
    PerformanceLedgerScoringMixin,
):
    @staticmethod
    def _canonical(value):
        return evidence_protocol.canonical_json_v1(value)

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
            event = PerformanceLedgerRepository.event_by_idempotency_key(
                "performance-batch-generated:" + command["idempotency_key"],
                db=db,
            )
            result.update(
                {
                    "event_id": event["id"] if event else None,
                    "idempotent_replay": True,
                }
            )
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
        event_id = PerformanceLedgerRepository.insert_batch_event(
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
        result.update({"event_id": event_id, "idempotent_replay": False})
        return result
