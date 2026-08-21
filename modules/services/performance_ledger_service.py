"""Generate immutable, versioned performance batches from frozen facts."""

from collections import defaultdict
from datetime import datetime
import hashlib
import json

from modules.domain.errors import ConflictError, NotFoundError
from modules.domain.performance_policy import (
    BATCH_STATUS_APPROVAL_PENDING,
    BATCH_STATUS_APPROVED,
    BATCH_STATUS_CANCELLED,
    BATCH_STATUS_DRAFT,
    ELIGIBILITY_ELIGIBLE,
    BATCH_STATUS_SUPERSEDED,
    BATCH_STATUS_SUPERVISOR_REVIEW,
    validate_production_month,
)
from modules.domain.reporting_day import reporting_month_bounds
from modules.repositories.performance_configuration_repository import (
    PerformanceConfigurationRepository,
)
from modules.repositories.performance_ledger_repository import (
    PerformanceLedgerRepository,
)
from modules.repositories.performance_fact_repository import PerformanceFactRepository
from modules.services import BaseService
from modules.services.performance_authorization_service import (
    PerformanceAuthorizationService,
)
from modules.services.position_snapshot_service import PositionSnapshotService
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

    @staticmethod
    def _actor_identity(actor, label="绩效操作人"):
        actor_id = (actor or {}).get("id")
        if actor_id is None:
            raise PermissionError(label + "不存在")
        return int(actor_id), str(
            (actor or {}).get("name") or (actor or {}).get("username") or ""
        )

    @classmethod
    def _require_approver(cls, actor):
        if not PerformanceAuthorizationService.can_perform(actor, "approve"):
            raise PermissionError("performance:approve permission is required")
        if not PerformanceAuthorizationService.can_perform(actor, "view_all"):
            raise PermissionError("performance:view_all permission is required")
        return cls._actor_identity(actor, "绩效批准人")

    @staticmethod
    def _workflow_command(data, *, require_reason=False):
        if not isinstance(data, dict):
            raise ValueError("绩效批次工作流参数无效")
        expected_row_version = data.get("row_version")
        if expected_row_version in (None, ""):
            expected_row_version = data.get("expected_row_version")
        try:
            expected_row_version = int(expected_row_version)
        except (TypeError, ValueError) as exc:
            raise ValueError("绩效批次版本号无效") from exc
        if expected_row_version < 0:
            raise ValueError("绩效批次版本号无效")
        idempotency_key = str(data.get("idempotency_key") or "").strip()
        if not idempotency_key:
            raise ValueError("绩效批次工作流幂等键不能为空")
        if len(idempotency_key) > 200:
            raise ValueError("绩效批次工作流幂等键过长")
        reason = str(data.get("reason") or "").strip()
        if require_reason and not reason:
            raise ValueError("绩效批次退回或取消必须填写原因")
        return {
            "expected_row_version": expected_row_version,
            "idempotency_key": idempotency_key,
            "request_id": str(data.get("request_id") or "").strip(),
            "reason": reason,
        }

    @staticmethod
    def _event_key(action, idempotency_key):
        return "performance-batch-" + action + ":" + idempotency_key

    @classmethod
    def _workflow_replay(cls, batch_id, actor_id, event_key, db):
        event = PerformanceLedgerRepository.event_by_idempotency_key(
            event_key, db=db
        )
        if not event:
            return None
        if int(event.get("batch_id") or 0) != int(batch_id):
            raise ConflictError("同一工作流幂等键不能用于其他绩效批次")
        if int(event.get("operator_id") or 0) != int(actor_id):
            raise PermissionError("绩效工作流幂等请求只能由原操作人重试")
        result = PerformanceLedgerRepository.batch_summary(batch_id, db=db)
        if result is None:
            raise NotFoundError("绩效批次不存在")
        payload = cls._json_object(event.get("payload_json"))
        replacement_id = payload.get("replacement_batch_id")
        if replacement_id is not None:
            replacement_id = int(replacement_id)
            result.update(
                {
                    "input_drift_detected": True,
                    "replacement_batch_id": replacement_id,
                    "replacement": PerformanceLedgerRepository.batch_summary(
                        replacement_id, db=db
                    ),
                }
            )
        result.update(
            {
                "event_id": event["id"],
                "idempotent_replay": True,
            }
        )
        return result

    @classmethod
    def _insert_workflow_event(
        cls,
        *,
        batch_id,
        event_type,
        from_status,
        to_status,
        actor_id,
        actor_name,
        command,
        event_key,
        payload=None,
        db,
    ):
        return PerformanceLedgerRepository.insert_batch_event(
            {
                "batch_id": batch_id,
                "event_type": event_type,
                "from_status": from_status,
                "to_status": to_status,
                "operator_id": actor_id,
                "operator_name": actor_name,
                "reason": command["reason"],
                "payload_json": cls._canonical(payload or {}),
                "request_id": command["request_id"],
                "idempotency_key": event_key,
            },
            db,
        )

    @staticmethod
    def _require_batch(batch_id, db):
        batch = PerformanceLedgerRepository.batch(batch_id, db=db)
        if not batch:
            raise NotFoundError("绩效批次不存在")
        return batch

    @staticmethod
    def _require_owned_batch(batch, actor_id):
        if batch.get("prepared_by") != actor_id:
            raise PermissionError("只能由绩效制单人操作该批次")

    @staticmethod
    def _require_batch_state(batch, *statuses):
        if batch["status"] not in statuses:
            raise ConflictError("绩效批次当前状态不允许此操作")

    @staticmethod
    def _require_batch_version(batch, expected_row_version):
        if int(batch["row_version"]) != int(expected_row_version):
            raise ConflictError("绩效批次版本号已被其他操作修改，请刷新后重试")

    @classmethod
    def _transition_result(
        cls,
        batch_id,
        actor_id,
        actor_name,
        command,
        *,
        event_action,
        event_type,
        current_status,
        target_status,
        fields=None,
        payload=None,
        db,
    ):
        event_key = cls._event_key(event_action, command["idempotency_key"])
        replay = cls._workflow_replay(batch_id, actor_id, event_key, db)
        if replay:
            return replay
        batch = cls._require_batch(batch_id, db)
        cls._require_batch_state(batch, current_status)
        cls._require_batch_version(batch, command["expected_row_version"])
        if not PerformanceLedgerRepository.transition_batch(
            batch_id,
            command["expected_row_version"],
            current_status,
            target_status,
            fields or {},
            db,
        ):
            raise ConflictError("绩效批次版本号已被其他操作修改，请刷新后重试")
        event_id = cls._insert_workflow_event(
            batch_id=batch_id,
            event_type=event_type,
            from_status=current_status,
            to_status=target_status,
            actor_id=actor_id,
            actor_name=actor_name,
            command=command,
            event_key=event_key,
            payload=payload,
            db=db,
        )
        result = PerformanceLedgerRepository.batch_summary(batch_id, db=db)
        result.update({"event_id": event_id, "idempotent_replay": False})
        return result

    @classmethod
    def submit_supervisor_review(cls, batch_id, data, actor, db=None):
        actor_id, actor_name = cls._require_preparer(actor)
        command = cls._workflow_command(data)

        def execute(txn):
            event_key = cls._event_key(
                "submit-supervisor-review", command["idempotency_key"]
            )
            replay = cls._workflow_replay(batch_id, actor_id, event_key, txn)
            if replay:
                return replay
            batch = cls._require_batch(batch_id, txn)
            cls._require_owned_batch(batch, actor_id)
            frozen = PerformanceFactCollector.verify_frozen_input(batch_id, db=txn)
            if not frozen["valid"]:
                raise ConflictError("绩效批次已保存事实与输入摘要不一致")
            return cls._transition_result(
                batch_id,
                actor_id,
                actor_name,
                command,
                event_action="submit-supervisor-review",
                event_type="batch_submitted_supervisor_review",
                current_status=BATCH_STATUS_DRAFT,
                target_status=BATCH_STATUS_SUPERVISOR_REVIEW,
                db=txn,
            )

        if db is not None:
            return execute(db)
        with BaseService.transaction() as txn:
            return execute(txn)

    submit_for_supervisor_review = submit_supervisor_review

    @classmethod
    def check_batch_integrity(cls, batch_id, db=None, *, include_current=False):
        batch = cls._require_batch(batch_id, db)
        issues = []
        frozen = PerformanceFactCollector.verify_frozen_input(batch_id, db=db)
        if not batch.get("input_digest") or not frozen["valid"]:
            issues.append(
                {
                    "code": "frozen_input_mismatch",
                    "message": "绩效批次冻结事实与输入摘要不一致",
                }
            )
        unresolved = PerformanceLedgerRepository.unresolved_exceptions(
            batch_id, db=db
        )
        if unresolved:
            issues.append(
                {
                    "code": "unresolved_exceptions",
                    "message": "绩效批次仍有未确认异常",
                    "count": len(unresolved),
                    "exception_ids": [row["id"] for row in unresolved],
                }
            )
        scores = PerformanceLedgerRepository.latest_score_revisions(
            batch_id, db=db
        )
        if not scores:
            issues.append(
                {
                    "code": "missing_scores",
                    "message": "绩效批次没有员工评分修订版",
                }
            )
        eligible = [
            row for row in scores if row["eligibility_status"] == ELIGIBILITY_ELIGIBLE
        ]
        missing_targets = [
            int(row["user_id"])
            for row in eligible
            if row.get("position_target_version_id") is None
        ]
        if missing_targets:
            issues.append(
                {
                    "code": "eligible_scores_missing_target",
                    "message": "合格评分缺少岗位目标版本",
                    "user_ids": missing_targets,
                }
            )
        invalid_rule_or_input = [
            int(row["user_id"])
            for row in eligible
            if row.get("rule_version_id") != batch.get("rule_version_id")
            or not row.get("input_digest")
        ]
        if invalid_rule_or_input:
            issues.append(
                {
                    "code": "eligible_scores_missing_input",
                    "message": "合格评分缺少规则或输入摘要",
                    "user_ids": invalid_rule_or_input,
                }
            )
        incomplete_reviews = [
            int(row["user_id"])
            for row in eligible
            if row.get("review_revision_id") is None
        ]
        if incomplete_reviews:
            issues.append(
                {
                    "code": "incomplete_reviews",
                    "message": "合格员工尚未完成主管复核",
                    "user_ids": incomplete_reviews,
                }
            )
        current_input = None
        if include_current:
            current_input = PerformanceFactCollector.current_input_status(
                batch_id, db=db
            )
            if current_input["input_drift_detected"]:
                issues.append(
                    {
                        "code": "input_drift",
                        "message": "绩效来源在截止时点后发生变化",
                        "saved_input_digest": current_input["saved_input_digest"],
                        "current_input_digest": current_input["current_input_digest"],
                    }
                )
        return {
            "batch_id": int(batch_id),
            "complete": not issues,
            "issues": issues,
            "current_input": current_input,
        }

    @classmethod
    def _replace_drifted_batch(
        cls, batch, command, actor_id, actor_name, integrity, db
    ):
        event_key = cls._event_key("submit-approval", command["idempotency_key"])
        current_input = integrity["current_input"]
        replacement = cls._create_txn(
            {
                "production_month": batch["production_month"],
                "idempotency_key": "performance-drift-replacement:"
                + command["idempotency_key"],
                "source_cutoff_at": current_input["current_source_cutoff_at"],
                "revision_reason": (
                    "输入摘要漂移自动重采集；来源批次 #" + str(batch["id"])
                ),
                "rule_version_id": batch["rule_version_id"],
                "request_id": command["request_id"],
            },
            actor_id,
            actor_name,
            db,
        )
        if not PerformanceLedgerRepository.transition_batch(
            batch["id"],
            command["expected_row_version"],
            BATCH_STATUS_SUPERVISOR_REVIEW,
            BATCH_STATUS_CANCELLED,
            {},
            db,
        ):
            raise ConflictError("绩效批次版本号已被其他操作修改，请刷新后重试")
        payload = {
            "reason_code": "input_drift",
            "saved_input_digest": current_input["saved_input_digest"],
            "current_input_digest": current_input["current_input_digest"],
            "replacement_batch_id": replacement["batch_id"],
        }
        event_id = cls._insert_workflow_event(
            batch_id=batch["id"],
            event_type="batch_cancelled_input_drift",
            from_status=BATCH_STATUS_SUPERVISOR_REVIEW,
            to_status=BATCH_STATUS_CANCELLED,
            actor_id=actor_id,
            actor_name=actor_name,
            command={
                **command,
                "reason": "输入摘要漂移，系统已创建新的绩效批次版本",
            },
            event_key=event_key,
            payload=payload,
            db=db,
        )
        result = PerformanceLedgerRepository.batch_summary(batch["id"], db=db)
        result.update(
            {
                "event_id": event_id,
                "idempotent_replay": False,
                "input_drift_detected": True,
                "replacement_batch_id": replacement["batch_id"],
                "replacement": replacement,
            }
        )
        return result

    @classmethod
    def submit_approval(cls, batch_id, data, actor, db=None):
        actor_id, actor_name = cls._require_preparer(actor)
        command = cls._workflow_command(data)

        def execute(txn):
            event_key = cls._event_key("submit-approval", command["idempotency_key"])
            replay = cls._workflow_replay(batch_id, actor_id, event_key, txn)
            if replay:
                return replay
            batch = cls._require_batch(batch_id, txn)
            cls._require_owned_batch(batch, actor_id)
            cls._require_batch_state(batch, BATCH_STATUS_SUPERVISOR_REVIEW)
            cls._require_batch_version(batch, command["expected_row_version"])
            integrity = cls.check_batch_integrity(
                batch_id, db=txn, include_current=True
            )
            if integrity["current_input"]["input_drift_detected"]:
                return cls._replace_drifted_batch(
                    batch, command, actor_id, actor_name, integrity, txn
                )
            if not integrity["complete"]:
                raise ConflictError(
                    "绩效批次完整性检查未通过",
                    details={"issues": integrity["issues"]},
                )
            submitted_at = PerformanceLedgerRepository.database_now(db=txn)
            return cls._transition_result(
                batch_id,
                actor_id,
                actor_name,
                command,
                event_action="submit-approval",
                event_type="batch_submitted_approval",
                current_status=BATCH_STATUS_SUPERVISOR_REVIEW,
                target_status=BATCH_STATUS_APPROVAL_PENDING,
                fields={"submitted_at": submitted_at},
                payload={"integrity": integrity},
                db=txn,
            )

        if db is not None:
            return execute(db)
        with BaseService.transaction() as txn:
            return execute(txn)

    submit_for_approval = submit_approval

    @classmethod
    def return_batch(cls, batch_id, data, actor, db=None):
        actor_id, actor_name = cls._actor_identity(actor)
        command = cls._workflow_command(data, require_reason=True)

        def execute(txn):
            event_key = cls._event_key("return", command["idempotency_key"])
            event = PerformanceLedgerRepository.event_by_idempotency_key(
                event_key, db=txn
            )
            if event:
                if event["from_status"] == BATCH_STATUS_APPROVAL_PENDING:
                    cls._require_approver(actor)
                else:
                    cls._require_preparer(actor)
                return cls._workflow_replay(batch_id, actor_id, event_key, txn)
            batch = cls._require_batch(batch_id, txn)
            if batch["status"] == BATCH_STATUS_SUPERVISOR_REVIEW:
                cls._require_preparer(actor)
                cls._require_owned_batch(batch, actor_id)
                target_status = BATCH_STATUS_DRAFT
                event_type = "batch_returned_draft"
            elif batch["status"] == BATCH_STATUS_APPROVAL_PENDING:
                cls._require_approver(actor)
                if batch.get("prepared_by") == actor_id:
                    raise PermissionError("绩效制单人与批准人必须为不同用户")
                target_status = BATCH_STATUS_SUPERVISOR_REVIEW
                event_type = "batch_returned_supervisor_review"
            else:
                raise ConflictError("绩效批次当前状态不允许退回")
            return cls._transition_result(
                batch_id,
                actor_id,
                actor_name,
                command,
                event_action="return",
                event_type=event_type,
                current_status=batch["status"],
                target_status=target_status,
                db=txn,
            )

        if db is not None:
            return execute(db)
        with BaseService.transaction() as txn:
            return execute(txn)

    @classmethod
    def cancel_batch(cls, batch_id, data, actor, db=None):
        actor_id, actor_name = cls._require_preparer(actor)
        command = cls._workflow_command(data, require_reason=True)

        def execute(txn):
            event_key = cls._event_key("cancel", command["idempotency_key"])
            replay = cls._workflow_replay(batch_id, actor_id, event_key, txn)
            if replay:
                return replay
            batch = cls._require_batch(batch_id, txn)
            cls._require_owned_batch(batch, actor_id)
            cls._require_batch_state(
                batch, BATCH_STATUS_DRAFT, BATCH_STATUS_SUPERVISOR_REVIEW
            )
            return cls._transition_result(
                batch_id,
                actor_id,
                actor_name,
                command,
                event_action="cancel",
                event_type="batch_cancelled",
                current_status=batch["status"],
                target_status=BATCH_STATUS_CANCELLED,
                db=txn,
            )

        if db is not None:
            return execute(db)
        with BaseService.transaction() as txn:
            return execute(txn)

    @classmethod
    def approve_batch(cls, batch_id, data, actor, db=None):
        actor_id, actor_name = cls._require_approver(actor)
        command = cls._workflow_command(data)

        def execute(txn):
            event_key = cls._event_key("approve", command["idempotency_key"])
            replay = cls._workflow_replay(batch_id, actor_id, event_key, txn)
            if replay:
                return replay
            batch = cls._require_batch(batch_id, txn)
            cls._require_batch_state(batch, BATCH_STATUS_APPROVAL_PENDING)
            cls._require_batch_version(batch, command["expected_row_version"])
            if batch.get("prepared_by") == actor_id:
                raise PermissionError("绩效制单人与批准人必须为不同用户")
            integrity = cls.check_batch_integrity(
                batch_id, db=txn, include_current=True
            )
            if not integrity["complete"]:
                raise ConflictError(
                    "绩效批次完整性检查未通过",
                    details={"issues": integrity["issues"]},
                )
            current = PerformanceLedgerRepository.current_approved_batch(
                batch["production_month"], db=txn
            )
            expected_predecessor = batch.get("supersedes_batch_id")
            current_id = current["id"] if current else None
            if current_id != expected_predecessor:
                raise ConflictError("当前正式绩效版本已变化，请重新创建修订版")
            if current:
                if not PerformanceLedgerRepository.mark_superseded(
                    current["id"],
                    batch_id,
                    current["row_version"],
                    txn,
                ):
                    raise ConflictError("原正式绩效版本已被其他操作修改")
                cls._insert_workflow_event(
                    batch_id=current["id"],
                    event_type="batch_superseded",
                    from_status=BATCH_STATUS_APPROVED,
                    to_status=BATCH_STATUS_SUPERSEDED,
                    actor_id=actor_id,
                    actor_name=actor_name,
                    command=command,
                    event_key=cls._event_key(
                        "supersede", command["idempotency_key"]
                    ),
                    payload={"successor_batch_id": batch_id},
                    db=txn,
                )
            approved_at = PerformanceLedgerRepository.database_now(db=txn)
            if not PerformanceLedgerRepository.approve_batch(
                batch_id,
                command["expected_row_version"],
                actor_id,
                actor_name,
                approved_at,
                txn,
            ):
                raise ConflictError("绩效批次版本号已被其他操作修改，请刷新后重试")
            event_id = cls._insert_workflow_event(
                batch_id=batch_id,
                event_type="batch_approved",
                from_status=BATCH_STATUS_APPROVAL_PENDING,
                to_status=BATCH_STATUS_APPROVED,
                actor_id=actor_id,
                actor_name=actor_name,
                command=command,
                event_key=event_key,
                payload={"superseded_batch_id": current_id},
                db=txn,
            )
            result = PerformanceLedgerRepository.batch_summary(batch_id, db=txn)
            result.update({"event_id": event_id, "idempotent_replay": False})
            return result

        if db is not None:
            return execute(db)
        with BaseService.transaction() as txn:
            return execute(txn)

    approve = approve_batch
    cancel = cancel_batch

    @classmethod
    def create_revision(cls, source_batch_id, data, actor, db=None):
        actor_id, actor_name = cls._require_preparer(actor)
        command = cls._workflow_command(data, require_reason=True)

        def execute(txn):
            source = cls._require_batch(source_batch_id, txn)
            existing = PerformanceLedgerRepository.batch_by_idempotency_key(
                command["idempotency_key"], db=txn
            )
            if existing:
                if existing.get("supersedes_batch_id") != source_batch_id:
                    raise ConflictError("同一修订幂等键不能用于其他绩效批次")
                result = PerformanceLedgerRepository.batch_summary(
                    existing["id"], db=txn
                )
                event = PerformanceLedgerRepository.event_by_idempotency_key(
                    "performance-batch-generated:" + command["idempotency_key"],
                    db=txn,
                )
                result["event_id"] = event["id"] if event else None
                result["idempotent_replay"] = True
                return result
            cls._require_batch_state(source, BATCH_STATUS_APPROVED)
            cls._require_batch_version(source, command["expected_row_version"])
            result = cls._create_txn(
                {
                    "production_month": source["production_month"],
                    "idempotency_key": command["idempotency_key"],
                    "source_cutoff_at": PerformanceLedgerRepository.database_now(
                        db=txn
                    ),
                    "revision_reason": command["reason"],
                    "rule_version_id": source["rule_version_id"],
                    "request_id": command["request_id"],
                },
                actor_id,
                actor_name,
                txn,
            )
            if result["batch"].get("supersedes_batch_id") != source_batch_id:
                raise ConflictError("修订版必须引用当前正式绩效批次")
            return result

        if db is not None:
            return execute(db)
        with BaseService.transaction() as txn:
            return execute(txn)

    @classmethod
    def compare_batches(cls, base_batch_id, compare_batch_id, actor=None, db=None):
        if actor is not None and not any(
            PerformanceAuthorizationService.can_perform(actor, action)
            for action in ("view_all", "prepare", "approve")
        ):
            raise PermissionError("无权比较绩效批次")
        base = cls._require_batch(base_batch_id, db)
        compared = cls._require_batch(compare_batch_id, db)
        if base["production_month"] != compared["production_month"]:
            raise ConflictError("只能比较同一生产月份的绩效批次")
        base_scores = {
            int(row["user_id"]): row
            for row in PerformanceLedgerRepository.latest_score_revisions(
                base_batch_id, db=db
            )
        }
        compared_scores = {
            int(row["user_id"]): row
            for row in PerformanceLedgerRepository.latest_score_revisions(
                compare_batch_id, db=db
            )
        }
        fields = (
            "eligibility_status",
            "eligibility_reason_code",
            "output_score",
            "quality_score",
            "delivery_score",
            "discipline_score",
            "improvement_score",
            "total_score",
            "warning_level",
            "rank_no",
            "rank_total",
        )
        items = []
        for user_id in sorted(set(base_scores) | set(compared_scores)):
            before = base_scores.get(user_id)
            after = compared_scores.get(user_id)
            before_values = (
                {field: before.get(field) for field in fields} if before else None
            )
            after_values = (
                {field: after.get(field) for field in fields} if after else None
            )
            identity = after or before or {}
            items.append(
                {
                    "user_id": user_id,
                    "employee_name": identity.get("employee_name_snapshot") or "",
                    "employee_no": identity.get("employee_no_snapshot") or "",
                    "position_name": identity.get("position_name_snapshot") or "",
                    "before": before_values,
                    "after": after_values,
                    "changed_fields": [
                        field
                        for field in fields
                        if (before_values or {}).get(field)
                        != (after_values or {}).get(field)
                    ],
                }
            )
        return {
            "production_month": base["production_month"],
            "base_batch_id": int(base_batch_id),
            "compare_batch_id": int(compare_batch_id),
            "items": items,
        }

    @staticmethod
    def _require_reviewer(actor):
        if not PerformanceAuthorizationService.can_perform(
            actor, "review_department"
        ):
            raise PermissionError("performance:review_department permission is required")
        actor_id = (actor or {}).get("id")
        if actor_id is None:
            raise PermissionError("绩效复核人不存在")
        return int(actor_id), str(
            (actor or {}).get("name") or (actor or {}).get("username") or ""
        )

    @classmethod
    def save_supervisor_review(cls, data, actor, db=None):
        """Append a supervisor review and atomically recalculate its position group."""
        if not isinstance(data, dict):
            raise ValueError("主管复核参数无效")
        actor_id, actor_name = cls._require_reviewer(actor)
        try:
            batch_id = int(data.get("batch_id", data.get("performance_batch_id")))
            user_id = int(data.get("user_id", data.get("employee_id")))
        except (TypeError, ValueError) as exc:
            raise ValueError("批次和员工主键无效") from exc
        expected_row_version = data.get("row_version")
        if expected_row_version in (None, ""):
            expected_row_version = data.get("expected_row_version")
        try:
            expected_row_version = int(expected_row_version)
        except (TypeError, ValueError) as exc:
            raise ValueError("绩效批次版本号无效") from exc
        idempotency_key = str(
            data.get("idempotency_key")
            or data.get("review_idempotency_key")
            or ""
        ).strip()
        if not idempotency_key:
            raise ValueError("主管复核幂等键不能为空")
        if len(idempotency_key) > 200:
            raise ValueError("主管复核幂等键过长")
        review_input = data.get("review")
        if not isinstance(review_input, dict):
            review_input = data
        review = {
            "discipline_deduction": review_input.get("discipline_deduction", 0),
            "discipline_reason": review_input.get("discipline_reason", ""),
            "improvement_adjustment": review_input.get("improvement_adjustment", 0),
            "improvement_reason": review_input.get("improvement_reason", ""),
            "manual_score": review_input.get(
                "manual_score", PerformanceScoringPolicy.MANUAL_SCORE_DEFAULT
            ),
            "manual_comment": review_input.get("manual_comment", ""),
        }
        command = {
            "batch_id": batch_id,
            "user_id": user_id,
            "expected_row_version": expected_row_version,
            "idempotency_key": idempotency_key,
            "request_id": str(data.get("request_id") or "").strip(),
            "reason": str(data.get("reason") or "").strip(),
            "review": review,
        }
        if db is not None:
            return cls._save_supervisor_review_txn(
                command, actor_id, actor_name, actor, db
            )
        with BaseService.transaction() as txn:
            return cls._save_supervisor_review_txn(
                command, actor_id, actor_name, actor, txn
            )

    # A short alias keeps service callers consistent with the legacy performance API.
    save_review = save_supervisor_review

    @classmethod
    def _save_supervisor_review_txn(cls, command, actor_id, actor_name, actor, db):
        existing_review = PerformanceLedgerRepository.review_by_idempotency_key(
            command["idempotency_key"], db=db
        )
        if existing_review:
            if (
                int(existing_review["batch_id"]) != command["batch_id"]
                or int(existing_review["user_id"]) != command["user_id"]
            ):
                raise ConflictError("同一主管复核幂等键不能用于其他员工或批次")
            result = PerformanceLedgerRepository.batch_summary(
                command["batch_id"], db=db
            )
            if result is None:
                raise NotFoundError("绩效批次不存在")
            result.update(
                {
                    "review_id": existing_review["id"],
                    "review_revision": existing_review["revision"],
                    "changed_user_ids": [],
                    "event_id": (
                        PerformanceLedgerRepository.event_by_idempotency_key(
                            "performance-supervisor-review:"
                            + command["idempotency_key"],
                            db=db,
                        )
                        or {}
                    ).get("id"),
                    "idempotent_replay": True,
                }
            )
            return result

        batch = PerformanceLedgerRepository.batch(command["batch_id"], db=db)
        if not batch:
            raise NotFoundError("绩效批次不存在")
        if batch["status"] != "supervisor_review":
            raise ConflictError("只有主管复核状态的绩效批次允许保存复核")
        if int(batch["row_version"]) != command["expected_row_version"]:
            raise ConflictError("绩效批次版本号已被其他操作修改，请刷新后重试")
        if not PerformanceAuthorizationService.can_review_member(
            actor,
            command["batch_id"],
            command["user_id"],
            db=db,
        ):
            # Preserve the actor's full permission set while avoiding a second
            # authorization implementation in this service.
            raise PermissionError("主管无权复核该部门员工")

        latest_scores = PerformanceLedgerRepository.latest_score_revisions(
            command["batch_id"], db=db
        )
        latest_by_user = {int(row["user_id"]): row for row in latest_scores}
        if command["user_id"] not in latest_by_user:
            raise NotFoundError("绩效批次中不存在该员工")

        rule = PerformanceConfigurationRepository.rule(
            batch.get("rule_version_id"), db=db
        )
        if not rule:
            raise NotFoundError("绩效批次引用的绩效规则不存在")
        normalized_review = PerformanceScoringPolicy._normalize_review(
            command["review"]
        )
        normalized_rule = PerformanceScoringPolicy._normalize_rule(rule)
        # Validate reason requirements even when the employee is currently
        # ineligible; score_worker intentionally short-circuits those rows.
        PerformanceScoringPolicy._review_values(
            normalized_review, normalized_rule
        )

        facts = PerformanceFactRepository.list_batch_facts(
            command["batch_id"], db=db
        )
        candidate_ids = sorted(
            {int(row["user_id"]) for row in latest_scores if row.get("user_id") is not None}
        )
        if not candidate_ids:
            candidate_ids = sorted(
                {int(row["user_id"]) for row in facts if row.get("user_id") is not None}
            )
        target_by_position = {}
        for row in latest_scores:
            position_id = row.get("position_id_snapshot")
            target_id = row.get("position_target_version_id")
            if position_id is not None:
                position_id = int(position_id)
                target_by_position.setdefault(position_id, None)
                if target_id is not None:
                    target = PerformanceConfigurationRepository.target(target_id, db=db)
                    if target:
                        target_by_position[position_id] = target
        contexts = cls._candidate_contexts(
            command["batch_id"],
            batch["production_month"],
            candidate_ids,
            facts,
            db,
            target_by_position=target_by_position,
            record_exceptions=False,
        )
        context_by_user = {int(item["user_id"]): item for item in contexts}
        if command["user_id"] not in context_by_user:
            raise NotFoundError("绩效批次中不存在该员工的来源事实")

        review_by_user = {}
        for user_id in context_by_user:
            prior_review = PerformanceLedgerRepository.latest_review(
                command["batch_id"], user_id, db=db
            )
            if prior_review:
                review_by_user[user_id] = {
                    "discipline_deduction": prior_review["discipline_deduction"],
                    "discipline_reason": prior_review["discipline_reason"],
                    "improvement_adjustment": prior_review["improvement_adjustment"],
                    "improvement_reason": prior_review["improvement_reason"],
                    "manual_score": prior_review["manual_score"],
                    "manual_comment": prior_review["manual_comment"],
                }
        review_by_user[command["user_id"]] = normalized_review
        pending_counts = PerformanceLedgerRepository.pending_exception_counts(
            command["batch_id"], db=db
        )
        calculated_at = PerformanceLedgerRepository.database_now(db=db)
        results = cls._score_candidates(
            rule,
            contexts,
            pending_counts,
            calculated_at,
            review_by_user=review_by_user,
        )
        result_by_user = {int(item["user_id"]): item for item in results}
        target_result = result_by_user.get(command["user_id"])
        if target_result is None:
            raise NotFoundError("绩效批次中不存在该员工的评分结果")

        review_payload = {
            "batch_id": command["batch_id"],
            "user_id": command["user_id"],
            "revision": PerformanceLedgerRepository.next_review_revision(
                command["batch_id"], command["user_id"], db=db
            ),
            **normalized_review,
            "reviewed_by": actor_id,
            "reviewed_by_name": actor_name,
            "input_digest": hashlib.sha256(
                cls._canonical(
                    {
                        "batch_id": command["batch_id"],
                        "user_id": command["user_id"],
                        "review": normalized_review,
                    }
                ).encode("utf-8")
            ).hexdigest(),
            "idempotency_key": command["idempotency_key"],
        }
        review_id = PerformanceLedgerRepository.insert_review(review_payload, db)

        changed_results = []
        for result in results:
            user_id = int(result["user_id"])
            previous = latest_by_user.get(user_id)
            force_target = user_id == command["user_id"]
            if force_target or cls._score_revision_changed(previous, result):
                changed_results.append(result)

        changed_results.sort(key=lambda item: int(item["user_id"]))
        inserted_score_ids = []
        for result in changed_results:
            user_id = int(result["user_id"])
            previous = latest_by_user.get(user_id)
            score_payload = cls._score_payload(
                command["batch_id"],
                result,
                actor_id,
                actor_name,
                revision=(int(previous["revision"]) + 1 if previous else 1),
                review_revision_id=(
                    review_id
                    if user_id == command["user_id"]
                    else (previous.get("review_revision_id") if previous else None)
                ),
                review=review_by_user.get(user_id),
            )
            inserted_score_ids.append(
                PerformanceLedgerRepository.insert_score_revision(score_payload, db)
            )

        new_row_version = PerformanceLedgerRepository.update_batch_row_version(
            command["batch_id"], command["expected_row_version"], db
        )
        if new_row_version is None:
            raise ConflictError("绩效批次版本号已被其他操作修改，请刷新后重试")
        changed_user_ids = [int(item["user_id"]) for item in changed_results]
        event_id = PerformanceLedgerRepository.insert_batch_event(
            {
                "batch_id": command["batch_id"],
                "event_type": "supervisor_review_saved",
                "from_status": "supervisor_review",
                "to_status": "supervisor_review",
                "operator_id": actor_id,
                "operator_name": actor_name,
                "reason": command["reason"],
                "payload_json": cls._canonical(
                    {
                        "review_id": review_id,
                        "review_revision": review_payload["revision"],
                        "user_id": command["user_id"],
                        "changed_user_ids": changed_user_ids,
                        "score_revision_ids": inserted_score_ids,
                    }
                ),
                "request_id": command["request_id"],
                "idempotency_key": "performance-supervisor-review:"
                + command["idempotency_key"],
            },
            db,
        )
        result = PerformanceLedgerRepository.batch_summary(
            command["batch_id"], db=db
        )
        result.update(
            {
                "review_id": review_id,
                "review_revision": review_payload["revision"],
                "changed_user_ids": changed_user_ids,
                "event_id": event_id,
                "idempotent_replay": False,
            }
        )
        return result

    @staticmethod
    def _pagination(page, per_page, default=20):
        try:
            page = max(int(page or 1), 1)
            per_page = min(max(int(per_page or default), 1), 200)
        except (TypeError, ValueError) as exc:
            raise ValueError("绩效分页参数无效") from exc
        return page, per_page

    @classmethod
    def require_visible_batch(cls, batch_id, actor, db=None):
        batch = cls._require_batch(batch_id, db)
        scope = PerformanceAuthorizationService.require_workflow_view_access(
            actor, db=db
        )
        if not PerformanceLedgerRepository.batch_is_visible(
            batch_id, scope, db=db
        ):
            raise PermissionError("无权查看该绩效批次")
        return batch, scope

    @classmethod
    def _allowed_batch_actions(cls, batch, actor):
        """Project workflow actions without duplicating command authorization in UI."""
        actions = []
        actor_id = (actor or {}).get("id")
        try:
            actor_id = int(actor_id) if actor_id is not None else None
        except (TypeError, ValueError):
            actor_id = None
        status = batch.get("status")
        owns_batch = actor_id is not None and actor_id == batch.get("prepared_by")
        can_prepare = PerformanceAuthorizationService.can_perform(actor, "prepare")
        can_approve = PerformanceAuthorizationService.can_perform(actor, "approve")
        can_view_all = PerformanceAuthorizationService.can_perform(actor, "view_all")

        if can_prepare and owns_batch:
            if status == BATCH_STATUS_DRAFT:
                actions.extend(("submit_supervisor_review", "cancel"))
            elif status == BATCH_STATUS_SUPERVISOR_REVIEW:
                actions.extend(("submit_approval", "return", "cancel"))
        if can_prepare and status == BATCH_STATUS_APPROVED:
            actions.append("create_revision")
        if (
            can_approve
            and can_view_all
            and actor_id is not None
            and actor_id != batch.get("prepared_by")
            and status == BATCH_STATUS_APPROVAL_PENDING
        ):
            actions.extend(("approve", "return"))
        if (
            status == BATCH_STATUS_SUPERVISOR_REVIEW
            and PerformanceAuthorizationService.can_perform(
                actor, "review_department"
            )
        ):
            actions.append("review_member")
        return actions

    @classmethod
    def list_batches(
        cls,
        actor,
        production_month="",
        status="",
        page=1,
        per_page=20,
        db=None,
    ):
        if production_month:
            production_month = validate_production_month(production_month)
        allowed_statuses = {
            "",
            BATCH_STATUS_DRAFT,
            BATCH_STATUS_SUPERVISOR_REVIEW,
            BATCH_STATUS_APPROVAL_PENDING,
            BATCH_STATUS_APPROVED,
            BATCH_STATUS_SUPERSEDED,
            BATCH_STATUS_CANCELLED,
        }
        if status not in allowed_statuses:
            raise ValueError("绩效批次状态无效")
        page, per_page = cls._pagination(page, per_page)
        scope = PerformanceAuthorizationService.require_workflow_view_access(
            actor, db=db
        )
        result = PerformanceLedgerRepository.list_batches(
            scope,
            production_month=production_month,
            status=status,
            page=page,
            limit=per_page,
            db=db,
        )
        for item in result["items"]:
            item["allowed_actions"] = cls._allowed_batch_actions(item, actor)
        return result

    @classmethod
    def batch_detail(cls, batch_id, actor, page=1, per_page=50, db=None):
        page, per_page = cls._pagination(page, per_page, default=50)
        _, scope = cls.require_visible_batch(batch_id, actor, db=db)
        result = PerformanceLedgerRepository.batch_summary(batch_id, db=db)
        scores = PerformanceAuthorizationService.list_visible_scores(
            actor,
            batch_id=batch_id,
            page=page,
            limit=per_page,
            db=db,
        )
        events = (
            PerformanceLedgerRepository.list_batch_events(batch_id, db=db)
            if any(
                PerformanceAuthorizationService.can_perform(actor, action)
                for action in ("prepare", "approve", "review_department")
            )
            else []
        )
        for event in events:
            event["payload"] = cls._json_object(event.get("payload_json"))
        allowed_actions = cls._allowed_batch_actions(result["batch"], actor)
        if "review_member" in allowed_actions:
            for score in scores["items"]:
                score["allowed_actions"] = (
                    ["review"]
                    if PerformanceAuthorizationService.can_review_member(
                        actor, batch_id, score["user_id"], db=db
                    )
                    else []
                )
        else:
            for score in scores["items"]:
                score["allowed_actions"] = []
        result.update(
            {
                "scores": scores["items"],
                "scores_total": scores["total"],
                "page": page,
                "per_page": per_page,
                "events": events,
                "visible_scope": scope,
                "allowed_actions": allowed_actions,
            }
        )
        return result

    @classmethod
    def list_exceptions(
        cls,
        batch_id,
        actor,
        status="",
        page=1,
        per_page=50,
        db=None,
    ):
        if status not in ("", "pending", "resolved", "confirmed_insufficient", "excluded"):
            raise ValueError("绩效异常状态无效")
        page, per_page = cls._pagination(page, per_page, default=50)
        _, scope = cls.require_visible_batch(batch_id, actor, db=db)
        result = PerformanceLedgerRepository.list_exceptions(
            scope,
            batch_id,
            status=status,
            page=page,
            limit=per_page,
            db=db,
        )
        for item in result["items"]:
            item["snapshot"] = cls._json_object(item.get("snapshot_json"))
        return result

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
