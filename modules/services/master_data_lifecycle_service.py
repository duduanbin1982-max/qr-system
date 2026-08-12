"""Two-person retirement and reactivation workflows for master-data roots."""

from datetime import datetime

from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.domain.process_versioning import assert_separation_of_duties, require_row_version
from modules.repositories.master_data_lifecycle_repository import (
    MasterDataLifecycleRepository,
)
from modules.repositories.process_version_repository import ProcessVersionRepository
from modules.repositories.route_version_repository import RouteVersionRepository
from modules.services import BaseService


class MasterDataLifecycleService:
    @staticmethod
    def _actor(actor):
        actor = actor or {}
        try:
            actor_id = int(actor.get("id"))
        except (TypeError, ValueError) as exc:
            raise ValidationError("操作人不能为空") from exc
        if actor_id <= 0:
            raise ValidationError("操作人不能为空")
        return {
            "id": actor_id,
            "name": str(actor.get("name") or actor.get("username") or "").strip(),
            "role": str(actor.get("role") or "").strip(),
        }

    @staticmethod
    def _action(action):
        action = str(action or "").strip().lower()
        if action not in {"retire", "reactivate"}:
            raise ValidationError("生命周期动作必须是 retire 或 reactivate")
        return action

    @staticmethod
    def _reason(command):
        reason = str((command or {}).get("reason") or "").strip()
        if not reason:
            raise ValidationError("生命周期原因不能为空")
        return reason

    @staticmethod
    def _key(command):
        key = str((command or {}).get("idempotency_key") or "").strip()
        if not key:
            raise ValidationError("幂等键不能为空")
        return key

    @staticmethod
    def request_process(process_id, action, command, actor_user):
        actor = MasterDataLifecycleService._actor(actor_user)
        action = MasterDataLifecycleService._action(action)
        reason = MasterDataLifecycleService._reason(command)
        key = MasterDataLifecycleService._key(command)
        with BaseService.transaction() as db:
            replay = MasterDataLifecycleRepository.process_request_by_idempotency_key(
                key, db=db
            )
            if replay is not None:
                return replay
            root = ProcessVersionRepository.root(process_id, db=db)
            if root is None:
                raise NotFoundError("工序不存在")
            if action == "retire" and root["lifecycle_status"] != "active":
                raise ConflictError("工序已经退休")
            if action == "reactivate":
                current = ProcessVersionRepository.current_version(process_id, db=db)
                if root["lifecycle_status"] != "retired":
                    raise ConflictError("只有已退休工序可以重新启用")
                if current is None or current["status"] != "published" or int(current["version"]) <= 1:
                    raise ConflictError("重新启用前必须先发布新修订版")
            return MasterDataLifecycleRepository.create_process_request(
                process_id,
                {
                    "action": action,
                    "reason": reason,
                    "requested_by": actor["id"],
                    "requested_by_name": actor["name"],
                    "idempotency_key": key,
                },
                db,
            )

    @staticmethod
    def approve_process(request_id, command, actor_user):
        actor = MasterDataLifecycleService._actor(actor_user)
        with BaseService.transaction() as db:
            request = MasterDataLifecycleRepository.process_request(request_id, db=db)
            if request is None:
                raise NotFoundError("工序生命周期申请不存在")
            if request["status"] != "pending":
                return request
            assert_separation_of_duties(
                request["requested_by"], actor["id"], entity_type="process"
            )
            root = ProcessVersionRepository.root(request["process_id"], db=db)
            if root is None:
                raise NotFoundError("工序不存在")
            expected = require_row_version(command.get("row_version", request["row_version"]))
            if request["action"] == "retire":
                current = ProcessVersionRepository.current_version(request["process_id"], db=db)
                if current is not None and current["status"] == "published":
                    current = ProcessVersionRepository.transition_version(
                        current["id"], "published", current["row_version"], "retired",
                        {"effective_to": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, db
                    )
                ProcessVersionRepository.transition_root_lifecycle(
                    request["process_id"], "active", root["row_version"],
                    "retired", "inactive", db
                )
            else:
                current = ProcessVersionRepository.current_version(request["process_id"], db=db)
                if root["lifecycle_status"] != "retired" or current is None or current["status"] != "published" or int(current["version"]) <= 1:
                    raise ConflictError("重新启用前必须先发布新修订版")
                ProcessVersionRepository.transition_root_lifecycle(
                    request["process_id"], "retired", root["row_version"],
                    "active", "active", db
                )
            resolved = MasterDataLifecycleRepository.transition_process_request(
                request_id, "pending", expected, "approved",
                {
                    "approved_by": actor["id"],
                    "approved_by_name": actor["name"],
                    "resolved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }, db
            )
            ProcessVersionRepository.insert_event(
                {
                    "entity_id": request["process_id"],
                    "version_id": current["id"],
                    "event_type": "retired" if request["action"] == "retire" else "reactivated",
                    "actor_id": actor["id"],
                    "actor_name": actor["name"],
                    "actor_role": actor["role"],
                    "reason": request["reason"],
                    "idempotency_key": request["idempotency_key"],
                    "from_status": "active" if request["action"] == "retire" else "retired",
                    "to_status": "retired" if request["action"] == "retire" else "active",
                    "payload": {"lifecycle_request_id": request_id},
                },
                db,
            )
            return resolved

    @staticmethod
    def request_route(route_id, action, command, actor_user):
        actor = MasterDataLifecycleService._actor(actor_user)
        action = MasterDataLifecycleService._action(action)
        reason = MasterDataLifecycleService._reason(command)
        key = MasterDataLifecycleService._key(command)
        with BaseService.transaction() as db:
            replay = MasterDataLifecycleRepository.route_request_by_idempotency_key(
                key, db=db
            )
            if replay is not None:
                return replay
            root = RouteVersionRepository.root(route_id, db=db)
            if root is None:
                raise NotFoundError("路线不存在")
            if action == "retire" and root["lifecycle_status"] != "active":
                raise ConflictError("路线已经退休")
            if action == "reactivate":
                current = RouteVersionRepository.current_version(route_id, db=db)
                if root["lifecycle_status"] != "retired" or current is None or current["status"] != "published" or int(current["version"]) <= 1:
                    raise ConflictError("重新启用前必须先发布新修订版")
            return MasterDataLifecycleRepository.create_route_request(
                route_id,
                {
                    "action": action,
                    "reason": reason,
                    "requested_by": actor["id"],
                    "requested_by_name": actor["name"],
                    "idempotency_key": key,
                }, db
            )

    @staticmethod
    def approve_route(request_id, command, actor_user):
        actor = MasterDataLifecycleService._actor(actor_user)
        with BaseService.transaction() as db:
            request = MasterDataLifecycleRepository.route_request(request_id, db=db)
            if request is None:
                raise NotFoundError("路线生命周期申请不存在")
            if request["status"] != "pending":
                return request
            assert_separation_of_duties(request["requested_by"], actor["id"], entity_type="route")
            root = RouteVersionRepository.root(request["process_route_id"], db=db)
            if root is None:
                raise NotFoundError("路线不存在")
            expected = require_row_version(command.get("row_version", request["row_version"]))
            if request["action"] == "retire":
                current = RouteVersionRepository.current_version(request["process_route_id"], db=db)
                if current is not None and current["status"] == "published":
                    current = RouteVersionRepository.transition_version(
                        current["id"], "published", current["row_version"], "retired",
                        {"effective_to": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}, db
                    )
                RouteVersionRepository.transition_root_lifecycle(
                    request["process_route_id"], "active", root["row_version"],
                    "retired", "inactive", db
                )
            else:
                current = RouteVersionRepository.current_version(request["process_route_id"], db=db)
                if root["lifecycle_status"] != "retired" or current is None or current["status"] != "published" or int(current["version"]) <= 1:
                    raise ConflictError("重新启用前必须先发布新修订版")
                RouteVersionRepository.transition_root_lifecycle(
                    request["process_route_id"], "retired", root["row_version"],
                    "active", "active", db
                )
            resolved = MasterDataLifecycleRepository.transition_route_request(
                request_id, "pending", expected, "approved",
                {
                    "approved_by": actor["id"],
                    "approved_by_name": actor["name"],
                    "resolved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }, db
            )
            RouteVersionRepository.insert_event(
                {
                    "entity_id": request["process_route_id"],
                    "version_id": current["id"],
                    "event_type": "retired" if request["action"] == "retire" else "reactivated",
                    "actor_id": actor["id"],
                    "actor_name": actor["name"],
                    "actor_role": actor["role"],
                    "reason": request["reason"],
                    "idempotency_key": request["idempotency_key"],
                    "from_status": "active" if request["action"] == "retire" else "retired",
                    "to_status": "retired" if request["action"] == "retire" else "active",
                    "payload": {"lifecycle_request_id": request_id},
                },
                db,
            )
            return resolved
