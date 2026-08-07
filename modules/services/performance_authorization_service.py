"""Performance action authorization and historical department scopes."""

import json

from modules.access_policy import has_permission_code
from modules.domain.errors import NotFoundError, ValidationError
from modules.repositories.performance_authorization_repository import (
    PerformanceAuthorizationRepository,
)
from modules.services import BaseService
from modules.services.access_policy_service import AccessPolicyService


class PerformanceAuthorizationService:
    ACTIONS = {
        "view_self",
        "view_department",
        "view_all",
        "review_department",
        "prepare",
        "approve",
        "plan_manage",
        "plan_reassess",
    }

    @staticmethod
    def _permissions(actor):
        return AccessPolicyService.get_user_permissions(actor or {})

    @staticmethod
    def _actor_id(actor):
        actor_id = (actor or {}).get("id")
        if actor_id is None:
            raise PermissionError("Authenticated performance actor is required")
        return int(actor_id)

    @staticmethod
    def can_perform(actor, action):
        if action not in PerformanceAuthorizationService.ACTIONS:
            return False
        return has_permission_code(
            PerformanceAuthorizationService._permissions(actor),
            "performance:" + action,
        )

    @staticmethod
    def resolve_view_scope(actor, db=None):
        actor_id = PerformanceAuthorizationService._actor_id(actor)
        permissions = PerformanceAuthorizationService._permissions(actor)
        if has_permission_code(permissions, "performance:view_all"):
            return {"all": True, "self_user_id": None, "department_ids": []}

        self_user_id = (
            actor_id
            if has_permission_code(permissions, "performance:view_self")
            else None
        )
        department_ids = []
        if has_permission_code(permissions, "performance:view_department"):
            department_ids = [
                row["id"]
                for row in PerformanceAuthorizationRepository.list_department_scopes(
                    actor_id, db=db
                )
            ]
        return {
            "all": False,
            "self_user_id": self_user_id,
            "department_ids": sorted(set(department_ids)),
        }

    @staticmethod
    def list_visible_scores(
        actor,
        batch_id=None,
        user_id=None,
        department_id=None,
        warning_level="",
        search="",
        position_id="",
        page=1,
        limit=20,
        db=None,
    ):
        page = max(int(page or 1), 1)
        limit = min(max(int(limit or 20), 1), 200)
        scope = PerformanceAuthorizationService.resolve_view_scope(actor, db=db)
        return PerformanceAuthorizationRepository.list_score_revisions(
            scope,
            batch_id=batch_id,
            user_id=user_id,
            department_id=department_id,
            warning_level=warning_level,
            search=search,
            position_id=position_id,
            page=page,
            limit=limit,
            db=db,
        )

    @staticmethod
    def require_view_access(actor, db=None):
        scope = PerformanceAuthorizationService.resolve_view_scope(actor, db=db)
        if not scope["all"] and scope["self_user_id"] is None and not scope["department_ids"]:
            raise PermissionError("无绩效结果查看权限")
        return scope

    @staticmethod
    def require_workflow_view_access(actor, db=None):
        if not any(
            PerformanceAuthorizationService.can_perform(actor, action)
            for action in ("view_all", "review_department", "prepare", "approve")
        ):
            raise PermissionError("无绩效批次工作流查看权限")
        return PerformanceAuthorizationService.require_view_access(actor, db=db)

    @staticmethod
    def require_visible_filters(
        actor, batch_id, user_id=None, department_id=None, db=None
    ):
        scope = PerformanceAuthorizationService.require_view_access(actor, db=db)
        if department_id is not None:
            if not PerformanceAuthorizationRepository.department_exists(
                department_id, db=db
            ):
                raise NotFoundError("绩效部门不存在")
            if not scope["all"] and department_id not in scope["department_ids"]:
                raise PermissionError("无权查看该部门绩效")
        if user_id is not None:
            if not PerformanceAuthorizationRepository.user_exists(user_id, db=db):
                raise NotFoundError("绩效员工不存在")
            allowed = scope["all"] or user_id == scope["self_user_id"]
            member = PerformanceAuthorizationRepository.latest_score_member(
                batch_id, user_id, db=db
            )
            if member and member.get("department_id_snapshot") in scope["department_ids"]:
                allowed = True
            if not allowed:
                raise PermissionError("无权查看该员工绩效")
        return scope

    @staticmethod
    def can_review_member(actor, batch_id, user_id, db=None):
        permissions = PerformanceAuthorizationService._permissions(actor)
        if not has_permission_code(permissions, "performance:review_department"):
            return False
        if "*" in permissions:
            return True
        actor_id = PerformanceAuthorizationService._actor_id(actor)
        department_ids = {
            row["id"]
            for row in PerformanceAuthorizationRepository.list_department_scopes(
                actor_id, db=db
            )
        }
        member = PerformanceAuthorizationRepository.latest_score_member(
            batch_id, user_id, db=db
        )
        return bool(
            member
            and member.get("department_id_snapshot") is not None
            and member["department_id_snapshot"] in department_ids
        )

    @staticmethod
    def require_distinct_actors(first_actor_id, second_actor_id):
        if first_actor_id is not None and first_actor_id == second_actor_id:
            raise ValueError("Performance duty actors must differ")
        return True

    @staticmethod
    def _require_scope_admin(actor):
        if not has_permission_code(
            PerformanceAuthorizationService._permissions(actor), "users:admin"
        ):
            raise PermissionError("users:admin permission is required")
        return PerformanceAuthorizationService._actor_id(actor)

    @staticmethod
    def get_department_scopes(user_id, actor, db=None):
        PerformanceAuthorizationService._require_scope_admin(actor)
        if not PerformanceAuthorizationRepository.user_exists(user_id, db=db):
            raise NotFoundError("Performance scope user not found")
        departments = PerformanceAuthorizationRepository.list_department_scopes(
            user_id, db=db
        )
        return {
            "user_id": user_id,
            "department_ids": [row["id"] for row in departments],
            "departments": departments,
        }

    @staticmethod
    def replace_department_scopes(user_id, department_ids, actor, db=None):
        actor_id = PerformanceAuthorizationService._require_scope_admin(actor)
        if not isinstance(department_ids, list):
            raise ValidationError("department_ids must be a list")
        try:
            normalized = sorted({int(value) for value in department_ids})
        except (TypeError, ValueError):
            raise ValidationError("department_ids must contain integers") from None
        if any(value <= 0 for value in normalized):
            raise ValidationError("department_ids must contain positive integers")

        with BaseService.transaction() as txn:
            if not PerformanceAuthorizationRepository.user_exists(user_id, db=txn):
                raise NotFoundError("Performance scope user not found")
            existing = PerformanceAuthorizationRepository.existing_department_ids(
                normalized, db=txn
            )
            missing = sorted(set(normalized) - existing)
            if missing:
                raise NotFoundError(
                    "Performance scope department not found: "
                    + ", ".join(str(value) for value in missing)
                )
            actor_name = str(
                (actor or {}).get("name") or (actor or {}).get("username") or ""
            )
            PerformanceAuthorizationRepository.replace_department_scopes(
                user_id, normalized, actor_id, actor_name, db=txn
            )
            PerformanceAuthorizationRepository.insert_scope_audit(
                actor_id,
                user_id,
                json.dumps(
                    {"department_ids": normalized},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                db=txn,
            )
        return PerformanceAuthorizationService.get_department_scopes(
            user_id, actor, db=db
        )
