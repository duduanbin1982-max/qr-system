"""Supervisor review and atomic ranking recalculation for performance batches."""

import hashlib

from modules.domain.errors import ConflictError, NotFoundError
from modules.repositories.performance_configuration_repository import (
    PerformanceConfigurationRepository,
)
from modules.repositories.performance_fact_repository import PerformanceFactRepository
from modules.repositories.performance_ledger_repository import (
    PerformanceLedgerRepository,
)
from modules.services import BaseService
from modules.services.performance_authorization_service import (
    PerformanceAuthorizationService,
)
from modules.services.performance_scoring_policy import PerformanceScoringPolicy


class PerformanceLedgerReviewMixin:
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
