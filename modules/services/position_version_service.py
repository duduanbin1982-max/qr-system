"""Transactional workflow for stable position roots and immutable revisions."""

from datetime import datetime

from modules.domain.errors import ConflictError, ValidationError
from modules.domain.position_versioning import (
    PositionNotFoundError,
    PositionProcessInvalidError,
    PositionReferenceConflictError,
    PositionVersionAlreadyOpenError,
    PositionVersionNotFoundError,
    assert_impact_digest,
    assert_root_identity_preserved,
    assert_row_version,
    assert_separation_of_duties,
    content_digest,
    copy_revision_content,
    normalize_position_content,
    require_row_version,
    validate_transition,
)
from modules.repositories.position_repository import PositionRepository
from modules.repositories.position_version_repository import PositionVersionRepository
from modules.repositories.process_version_repository import ProcessVersionRepository
from modules.services import BaseService
from modules.services.position_audit_service import PositionAuditService
from modules.services.position_impact_service import PositionImpactService
from modules.services.position_snapshot_service import PositionSnapshotService


class PositionVersionService:
    EDITABLE_FIELDS = ("name", "description", "process_ids")

    @staticmethod
    def _now():
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _actor(actor):
        source = actor or {}
        try:
            actor_id = int(source.get("id"))
        except (TypeError, ValueError) as exc:
            raise ValidationError("操作人不能为空") from exc
        if actor_id <= 0:
            raise ValidationError("操作人不能为空")
        return {
            "id": actor_id,
            "name": str(source.get("name") or source.get("username") or "").strip(),
            "role": str(source.get("role") or "").strip(),
        }

    @staticmethod
    def _required_text(command, field, label):
        value = str((command or {}).get(field) or "").strip()
        if not value:
            raise ValidationError(f"{label}不能为空")
        return value

    @staticmethod
    def _idempotency_key(command):
        return PositionVersionService._required_text(
            command, "idempotency_key", "幂等键"
        )

    @staticmethod
    def _validate_process_ids(process_ids, db):
        normalized = sorted({int(value) for value in process_ids or []})
        if not normalized:
            return []
        roots = {
            root["id"]: root
            for root in ProcessVersionRepository.roots(normalized, db=db)
        }
        invalid = []
        for process_id in normalized:
            root = roots.get(process_id)
            current = root.get("current_version") if root else None
            if (
                root is None
                or root.get("status") != "active"
                or root.get("lifecycle_status") != "active"
                or current is None
                or current.get("status") != "published"
            ):
                invalid.append(process_id)
        if invalid:
            raise PositionProcessInvalidError(
                "岗位只能关联当前已发布且启用的工序",
                details={"process_ids": invalid},
            )
        return normalized

    @staticmethod
    def _assert_unique_name(name, position_id=None, db=None):
        if position_id is None:
            duplicate = PositionRepository.find_position_by_name(name, db=db)
        else:
            duplicate = PositionRepository.find_position_by_name_excluding(
                name, position_id, db=db
            )
        if duplicate:
            raise ConflictError(f"岗位名称【{name}】已存在")

    @staticmethod
    def _event(version, event_type, actor, key, db, **fields):
        payload = {
            "position_id": version["position_id"],
            "position_version_id": version["id"],
            "event_type": event_type,
            "actor_id": actor["id"],
            "actor_name": actor["name"],
            "actor_role": actor["role"],
            "idempotency_key": key,
            "reason": fields.pop("reason", ""),
            "impact_digest": fields.pop(
                "impact_digest", version.get("impact_digest", "")
            ),
            "payload": fields.pop("payload", {}),
        }
        payload.update(fields)
        return PositionVersionRepository.create_event(payload, db)

    @staticmethod
    def _audit(
        db,
        *,
        action,
        actor,
        key,
        request_id,
        version,
        before=None,
        after=None,
        reason="",
    ):
        return PositionAuditService.record(
            db,
            action=action,
            actor=actor,
            request_id=request_id,
            idempotency_key=key,
            position_id=version["position_id"],
            position_version_id=version["id"],
            before=before,
            after=after,
            reason=reason,
            impact_digest=version.get("impact_digest", ""),
        )

    @staticmethod
    def create_position(command, actor_user, request_id=""):
        actor = PositionVersionService._actor(actor_user)
        key = PositionVersionService._idempotency_key(command)
        content = normalize_position_content(command)
        with BaseService.transaction() as db:
            replay = PositionVersionRepository.version_by_idempotency_key(key, db=db)
            if replay:
                return {
                    "root": PositionVersionRepository.root(
                        replay["position_id"], db=db
                    ),
                    "version": replay,
                }
            PositionVersionService._assert_unique_name(content["name"], db=db)
            process_ids = PositionVersionService._validate_process_ids(
                content["process_ids"], db
            )
            root = PositionVersionRepository.create_root(
                {
                    "name": content["name"],
                    "description": content["description"],
                    "created_by": actor["id"],
                },
                db,
            )
            payload = {
                **content,
                "process_ids": process_ids,
                "position_code_snapshot": root["position_code"],
                "status": "draft",
                "revision_reason": str(
                    command.get("revision_reason") or "创建 V1 草稿"
                ).strip(),
                "idempotency_key": key,
                "created_by": actor["id"],
                "created_by_name": actor["name"],
            }
            payload["content_digest"] = content_digest(
                {**payload, "position_id": root["id"], "version": 1}
            )
            version = PositionVersionRepository.create_revision(
                root["id"], payload, db
            )
            version = PositionVersionRepository.replace_version_processes(
                version["id"], process_ids, db
            )
            PositionVersionService._event(version, "created", actor, key, db)
            PositionVersionService._audit(
                db,
                action="position_version_create",
                actor=actor,
                key=key,
                request_id=request_id,
                version=version,
                after=version,
                reason=version["revision_reason"],
            )
            return {"root": root, "version": version}

    @staticmethod
    def create_revision(position_id, command, actor_user, request_id=""):
        actor = PositionVersionService._actor(actor_user)
        key = PositionVersionService._idempotency_key(command)
        reason = PositionVersionService._required_text(
            command, "revision_reason", "修订原因"
        )
        with BaseService.transaction() as db:
            replay = PositionVersionRepository.version_by_idempotency_key(key, db=db)
            if replay:
                return replay
            root = PositionVersionRepository.root(position_id, db=db)
            if not root:
                raise PositionNotFoundError("岗位不存在")
            if "row_version" in command:
                assert_row_version(command["row_version"], root["row_version"])
            if PositionVersionRepository.open_version(position_id, db=db):
                raise PositionVersionAlreadyOpenError("该岗位已有草稿或待审批修订版")
            current = PositionVersionRepository.current_version(position_id, db=db)
            if not current:
                raise PositionReferenceConflictError("岗位尚无可复制的当前版本")
            revision = copy_revision_content(
                current,
                version=int(current["version"]) + 1,
                revision_reason=reason,
            )
            for field in PositionVersionService.EDITABLE_FIELDS:
                if field in command:
                    revision[field] = command[field]
            revision = {**revision, **normalize_position_content(revision)}
            assert_root_identity_preserved(
                current,
                {**revision, **command},
                identity_change_reason=reason,
            )
            PositionVersionService._assert_unique_name(
                revision["name"], position_id=position_id, db=db
            )
            revision["process_ids"] = PositionVersionService._validate_process_ids(
                revision["process_ids"], db
            )
            revision.update(
                {
                    "position_code_snapshot": root["position_code"],
                    "effective_from": "",
                    "effective_to": "",
                    "created_by": actor["id"],
                    "created_by_name": actor["name"],
                    "approved_by": None,
                    "approved_by_name": "",
                    "approved_at": "",
                    "published_at": "",
                    "idempotency_key": key,
                }
            )
            revision["content_digest"] = content_digest(revision)
            created = PositionVersionRepository.create_revision(
                position_id, revision, db
            )
            created = PositionVersionRepository.replace_version_processes(
                created["id"], revision["process_ids"], db
            )
            PositionVersionService._event(
                created,
                "revision_created",
                actor,
                key,
                db,
                reason=reason,
                payload={"supersedes_version_id": current["id"]},
            )
            PositionVersionService._audit(
                db,
                action="position_version_revision_create",
                actor=actor,
                key=key,
                request_id=request_id,
                version=created,
                before=current,
                after=created,
                reason=reason,
            )
            return created

    @staticmethod
    def get_version(version_id):
        version = PositionVersionRepository.version(version_id)
        if not version:
            raise PositionVersionNotFoundError("岗位版本不存在")
        return version

    @staticmethod
    def list_versions(position_id):
        root = PositionVersionRepository.root(position_id)
        if not root:
            raise PositionNotFoundError("岗位不存在")
        return {
            "position": root,
            "versions": PositionVersionRepository.list_versions(position_id),
            "events": PositionVersionRepository.list_events(position_id),
        }

    @staticmethod
    def impact(version_id):
        version = PositionVersionService.get_version(version_id)
        return {
            "version": version,
            "impact": PositionImpactService.summarize(version["position_id"]),
        }

    @staticmethod
    def update_draft(version_id, command, actor_user, request_id=""):
        actor = PositionVersionService._actor(actor_user)
        key = PositionVersionService._idempotency_key(command)
        expected = require_row_version(command.get("row_version"))
        with BaseService.transaction() as db:
            replay = PositionVersionRepository.event_by_idempotency_key(key, db=db)
            if replay:
                return PositionVersionRepository.version(
                    replay["position_version_id"], db=db
                )
            version = PositionVersionRepository.version(version_id, db=db)
            if not version:
                raise PositionVersionNotFoundError("岗位版本不存在")
            validate_transition(version["status"], "draft")
            fields = {
                field: command[field]
                for field in PositionVersionService.EDITABLE_FIELDS
                if field in command
            }
            candidate = {**version, **fields}
            candidate = {**candidate, **normalize_position_content(candidate)}
            assert_root_identity_preserved(
                version,
                {**candidate, **command},
                identity_change_reason=version.get("revision_reason", ""),
            )
            PositionVersionService._assert_unique_name(
                candidate["name"], position_id=version["position_id"], db=db
            )
            candidate["process_ids"] = PositionVersionService._validate_process_ids(
                candidate["process_ids"], db
            )
            updated = PositionVersionRepository.update_version_content(
                version_id,
                "draft",
                expected,
                {
                    "name": candidate["name"],
                    "description": candidate["description"],
                    "content_digest": content_digest(candidate),
                },
                db,
            )
            updated = PositionVersionRepository.replace_version_processes(
                version_id, candidate["process_ids"], db
            )
            PositionVersionService._event(
                updated,
                "draft_updated",
                actor,
                key,
                db,
                from_status="draft",
                to_status="draft",
            )
            PositionVersionService._audit(
                db,
                action="position_version_update",
                actor=actor,
                key=key,
                request_id=request_id,
                version=updated,
                before=version,
                after=updated,
                reason=updated.get("revision_reason", ""),
            )
            return updated

    @staticmethod
    def submit(version_id, command, actor_user, request_id=""):
        actor = PositionVersionService._actor(actor_user)
        key = PositionVersionService._idempotency_key(command)
        with BaseService.transaction() as db:
            replay = PositionVersionRepository.event_by_idempotency_key(key, db=db)
            if replay:
                return PositionVersionRepository.version(
                    replay["position_version_id"], db=db
                )
            version = PositionVersionRepository.version(version_id, db=db)
            if not version:
                raise PositionVersionNotFoundError("岗位版本不存在")
            validate_transition(version["status"], "pending_approval")
            PositionVersionService._validate_process_ids(version["process_ids"], db)
            impact = PositionImpactService.summarize(version["position_id"], db=db)
            updated = PositionVersionRepository.transition_version(
                version_id,
                "draft",
                require_row_version(command.get("row_version")),
                "pending_approval",
                {
                    "submitted_at": PositionVersionService._now(),
                    "impact_digest": impact["impact_digest"],
                    "content_digest": content_digest(version),
                },
                db,
            )
            PositionVersionService._event(
                updated,
                "submitted",
                actor,
                key,
                db,
                from_status="draft",
                to_status="pending_approval",
            )
            PositionVersionService._audit(
                db,
                action="position_version_submit",
                actor=actor,
                key=key,
                request_id=request_id,
                version=updated,
                before=version,
                after=updated,
                reason=updated.get("revision_reason", ""),
            )
            return updated

    @staticmethod
    def _publish_pending(version, actor, key, request_id, db):
        root = PositionVersionRepository.root(version["position_id"], db=db)
        impact = PositionImpactService.summarize(version["position_id"], db=db)
        assert_impact_digest(version.get("impact_digest", ""), impact["impact_digest"])
        PositionVersionService._validate_process_ids(version["process_ids"], db)
        PositionVersionService._assert_unique_name(
            version["name"], position_id=version["position_id"], db=db
        )
        current = PositionVersionRepository.current_version(
            version["position_id"], db=db
        )
        now = PositionVersionService._now()
        if (
            current
            and current["id"] != version["id"]
            and current["status"] == "published"
        ):
            superseded = PositionVersionRepository.transition_version(
                current["id"],
                "published",
                current["row_version"],
                "superseded",
                {"effective_to": now},
                db,
            )
            PositionVersionService._event(
                superseded,
                "superseded",
                actor,
                key + ":superseded",
                db,
                from_status="published",
                to_status="superseded",
                payload={"successor_version_id": version["id"]},
            )
        published = PositionVersionRepository.transition_version(
            version["id"],
            "pending_approval",
            version["row_version"],
            "published",
            {
                "effective_from": version.get("effective_from") or now,
                "approved_by": actor["id"],
                "approved_by_name": actor["name"],
                "approved_at": now,
                "published_at": now,
            },
            db,
        )
        root_after = PositionVersionRepository.update_compatibility_projection(
            version["position_id"], published["id"], root["row_version"], db
        )
        if not current or current.get("name") != published.get("name"):
            PositionSnapshotService.apply_published_name(
                published["position_id"],
                published["id"],
                published["name"],
                published["published_at"],
                db,
            )
        PositionVersionService._event(
            published,
            "approved",
            actor,
            key + ":approved",
            db,
            from_status="pending_approval",
            to_status="published",
        )
        PositionVersionService._event(
            published,
            "published",
            actor,
            key,
            db,
            from_status="pending_approval",
            to_status="published",
        )
        PositionVersionService._audit(
            db,
            action="position_version_approve",
            actor=actor,
            key=key,
            request_id=request_id,
            version=published,
            before=current,
            after=published,
            reason=published.get("revision_reason", ""),
        )
        return published, root_after

    @staticmethod
    def approve(version_id, command, actor_user, request_id=""):
        actor = PositionVersionService._actor(actor_user)
        key = PositionVersionService._idempotency_key(command)
        with BaseService.transaction() as db:
            replay = PositionVersionRepository.event_by_idempotency_key(key, db=db)
            if replay:
                return PositionVersionRepository.version(
                    replay["position_version_id"], db=db
                )
            version = PositionVersionRepository.version(version_id, db=db)
            if not version:
                raise PositionVersionNotFoundError("岗位版本不存在")
            validate_transition(version["status"], "published")
            assert_row_version(command.get("row_version"), version["row_version"])
            assert_separation_of_duties(version["created_by"], actor["id"])
            published, _ = PositionVersionService._publish_pending(
                version, actor, key, request_id, db
            )
            return published

    @staticmethod
    def reject(version_id, command, actor_user, request_id=""):
        return PositionVersionService._terminal_transition(
            version_id,
            command,
            actor_user,
            "rejected",
            "驳回原因",
            request_id,
        )

    @staticmethod
    def cancel(version_id, command, actor_user, request_id=""):
        return PositionVersionService._terminal_transition(
            version_id,
            command,
            actor_user,
            "cancelled",
            "取消原因",
            request_id,
        )

    @staticmethod
    def _terminal_transition(
        version_id, command, actor_user, target_status, reason_label, request_id
    ):
        actor = PositionVersionService._actor(actor_user)
        key = PositionVersionService._idempotency_key(command)
        reason = PositionVersionService._required_text(command, "reason", reason_label)
        with BaseService.transaction() as db:
            replay = PositionVersionRepository.event_by_idempotency_key(key, db=db)
            if replay:
                return PositionVersionRepository.version(
                    replay["position_version_id"], db=db
                )
            version = PositionVersionRepository.version(version_id, db=db)
            if not version:
                raise PositionVersionNotFoundError("岗位版本不存在")
            validate_transition(version["status"], target_status)
            if target_status == "rejected":
                assert_separation_of_duties(version["created_by"], actor["id"])
            transitioned = PositionVersionRepository.transition_version(
                version_id,
                version["status"],
                require_row_version(command.get("row_version")),
                target_status,
                {},
                db,
            )
            PositionVersionService._event(
                transitioned,
                target_status,
                actor,
                key,
                db,
                reason=reason,
                from_status=version["status"],
                to_status=target_status,
            )
            PositionVersionService._audit(
                db,
                action=f"position_version_{target_status}",
                actor=actor,
                key=key,
                request_id=request_id,
                version=transitioned,
                before=version,
                after=transitioned,
                reason=reason,
            )
            return transitioned

    @staticmethod
    def resolve_current_for_business(position_id):
        root = PositionVersionRepository.root(position_id)
        if not root:
            raise PositionNotFoundError("岗位不存在")
        if root.get("lifecycle_status") != "active":
            raise PositionReferenceConflictError("岗位已退休，不能用于新业务")
        current = PositionVersionRepository.current_version(position_id)
        if not current or current.get("status") != "published":
            raise PositionReferenceConflictError("岗位尚无已发布版本，不能用于新业务")
        return current
