"""Batch lifecycle and dual-control workflow for the performance ledger."""

from modules.domain.errors import ConflictError, NotFoundError
from modules.domain.performance_policy import (
    BATCH_STATUS_APPROVAL_PENDING,
    BATCH_STATUS_APPROVED,
    BATCH_STATUS_CANCELLED,
    BATCH_STATUS_DRAFT,
    BATCH_STATUS_SUPERSEDED,
    BATCH_STATUS_SUPERVISOR_REVIEW,
    ELIGIBILITY_ELIGIBLE,
)
from modules.repositories.performance_ledger_repository import (
    PerformanceLedgerRepository,
)
from modules.services import BaseService
from modules.services.performance_authorization_service import (
    PerformanceAuthorizationService,
)
from modules.services.performance_fact_collector import PerformanceFactCollector


class PerformanceLedgerWorkflowMixin:
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
