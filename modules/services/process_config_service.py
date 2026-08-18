"""Versioned, dual-control process configuration application service."""

import json
from datetime import datetime

from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.domain.process_config import (
    PROCESS_CONFIG_FIELDS,
    ProcessConfigOpenRevisionError,
    ProcessConfigStaleError,
    assert_approval_separation,
    assert_row_version,
    changed_process_config_fields,
    normalize_process_config,
    require_row_version,
)
from modules.repositories.process_config_repository import ProcessConfigRepository
from modules.services import BaseService


def _row_dict(row):
    if row is None:
        return None
    value = dict(row)
    for field in ("changed_fields", "detail"):
        if field in value and isinstance(value[field], str):
            try:
                value[field] = json.loads(value[field] or ("[]" if field == "changed_fields" else "{}"))
            except json.JSONDecodeError:
                value[field] = [] if field == "changed_fields" else {}
    return value


class ProcessConfigService:
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
        }

    @staticmethod
    def _text(command, field, label):
        value = str((command or {}).get(field) or "").strip()
        if not value:
            raise ValidationError(f"{label}不能为空")
        return value

    @staticmethod
    def _key(command):
        return ProcessConfigService._text(command, "idempotency_key", "幂等键")

    @staticmethod
    def _values(row):
        return {field: row[field] for field in PROCESS_CONFIG_FIELDS}

    @staticmethod
    def _present_revision(row, db=None):
        revision = _row_dict(row)
        if revision is None:
            return None
        revision["events"] = [
            _row_dict(event)
            for event in ProcessConfigRepository.list_events(revision["id"], db=db)
        ]
        return revision

    @staticmethod
    def get_current():
        config = ProcessConfigRepository.get_active()
        if config is None:
            raise RuntimeError("工艺配置尚未初始化")
        return {
            "config": _row_dict(config),
            "open_revision": ProcessConfigService._present_revision(
                ProcessConfigRepository.open_revision()
            ),
        }

    @staticmethod
    def list_revisions(limit=100):
        try:
            limit = int(limit)
        except (TypeError, ValueError) as exc:
            raise ValidationError("历史记录条数必须是整数") from exc
        limit = max(1, min(limit, 200))
        return {
            "revisions": [
                ProcessConfigService._present_revision(row)
                for row in ProcessConfigRepository.list_revisions(limit=limit)
            ]
        }

    @staticmethod
    def create_revision(command, actor_user):
        actor = ProcessConfigService._actor(actor_user)
        key = ProcessConfigService._key(command)
        reason = ProcessConfigService._text(command, "revision_reason", "修订原因")
        with BaseService.transaction() as db:
            replay = ProcessConfigRepository.revision_by_idempotency_key(key, db=db)
            if replay is not None:
                return ProcessConfigService._present_revision(replay, db=db)
            config = ProcessConfigRepository.get_active(db=db)
            if config is None:
                raise RuntimeError("工艺配置尚未初始化")
            assert_row_version(command.get("row_version"), config["row_version"])
            open_revision = ProcessConfigRepository.open_revision(db=db)
            if open_revision is not None:
                raise ProcessConfigOpenRevisionError(
                    "已有工艺配置草稿或待审批修订版",
                    details={"revision_id": open_revision["id"]},
                )
            changes = {
                field: command[field]
                for field in PROCESS_CONFIG_FIELDS
                if field in command
            }
            current_values = ProcessConfigService._values(config)
            candidate = normalize_process_config(
                changes, base=current_values, require_changes=True
            )
            changed_fields = changed_process_config_fields(current_values, candidate)
            revision = ProcessConfigRepository.create_revision(
                candidate,
                {
                    "version": ProcessConfigRepository.next_version(db=db),
                    "base_row_version": config["row_version"],
                    "changed_fields": changed_fields,
                    "revision_reason": reason,
                    "created_by": actor["id"],
                    "created_by_name": actor["name"],
                    "idempotency_key": key,
                },
                db,
            )
            ProcessConfigRepository.insert_event(
                revision["id"], "created", actor, key, db,
                to_status="draft", detail={"changed_fields": changed_fields},
            )
            ProcessConfigRepository.insert_audit(
                "process_config_revision_create",
                revision,
                actor,
                db,
                changed_fields=changed_fields,
            )
            return ProcessConfigService._present_revision(revision, db=db)

    @staticmethod
    def update_draft(revision_id, command, actor_user):
        actor = ProcessConfigService._actor(actor_user)
        key = ProcessConfigService._key(command)
        with BaseService.transaction() as db:
            replay = ProcessConfigRepository.event_by_idempotency_key(key, db=db)
            if replay is not None:
                return ProcessConfigService._present_revision(
                    ProcessConfigRepository.get_revision(replay["revision_id"], db=db), db=db
                )
            revision = ProcessConfigRepository.get_revision(revision_id, db=db)
            if revision is None:
                raise NotFoundError("工艺配置修订版不存在")
            if revision["status"] != "draft":
                raise ConflictError("只有草稿状态可以修改")
            if int(revision["created_by"] or 0) != actor["id"]:
                raise ConflictError("只能修改本人创建的工艺配置草稿")
            assert_row_version(command.get("row_version"), revision["row_version"])
            config = ProcessConfigRepository.get_active(db=db)
            assert_row_version(revision["base_row_version"], config["row_version"])
            changes = {
                field: command[field]
                for field in PROCESS_CONFIG_FIELDS
                if field in command
            }
            candidate = normalize_process_config(
                changes,
                base=ProcessConfigService._values(revision),
            )
            changed_fields = changed_process_config_fields(
                ProcessConfigService._values(config), candidate
            )
            if not changed_fields:
                raise ValidationError("工艺配置没有发生变化")
            reason = str(command.get("revision_reason") or revision["revision_reason"]).strip()
            updated = ProcessConfigRepository.update_draft(
                revision_id,
                revision["row_version"],
                candidate,
                {"changed_fields": changed_fields, "revision_reason": reason},
                db,
            )
            if updated is None:
                raise ProcessConfigStaleError("工艺配置草稿已被其他用户更新")
            ProcessConfigRepository.insert_event(
                revision_id, "updated", actor, key, db,
                from_status="draft", to_status="draft",
                detail={"changed_fields": changed_fields},
            )
            ProcessConfigRepository.insert_audit(
                "process_config_revision_update",
                updated,
                actor,
                db,
                changed_fields=changed_fields,
            )
            return ProcessConfigService._present_revision(updated, db=db)

    @staticmethod
    def submit(revision_id, command, actor_user):
        actor = ProcessConfigService._actor(actor_user)
        key = ProcessConfigService._key(command)
        with BaseService.transaction() as db:
            replay = ProcessConfigRepository.event_by_idempotency_key(key, db=db)
            if replay is not None:
                return ProcessConfigService._present_revision(
                    ProcessConfigRepository.get_revision(replay["revision_id"], db=db), db=db
                )
            revision = ProcessConfigRepository.get_revision(revision_id, db=db)
            if revision is None:
                raise NotFoundError("工艺配置修订版不存在")
            if revision["status"] != "draft":
                raise ConflictError("只有草稿状态可以提交")
            if int(revision["created_by"] or 0) != actor["id"]:
                raise ConflictError("只能提交本人创建的工艺配置草稿")
            assert_row_version(command.get("row_version"), revision["row_version"])
            config = ProcessConfigRepository.get_active(db=db)
            assert_row_version(revision["base_row_version"], config["row_version"])
            submitted_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            submitted = ProcessConfigRepository.transition_revision(
                revision_id,
                "draft",
                revision["row_version"],
                "pending_approval",
                {"submitted_at": submitted_at},
                db,
            )
            if submitted is None:
                raise ProcessConfigStaleError("工艺配置草稿已被其他用户更新")
            ProcessConfigRepository.insert_event(
                revision_id, "submitted", actor, key, db,
                from_status="draft", to_status="pending_approval",
            )
            ProcessConfigRepository.insert_audit(
                "process_config_revision_submit", submitted, actor, db
            )
            return ProcessConfigService._present_revision(submitted, db=db)

    @staticmethod
    def approve(revision_id, command, actor_user):
        actor = ProcessConfigService._actor(actor_user)
        key = ProcessConfigService._key(command)
        with BaseService.transaction() as db:
            replay = ProcessConfigRepository.event_by_idempotency_key(key, db=db)
            if replay is not None:
                return {
                    "config": _row_dict(ProcessConfigRepository.get_active(db=db)),
                    "revision": ProcessConfigService._present_revision(
                        ProcessConfigRepository.get_revision(replay["revision_id"], db=db), db=db
                    ),
                }
            revision = ProcessConfigRepository.get_revision(revision_id, db=db)
            if revision is None:
                raise NotFoundError("工艺配置修订版不存在")
            if revision["status"] != "pending_approval":
                raise ConflictError("只有待审批修订版可以批准")
            assert_row_version(command.get("row_version"), revision["row_version"])
            assert_approval_separation(revision["created_by"], actor["id"])
            config = ProcessConfigRepository.get_active(db=db)
            assert_row_version(revision["base_row_version"], config["row_version"])
            approved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            published = ProcessConfigRepository.transition_revision(
                revision_id,
                "pending_approval",
                revision["row_version"],
                "published",
                {
                    "approved_by": actor["id"],
                    "approved_by_name": actor["name"],
                    "approved_at": approved_at,
                },
                db,
            )
            if published is None:
                raise ProcessConfigStaleError("工艺配置修订版已被其他用户更新")
            active = ProcessConfigRepository.publish_active(published, actor, db)
            if active is None:
                raise ProcessConfigStaleError("当前工艺配置已发生变化，请重新制单")
            ProcessConfigRepository.update_legacy_mirrors(active, db)
            ProcessConfigRepository.insert_event(
                revision_id, "approved", actor, key, db,
                from_status="pending_approval", to_status="published",
            )
            ProcessConfigRepository.insert_event(
                revision_id, "published", actor, key + ":published", db,
                from_status="pending_approval", to_status="published",
                detail={"active_version": active["version"]},
            )
            ProcessConfigRepository.insert_audit(
                "process_config_revision_approve",
                published,
                actor,
                db,
                changed_fields=_row_dict(published)["changed_fields"],
            )
            result = {
                "config": _row_dict(active),
                "revision": ProcessConfigService._present_revision(published, db=db),
            }
        from modules.cache_utils import invalidate_cache
        from modules.setting_reader import clear_settings_cache

        clear_settings_cache()
        invalidate_cache()
        return result

    @staticmethod
    def reject(revision_id, command, actor_user):
        actor = ProcessConfigService._actor(actor_user)
        key = ProcessConfigService._key(command)
        reason = ProcessConfigService._text(command, "reason", "驳回原因")
        with BaseService.transaction() as db:
            replay = ProcessConfigRepository.event_by_idempotency_key(key, db=db)
            if replay is not None:
                return ProcessConfigService._present_revision(
                    ProcessConfigRepository.get_revision(replay["revision_id"], db=db), db=db
                )
            revision = ProcessConfigRepository.get_revision(revision_id, db=db)
            if revision is None:
                raise NotFoundError("工艺配置修订版不存在")
            if revision["status"] != "pending_approval":
                raise ConflictError("只有待审批修订版可以驳回")
            assert_row_version(command.get("row_version"), revision["row_version"])
            assert_approval_separation(revision["created_by"], actor["id"])
            rejected_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            rejected = ProcessConfigRepository.transition_revision(
                revision_id,
                "pending_approval",
                revision["row_version"],
                "rejected",
                {
                    "rejected_reason": reason,
                    "rejected_by": actor["id"],
                    "rejected_by_name": actor["name"],
                    "rejected_at": rejected_at,
                },
                db,
            )
            if rejected is None:
                raise ProcessConfigStaleError("工艺配置修订版已被其他用户更新")
            ProcessConfigRepository.insert_event(
                revision_id, "rejected", actor, key, db,
                from_status="pending_approval", to_status="rejected",
                detail={"reason": reason},
            )
            ProcessConfigRepository.insert_audit(
                "process_config_revision_reject", rejected, actor, db, reason=reason
            )
            return ProcessConfigService._present_revision(rejected, db=db)
