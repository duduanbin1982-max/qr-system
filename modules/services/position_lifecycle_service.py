"""Two-person retirement and reactivation workflow for position roots."""

from datetime import datetime

from modules.domain.actor_context import ActorContextParseError, parse_actor_context
from modules.domain.errors import ConflictError, ValidationError
from modules.domain.position_versioning import (
    PositionActiveEmployeesError,
    PositionActiveSessionsError,
    PositionNotFoundError,
    PositionReferenceConflictError,
    PositionVersionNotFoundError,
    assert_impact_digest,
    assert_row_version,
    assert_separation_of_duties,
    require_row_version,
    validate_transition,
)
from modules.repositories.position_version_repository import PositionVersionRepository
from modules.services import BaseService
from modules.services.position_audit_service import PositionAuditService
from modules.services.position_impact_service import PositionImpactService


class PositionLifecycleService:
    @staticmethod
    def _now():
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _actor(actor):
        try:
            return parse_actor_context(actor).to_legacy_mapping()
        except ActorContextParseError as exc:
            raise ValidationError("操作人不能为空") from exc

    @staticmethod
    def _required_text(command, field, label):
        value = str((command or {}).get(field) or "").strip()
        if not value:
            raise ValidationError(f"{label}不能为空")
        return value

    @staticmethod
    def _reason(command, label="生命周期原因"):
        source = command or {}
        value = str(source.get("lifecycle_reason") or source.get("reason") or "").strip()
        if not value:
            raise ValidationError(f"{label}不能为空")
        return value

    @staticmethod
    def _idempotency_key(command):
        return PositionLifecycleService._required_text(
            command, "idempotency_key", "幂等键"
        )

    @staticmethod
    def _root(position_id, db):
        root = PositionVersionRepository.root(position_id, db=db)
        if not root:
            raise PositionNotFoundError("岗位不存在")
        return root

    @staticmethod
    def _request(request_id, db):
        request = PositionVersionRepository.lifecycle_request(request_id, db=db)
        if not request:
            raise PositionVersionNotFoundError("岗位生命周期申请不存在")
        return request

    @staticmethod
    def _assert_request_replay(replay, position_id, action):
        if (
            int(replay["position_id"]) != int(position_id)
            or replay["action"] != action
        ):
            raise ConflictError("幂等键已被其他岗位生命周期申请使用")
        return replay

    @staticmethod
    def _reactivation_version(position_id, root, db):
        if root.get("lifecycle_status") != "retired":
            raise PositionReferenceConflictError("只有已退休岗位可以重新启用")
        current = PositionVersionRepository.current_version(position_id, db=db)
        retired_versions = [
            version
            for version in PositionVersionRepository.list_versions(position_id, db=db)
            if version.get("status") == "retired"
        ]
        last_retired = max(
            retired_versions,
            key=lambda version: (int(version["version"]), int(version["id"])),
            default=None,
        )
        if (
            current is None
            or current.get("status") != "published"
            or last_retired is None
            or int(current["version"]) <= int(last_retired["version"])
            or int(current.get("supersedes_version_id") or 0)
            != int(last_retired["id"])
            or not current.get("published_at")
            or (
                root.get("retired_at")
                and current["published_at"] < root["retired_at"]
            )
        ):
            raise PositionReferenceConflictError(
                "重新启用前必须先创建并批准退休后的新岗位修订版"
            )
        return current

    @staticmethod
    def _request_lifecycle(position_id, action, command, actor_user):
        actor = PositionLifecycleService._actor(actor_user)
        key = PositionLifecycleService._idempotency_key(command)
        reason = PositionLifecycleService._reason(command)
        with BaseService.transaction() as db:
            replay = PositionVersionRepository.lifecycle_request_by_idempotency_key(
                key, db=db
            )
            if replay:
                return PositionLifecycleService._assert_request_replay(
                    replay, position_id, action
                )
            root = PositionLifecycleService._root(position_id, db)
            assert_row_version(
                require_row_version((command or {}).get("row_version")),
                root["row_version"],
            )
            current = PositionVersionRepository.current_version(position_id, db=db)
            if action == "retire":
                if root.get("lifecycle_status") != "active":
                    raise PositionReferenceConflictError("岗位已经退休")
                if current is None or current.get("status") != "published":
                    raise PositionReferenceConflictError("岗位尚无已发布版本，不能退休")
            else:
                PositionLifecycleService._reactivation_version(position_id, root, db)
            impact = PositionImpactService.summarize(position_id, db=db)
            return PositionVersionRepository.create_lifecycle_request(
                {
                    "position_id": int(position_id),
                    "action": action,
                    "reason": reason,
                    "impact_digest": impact["impact_digest"],
                    "requested_by": actor["id"],
                    "requested_by_name": actor["name"],
                    "idempotency_key": key,
                },
                db,
            )

    @staticmethod
    def request_retirement(position_id, command, actor_user, request_id=""):
        del request_id
        return PositionLifecycleService._request_lifecycle(
            position_id, "retire", command, actor_user
        )

    @staticmethod
    def request_reactivation(position_id, command, actor_user, request_id=""):
        del request_id
        return PositionLifecycleService._request_lifecycle(
            position_id, "reactivate", command, actor_user
        )

    @staticmethod
    def _approval_replay(key, request_id, db):
        event = PositionVersionRepository.event_by_idempotency_key(key, db=db)
        if not event:
            return None
        payload = event.get("payload") or {}
        if int(payload.get("lifecycle_request_id") or 0) != int(request_id):
            raise ConflictError("幂等键已被其他岗位命令使用")
        return PositionLifecycleService._request(request_id, db)

    @staticmethod
    def _assert_retirement_blockers(impact, position_id):
        counts = {
            item["key"]: int(item["count"])
            for item in impact.get("categories", [])
        }
        if counts.get("active_employees", 0):
            raise PositionActiveEmployeesError(
                "岗位仍有启用员工，请先完成调岗",
                details={
                    "position_id": int(position_id),
                    "count": counts["active_employees"],
                },
            )
        if counts.get("active_sessions", 0):
            raise PositionActiveSessionsError(
                "岗位仍有活跃会话，请先失效会话",
                details={
                    "position_id": int(position_id),
                    "count": counts["active_sessions"],
                },
            )

    @staticmethod
    def _event(version, event_type, request, actor, key, db):
        return PositionVersionRepository.create_event(
            {
                "position_id": request["position_id"],
                "position_version_id": version["id"],
                "event_type": event_type,
                "from_status": (
                    "active" if event_type == "retired" else "retired"
                ),
                "to_status": (
                    "retired" if event_type == "retired" else "active"
                ),
                "actor_id": actor["id"],
                "actor_name": actor["name"],
                "actor_role": actor["role"],
                "reason": request["reason"],
                "impact_digest": request.get("impact_digest", ""),
                "idempotency_key": key,
                "payload": {"lifecycle_request_id": request["id"]},
            },
            db,
        )

    @staticmethod
    def approve_request(lifecycle_request_id, command, actor_user, request_id=""):
        actor = PositionLifecycleService._actor(actor_user)
        key = PositionLifecycleService._idempotency_key(command)
        expected = require_row_version((command or {}).get("row_version"))
        with BaseService.transaction() as db:
            replay = PositionLifecycleService._approval_replay(
                key, lifecycle_request_id, db
            )
            if replay:
                return replay
            lifecycle = PositionLifecycleService._request(lifecycle_request_id, db)
            if lifecycle["status"] != "pending":
                raise PositionReferenceConflictError("岗位生命周期申请已处理")
            assert_separation_of_duties(lifecycle["requested_by"], actor["id"])
            root = PositionLifecycleService._root(lifecycle["position_id"], db)
            impact = PositionImpactService.summarize(
                lifecycle["position_id"], db=db
            )
            assert_impact_digest(
                lifecycle.get("impact_digest", ""), impact["impact_digest"]
            )
            now = PositionLifecycleService._now()
            if lifecycle["action"] == "retire":
                if root.get("lifecycle_status") != "active":
                    raise PositionReferenceConflictError("岗位已经退休")
                PositionLifecycleService._assert_retirement_blockers(
                    impact, lifecycle["position_id"]
                )
                before = PositionVersionRepository.current_version(
                    lifecycle["position_id"], db=db
                )
                if before is None or before.get("status") != "published":
                    raise PositionReferenceConflictError("岗位当前版本不能退休")
                validate_transition(before["status"], "retired")
                version = PositionVersionRepository.transition_version(
                    before["id"],
                    "published",
                    before["row_version"],
                    "retired",
                    {"effective_to": now},
                    db,
                )
                root_after = PositionVersionRepository.update_root_lifecycle(
                    lifecycle["position_id"],
                    root["row_version"],
                    "retired",
                    retired_at=now,
                    db=db,
                )
                event_type = "retired"
                audit_action = "position_retired"
            else:
                before = PositionLifecycleService._reactivation_version(
                    lifecycle["position_id"], root, db
                )
                version = before
                root_after = PositionVersionRepository.update_root_lifecycle(
                    lifecycle["position_id"],
                    root["row_version"],
                    "active",
                    retired_at="",
                    db=db,
                )
                event_type = "reactivated"
                audit_action = "position_reactivated"
            resolved = PositionVersionRepository.transition_lifecycle_request(
                lifecycle["id"],
                "pending",
                expected,
                "approved",
                {
                    "approved_by": actor["id"],
                    "approved_by_name": actor["name"],
                    "resolved_at": now,
                    "impact_digest": impact["impact_digest"],
                },
                db,
            )
            PositionLifecycleService._event(
                version, event_type, lifecycle, actor, key, db
            )
            PositionAuditService.record(
                db,
                action=audit_action,
                actor=actor,
                request_id=request_id,
                idempotency_key=key,
                position_id=lifecycle["position_id"],
                position_version_id=version["id"],
                before=before,
                after=version,
                reason=lifecycle["reason"],
                impact_digest=impact["impact_digest"],
            )
            result = dict(resolved)
            result["position"] = root_after
            result["position_version"] = version
            return result

    @staticmethod
    def reject_request(lifecycle_request_id, command, actor_user, request_id=""):
        actor = PositionLifecycleService._actor(actor_user)
        key = PositionLifecycleService._idempotency_key(command)
        reason = PositionLifecycleService._reason(command, "驳回原因")
        expected = require_row_version((command or {}).get("row_version"))
        with BaseService.transaction() as db:
            replay = PositionLifecycleService._approval_replay(
                key, lifecycle_request_id, db
            )
            if replay:
                return replay
            lifecycle = PositionLifecycleService._request(lifecycle_request_id, db)
            if lifecycle["status"] != "pending":
                raise PositionReferenceConflictError("岗位生命周期申请已处理")
            assert_separation_of_duties(lifecycle["requested_by"], actor["id"])
            current = PositionVersionRepository.current_version(
                lifecycle["position_id"], db=db
            )
            if current is None:
                raise PositionReferenceConflictError("岗位没有可审计的当前版本")
            resolved = PositionVersionRepository.transition_lifecycle_request(
                lifecycle["id"],
                "pending",
                expected,
                "rejected",
                {
                    "approved_by": actor["id"],
                    "approved_by_name": actor["name"],
                    "resolved_at": PositionLifecycleService._now(),
                },
                db,
            )
            PositionVersionRepository.create_event(
                {
                    "position_id": lifecycle["position_id"],
                    "position_version_id": current["id"],
                    "event_type": "lifecycle_request_rejected",
                    "from_status": "pending",
                    "to_status": "rejected",
                    "actor_id": actor["id"],
                    "actor_name": actor["name"],
                    "actor_role": actor["role"],
                    "reason": reason,
                    "impact_digest": lifecycle.get("impact_digest", ""),
                    "idempotency_key": key,
                    "payload": {"lifecycle_request_id": lifecycle["id"]},
                },
                db,
            )
            PositionAuditService.record(
                db,
                action="position_lifecycle_rejected",
                actor=actor,
                request_id=request_id,
                idempotency_key=key,
                position_id=lifecycle["position_id"],
                position_version_id=current["id"],
                before=current,
                after=current,
                reason=reason,
                impact_digest=lifecycle.get("impact_digest", ""),
            )
            return resolved

    @staticmethod
    def list_requests(position_id):
        with BaseService.transaction() as db:
            PositionLifecycleService._root(position_id, db)
            return PositionVersionRepository.list_lifecycle_requests(
                position_id, db=db
            )
