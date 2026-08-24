"""Visibility-scoped query projections for the performance ledger."""

from modules.domain.performance_policy import (
    BATCH_STATUS_APPROVAL_PENDING,
    BATCH_STATUS_APPROVED,
    BATCH_STATUS_CANCELLED,
    BATCH_STATUS_DRAFT,
    BATCH_STATUS_SUPERSEDED,
    BATCH_STATUS_SUPERVISOR_REVIEW,
    validate_production_month,
)
from modules.repositories.performance_ledger_repository import (
    PerformanceLedgerRepository,
)
from modules.services.performance_authorization_service import (
    PerformanceAuthorizationService,
)


class PerformanceLedgerQueryMixin:
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
