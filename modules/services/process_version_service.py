"""Transactional workflow for stable process roots and immutable revisions."""

from datetime import datetime

from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.domain.process_versioning import (
    assert_root_identity_preserved,
    assert_row_version,
    assert_separation_of_duties,
    canonical_version_payload,
    copy_revision_content,
    payload_sha256,
    require_row_version,
    validate_process_version_transition,
)
from modules.repositories.process_version_repository import ProcessVersionRepository
from modules.services import BaseService
from modules.services.master_data_impact_service import MasterDataImpactService


class ProcessVersionService:
    EDITABLE_FIELDS = ("name", "category", "description", "seq_order")

    @staticmethod
    def _now():
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

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
    def _required_text(data, field, label):
        value = str((data or {}).get(field) or "").strip()
        if not value:
            raise ValidationError(f"{label}不能为空")
        return value

    @staticmethod
    def _idempotency_key(command):
        return ProcessVersionService._required_text(command, "idempotency_key", "幂等键")

    @staticmethod
    def _content_digest(version):
        return payload_sha256(canonical_version_payload("process", version, ()))

    @staticmethod
    def _impact(version, db):
        result = MasterDataImpactService.process_impact(version["process_id"], db=db)
        return result["references"]

    @staticmethod
    def _impact_digest(version, db):
        return payload_sha256(
            canonical_version_payload(
                "process", version, ProcessVersionService._impact(version, db)
            )
        )

    @staticmethod
    def _event(version, event_type, actor, key, db, **fields):
        payload = {
            "entity_id": version["process_id"],
            "version_id": version["id"],
            "event_type": event_type,
            "actor_id": actor["id"],
            "actor_name": actor["name"],
            "actor_role": actor["role"],
            "idempotency_key": key,
            "reason": fields.pop("reason", ""),
            "impact_digest": version.get("impact_digest", ""),
            "payload": fields.pop("payload", {}),
        }
        payload.update(fields)
        return ProcessVersionRepository.insert_event(payload, db)

    @staticmethod
    def create_process(command, actor_user):
        actor = ProcessVersionService._actor(actor_user)
        key = ProcessVersionService._idempotency_key(command)
        with BaseService.transaction() as db:
            replay = ProcessVersionRepository.version_by_idempotency_key(key, db=db)
            if replay is not None:
                return {
                    "root": ProcessVersionRepository.root(replay["process_id"], db=db),
                    "version": replay,
                }
            name = ProcessVersionService._required_text(command, "name", "工序名称")
            root = ProcessVersionRepository.create_root(
                {
                    "name": name,
                    "category": str(command.get("category") or "").strip(),
                    "description": str(command.get("description") or "").strip(),
                    "seq_order": int(command.get("seq_order") or 0),
                    "status": "inactive",
                    "created_by": actor["id"],
                },
                db,
            )
            version_payload = {
                "process_code_snapshot": root["process_code"],
                "name": name,
                "category": str(command.get("category") or "").strip(),
                "description": str(command.get("description") or "").strip(),
                "seq_order": int(command.get("seq_order") or 0),
                "status": "draft",
                "revision_reason": str(command.get("revision_reason") or "创建 V1 草稿").strip(),
                "created_by": actor["id"],
                "created_by_name": actor["name"],
                "idempotency_key": key,
            }
            version_payload["content_digest"] = ProcessVersionService._content_digest(
                {**version_payload, "process_id": root["id"], "version": 1}
            )
            version = ProcessVersionRepository.create_revision(root["id"], version_payload, db)
            ProcessVersionService._event(version, "created", actor, key, db)
            return {"root": root, "version": version}

    @staticmethod
    def create_revision(process_id, command, actor_user):
        actor = ProcessVersionService._actor(actor_user)
        key = ProcessVersionService._idempotency_key(command)
        with BaseService.transaction() as db:
            replay = ProcessVersionRepository.version_by_idempotency_key(key, db=db)
            if replay is not None:
                return replay
            root = ProcessVersionRepository.root(process_id, db=db)
            if root is None:
                raise NotFoundError("工序不存在")
            if "row_version" in command:
                assert_row_version(command["row_version"], root["row_version"])
            if ProcessVersionRepository.open_version(process_id, db=db) is not None:
                raise ConflictError("该工序已有草稿或待审批修订版")
            current = ProcessVersionRepository.current_version(process_id, db=db)
            if current is None:
                raise ConflictError("工序尚无可复制的当前版本")
            revision = copy_revision_content(
                "process",
                current,
                version=int(current["version"]) + 1,
                revision_reason=command.get("revision_reason"),
            )
            for field in ProcessVersionService.EDITABLE_FIELDS:
                if field in command:
                    revision[field] = command[field]
            revision["name"] = str(revision.get("name") or "").strip()
            if not revision["name"]:
                raise ValidationError("工序名称不能为空")
            revision["category"] = str(revision.get("category") or "").strip()
            revision["description"] = str(revision.get("description") or "").strip()
            revision["seq_order"] = int(revision.get("seq_order") or 0)
            assert_root_identity_preserved("process", current, {**revision, **command})
            revision.update(
                {
                    "process_code_snapshot": root["process_code"],
                    "supersedes_version_id": current["id"],
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
            revision["content_digest"] = ProcessVersionService._content_digest(revision)
            created = ProcessVersionRepository.create_revision(process_id, revision, db)
            ProcessVersionService._event(
                created,
                "revision_created",
                actor,
                key,
                db,
                reason=created["revision_reason"],
                payload={"supersedes_version_id": current["id"]},
            )
            return created

    @staticmethod
    def get_version(version_id):
        version = ProcessVersionRepository.version(version_id)
        if version is None:
            raise NotFoundError("工序版本不存在")
        return version

    @staticmethod
    def list_versions(process_id):
        root = ProcessVersionRepository.root(process_id)
        if root is None:
            raise NotFoundError("工序不存在")
        return {
            "process": root,
            "versions": ProcessVersionRepository.list_versions(process_id),
            "events": ProcessVersionRepository.list_events(process_id),
        }

    @staticmethod
    def impact(version_id):
        version = ProcessVersionService.get_version(version_id)
        return {
            "version": version,
            "impact": MasterDataImpactService.process_impact(version["process_id"]),
        }

    @staticmethod
    def update_draft(version_id, command, actor_user):
        ProcessVersionService._actor(actor_user)
        expected = require_row_version(command.get("row_version"))
        with BaseService.transaction() as db:
            version = ProcessVersionRepository.version(version_id, db=db)
            if version is None:
                raise NotFoundError("工序版本不存在")
            validate_process_version_transition(version["status"], "draft")
            fields = {
                field: command[field]
                for field in ProcessVersionService.EDITABLE_FIELDS
                if field in command
            }
            candidate = {**version, **fields, **command}
            assert_root_identity_preserved("process", version, candidate)
            if "name" in fields:
                fields["name"] = str(fields["name"] or "").strip()
                if not fields["name"]:
                    raise ValidationError("工序名称不能为空")
            if "category" in fields:
                fields["category"] = str(fields["category"] or "").strip()
            if "description" in fields:
                fields["description"] = str(fields["description"] or "").strip()
            if "seq_order" in fields:
                fields["seq_order"] = int(fields["seq_order"] or 0)
            fields["content_digest"] = ProcessVersionService._content_digest(
                {**version, **fields}
            )
            return ProcessVersionRepository.update_version_content(
                version_id, "draft", expected, fields, db
            )

    @staticmethod
    def submit(version_id, command, actor_user):
        actor = ProcessVersionService._actor(actor_user)
        key = ProcessVersionService._idempotency_key(command)
        with BaseService.transaction() as db:
            replay = ProcessVersionRepository.event_by_idempotency_key(key, db=db)
            if replay is not None:
                return ProcessVersionRepository.version(replay["version_id"], db=db)
            version = ProcessVersionRepository.version(version_id, db=db)
            if version is None:
                raise NotFoundError("工序版本不存在")
            validate_process_version_transition(version["status"], "pending_approval")
            impact_digest = ProcessVersionService._impact_digest(version, db)
            updated = ProcessVersionRepository.transition_version(
                version_id,
                "draft",
                require_row_version(command.get("row_version")),
                "pending_approval",
                {
                    "impact_digest": impact_digest,
                    "content_digest": ProcessVersionService._content_digest(version),
                },
                db,
            )
            ProcessVersionService._event(
                updated,
                "submitted",
                actor,
                key,
                db,
                from_status="draft",
                to_status="pending_approval",
            )
            return updated

    @staticmethod
    def _publish_pending(version, actor, db, event_prefix, check_impact=True):
        root = ProcessVersionRepository.root(version["process_id"], db=db)
        current_digest = ProcessVersionService._impact_digest(version, db)
        if check_impact and current_digest != version.get("impact_digest", ""):
            raise ConflictError(
                "工序版本影响范围已变化，请重新提交",
                details={
                    "submitted_impact_digest": version.get("impact_digest", ""),
                    "current_impact_digest": current_digest,
                },
            )
        current = ProcessVersionRepository.current_version(version["process_id"], db=db)
        now = ProcessVersionService._now()
        if current is not None and current["id"] != version["id"] and current["status"] == "published":
            ProcessVersionRepository.transition_version(
                current["id"],
                "published",
                current["row_version"],
                "superseded",
                {"effective_to": now},
                db,
            )
            ProcessVersionService._event(
                current,
                "superseded",
                actor,
                event_prefix + ":superseded",
                db,
                from_status="published",
                to_status="superseded",
                payload={"successor_version_id": version["id"]},
            )
        published = ProcessVersionRepository.transition_version(
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
        ProcessVersionService._event(
            published,
            "approved",
            actor,
            event_prefix + ":approved",
            db,
            from_status="pending_approval",
            to_status="published",
        )
        ProcessVersionRepository.update_compatibility_projection(
            version["process_id"], published["id"], root["row_version"], db
        )
        ProcessVersionService._event(
            published,
            "published",
            actor,
            event_prefix,
            db,
            from_status="pending_approval",
            to_status="published",
        )
        return published

    @staticmethod
    def approve(version_id, command, actor_user):
        actor = ProcessVersionService._actor(actor_user)
        key = ProcessVersionService._idempotency_key(command)
        with BaseService.transaction() as db:
            replay = ProcessVersionRepository.event_by_idempotency_key(key, db=db)
            if replay is not None:
                return ProcessVersionRepository.version(replay["version_id"], db=db)
            version = ProcessVersionRepository.version(version_id, db=db)
            if version is None:
                raise NotFoundError("工序版本不存在")
            validate_process_version_transition(version["status"], "published")
            require_row_version(command.get("row_version"))
            if int(command["row_version"]) != int(version["row_version"]):
                from modules.domain.process_versioning import ProcessVersionStaleError

                raise ProcessVersionStaleError("工序版本已被其他操作修改，请刷新后重试")
            assert_separation_of_duties(version["created_by"], actor["id"])
            return ProcessVersionService._publish_pending(version, actor, db, key)

    @staticmethod
    def reject(version_id, command, actor_user):
        actor = ProcessVersionService._actor(actor_user)
        key = ProcessVersionService._idempotency_key(command)
        reason = ProcessVersionService._required_text(command, "reason", "驳回原因")
        with BaseService.transaction() as db:
            replay = ProcessVersionRepository.event_by_idempotency_key(key, db=db)
            if replay is not None:
                return ProcessVersionRepository.version(replay["version_id"], db=db)
            version = ProcessVersionRepository.version(version_id, db=db)
            if version is None:
                raise NotFoundError("工序版本不存在")
            validate_process_version_transition(version["status"], "rejected")
            assert_separation_of_duties(version["created_by"], actor["id"])
            rejected = ProcessVersionRepository.transition_version(
                version_id,
                "pending_approval",
                require_row_version(command.get("row_version")),
                "rejected",
                {},
                db,
            )
            ProcessVersionService._event(
                rejected,
                "rejected",
                actor,
                key,
                db,
                reason=reason,
                from_status="pending_approval",
                to_status="rejected",
            )
            return rejected

    @staticmethod
    def resolve_current_for_business(process_id):
        root = ProcessVersionRepository.root(process_id)
        if root is None:
            raise NotFoundError("工序不存在")
        if root.get("lifecycle_status") != "active":
            raise ConflictError("工序已退休，不能用于新业务")
        version = ProcessVersionRepository.current_version(process_id)
        if version is None or version.get("status") != "published":
            raise ConflictError("工序尚无已发布版本，不能用于新业务")
        return version
