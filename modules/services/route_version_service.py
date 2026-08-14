"""Transactional workflow for stable route roots and immutable revisions."""

from datetime import datetime

from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.domain.process_versioning import (
    ReleaseDependencyError,
    assert_root_identity_preserved,
    assert_row_version,
    assert_route_category_consistency,
    assert_route_process_version_binding,
    assert_separation_of_duties,
    canonical_version_payload,
    copy_revision_content,
    normalize_route_items,
    payload_sha256,
    require_row_version,
    validate_route_version_transition,
)
from modules.repositories.process_version_repository import ProcessVersionRepository
from modules.repositories.route_version_repository import RouteVersionRepository
from modules.services import BaseService
from modules.services.master_data_impact_service import MasterDataImpactService


class RouteVersionService:
    EDITABLE_FIELDS = ("name", "category", "description")

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
    def _text(data, field, label):
        value = str((data or {}).get(field) or "").strip()
        if not value:
            raise ValidationError(f"{label}不能为空")
        return value

    @staticmethod
    def _key(command):
        return RouteVersionService._text(command, "idempotency_key", "幂等键")

    @staticmethod
    def _content_digest(version):
        return payload_sha256(canonical_version_payload("route", version, ()))

    @staticmethod
    def _impact_digest(version, db):
        result = MasterDataImpactService.route_impact(version["process_route_id"], db=db)
        return payload_sha256(
            canonical_version_payload("route", version, result["references"])
        )

    @staticmethod
    def _validate_items(category, items, db):
        normalized = normalize_route_items(items)
        versions = ProcessVersionRepository.versions_by_ids(
            [item["process_version_id"] for item in normalized], db=db
        )
        by_id = {version["id"]: version for version in versions}
        resolved = []
        for item in normalized:
            version = by_id.get(item["process_version_id"])
            if version is None:
                from modules.domain.process_versioning import RouteProcessVersionInvalidError

                raise RouteProcessVersionInvalidError(
                    "路线节点引用的工序版本不存在",
                    details={"process_version_id": item["process_version_id"]},
                )
            assert_route_process_version_binding(
                item["process_id"], version["process_id"], process_version_id=version["id"]
            )
            resolved.append(
                {
                    **item,
                    "process_category": version["category"],
                    "process_version_status": version["status"],
                }
            )
        assert_route_category_consistency(category, resolved)
        return normalized

    @staticmethod
    def _event(version, event_type, actor, key, db, **fields):
        payload = {
            "entity_id": version["process_route_id"],
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
        return RouteVersionRepository.insert_event(payload, db)

    @staticmethod
    def create_route(command, actor_user):
        actor = RouteVersionService._actor(actor_user)
        key = RouteVersionService._key(command)
        with BaseService.transaction() as db:
            replay = RouteVersionRepository.version_by_idempotency_key(key, db=db)
            if replay is not None:
                return {
                    "root": RouteVersionRepository.root(replay["process_route_id"], db=db),
                    "version": replay,
                }
            name = RouteVersionService._text(command, "name", "路线名称")
            category = str(command.get("category") or "").strip()
            items = RouteVersionService._validate_items(category, command.get("items") or [], db)
            root = RouteVersionRepository.create_root(
                {
                    "name": name,
                    "category": category,
                    "description": str(command.get("description") or "").strip(),
                    "status": "inactive",
                    "created_by": actor["id"],
                },
                db,
            )
            payload = {
                "route_code_snapshot": root["route_code"],
                "name": name,
                "category": category,
                "description": str(command.get("description") or "").strip(),
                "status": "draft",
                "revision_reason": str(command.get("revision_reason") or "创建 V1 草稿").strip(),
                "created_by": actor["id"],
                "created_by_name": actor["name"],
                "idempotency_key": key,
                "items": items,
            }
            payload["content_digest"] = RouteVersionService._content_digest(
                {**payload, "process_route_id": root["id"], "version": 1}
            )
            version = RouteVersionRepository.create_revision(root["id"], payload, items, db)
            RouteVersionService._event(version, "created", actor, key, db)
            return {"root": root, "version": version}

    @staticmethod
    def create_revision(route_id, command, actor_user):
        actor = RouteVersionService._actor(actor_user)
        key = RouteVersionService._key(command)
        with BaseService.transaction() as db:
            replay = RouteVersionRepository.version_by_idempotency_key(key, db=db)
            if replay is not None:
                return replay
            root = RouteVersionRepository.root(route_id, db=db)
            if root is None:
                raise NotFoundError("路线不存在")
            if "row_version" in command:
                assert_row_version(
                    command["row_version"], root["row_version"], entity_type="route"
                )
            if RouteVersionRepository.open_version(route_id, db=db) is not None:
                raise ConflictError("该路线已有草稿或待审批修订版")
            current = RouteVersionRepository.current_version(route_id, db=db)
            if current is None:
                raise ConflictError("路线尚无可复制的当前版本")
            revision = copy_revision_content(
                "route",
                current,
                version=int(current["version"]) + 1,
                revision_reason=command.get("revision_reason"),
            )
            for field in RouteVersionService.EDITABLE_FIELDS:
                if field in command:
                    revision[field] = command[field]
            if "items" in command:
                revision["items"] = command["items"]
            revision["name"] = str(revision.get("name") or "").strip()
            if not revision["name"]:
                raise ValidationError("路线名称不能为空")
            revision["category"] = str(revision.get("category") or "").strip()
            revision["description"] = str(revision.get("description") or "").strip()
            assert_root_identity_preserved("route", current, {**revision, **command})
            items = RouteVersionService._validate_items(
                revision["category"], revision.get("items") or [], db
            )
            revision.update(
                {
                    "route_code_snapshot": root["route_code"],
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
                    "items": items,
                }
            )
            revision["content_digest"] = RouteVersionService._content_digest(revision)
            created = RouteVersionRepository.create_revision(route_id, revision, items, db)
            RouteVersionService._event(
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
        version = RouteVersionRepository.version(version_id)
        if version is None:
            raise NotFoundError("路线版本不存在")
        return version

    @staticmethod
    def list_versions(route_id):
        root = RouteVersionRepository.root(route_id)
        if root is None:
            raise NotFoundError("路线不存在")
        return {
            "route": root,
            "versions": RouteVersionRepository.list_versions(route_id),
            "events": RouteVersionRepository.list_events(route_id),
        }

    @staticmethod
    def impact(version_id):
        version = RouteVersionService.get_version(version_id)
        return {
            "version": version,
            "impact": MasterDataImpactService.route_impact(
                version["process_route_id"]
            ),
        }

    @staticmethod
    def update_draft(version_id, command, actor_user):
        RouteVersionService._actor(actor_user)
        expected = require_row_version(command.get("row_version"))
        with BaseService.transaction() as db:
            version = RouteVersionRepository.version(version_id, db=db)
            if version is None:
                raise NotFoundError("路线版本不存在")
            validate_route_version_transition(version["status"], "draft")
            fields = {
                field: command[field]
                for field in RouteVersionService.EDITABLE_FIELDS
                if field in command
            }
            candidate = {**version, **fields, **command}
            assert_root_identity_preserved("route", version, candidate)
            items = RouteVersionService._validate_items(
                str(candidate.get("category") or "").strip(),
                candidate.get("items") or [],
                db,
            )
            if "name" in fields:
                fields["name"] = str(fields["name"] or "").strip()
                if not fields["name"]:
                    raise ValidationError("路线名称不能为空")
            for field in ("category", "description"):
                if field in fields:
                    fields[field] = str(fields[field] or "").strip()
            if "items" in command:
                updated = RouteVersionRepository.replace_items(
                    version_id, "draft", expected, items, db
                )
                expected = updated["row_version"]
            fields["content_digest"] = RouteVersionService._content_digest(
                {**version, **fields, "items": items}
            )
            return RouteVersionRepository.update_version_content(
                version_id, "draft", expected, fields, db
            )

    @staticmethod
    def submit(version_id, command, actor_user):
        actor = RouteVersionService._actor(actor_user)
        key = RouteVersionService._key(command)
        with BaseService.transaction() as db:
            replay = RouteVersionRepository.event_by_idempotency_key(key, db=db)
            if replay is not None:
                return RouteVersionRepository.version(replay["version_id"], db=db)
            version = RouteVersionRepository.version(version_id, db=db)
            if version is None:
                raise NotFoundError("路线版本不存在")
            validate_route_version_transition(version["status"], "pending_approval")
            RouteVersionService._validate_items(version["category"], version["items"], db)
            updated = RouteVersionRepository.transition_version(
                version_id,
                "draft",
                require_row_version(command.get("row_version")),
                "pending_approval",
                {
                    "impact_digest": RouteVersionService._impact_digest(version, db),
                    "content_digest": RouteVersionService._content_digest(version),
                },
                db,
            )
            RouteVersionService._event(
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
    def _validate_publish_dependencies(version, command, db, available_process_ids=()):
        available = {int(value) for value in available_process_ids}
        required_price_ids = {int(value) for value in command.get("required_price_process_ids") or []}
        dispositions = {
            int(item.get("process_id")): item
            for item in command.get("price_dispositions") or []
            if item.get("process_id") is not None
        }
        for item in version["items"]:
            process_version = ProcessVersionRepository.version(item["process_version_id"], db=db)
            if process_version is None or (
                process_version["status"] != "published"
                and process_version["id"] not in available
            ):
                raise ReleaseDependencyError(
                    "路线节点工序版本尚未发布",
                    details={
                        "reason_code": "ROUTE_PROCESS_VERSION_INVALID",
                        "process_id": item["process_id"],
                        "process_version_id": item["process_version_id"],
                    },
                )
            if item["process_id"] in required_price_ids:
                disposition = dispositions.get(item["process_id"])
                if disposition is None or disposition.get("disposition") not in {
                    "price_version",
                    "not_applicable",
                }:
                    raise ReleaseDependencyError(
                        "需要计件工价的路线节点缺少工价处置",
                        details={
                            "reason_code": "PRICE_VERSION_BINDING_REQUIRED",
                            "process_id": item["process_id"],
                        },
                    )
                if disposition["disposition"] == "not_applicable" and not str(
                    disposition.get("reason") or ""
                ).strip():
                    raise ValidationError("工价不适用处置必须填写原因")

    @staticmethod
    def _publish_pending(
        version, actor, db, event_prefix, command=None, check_impact=True
    ):
        command = command or {}
        RouteVersionService._validate_publish_dependencies(version, command, db)
        current_digest = RouteVersionService._impact_digest(version, db)
        if check_impact and current_digest != version.get("impact_digest", ""):
            raise ConflictError(
                "路线版本影响范围已变化，请重新提交",
                details={
                    "submitted_impact_digest": version.get("impact_digest", ""),
                    "current_impact_digest": current_digest,
                },
            )
        root = RouteVersionRepository.root(version["process_route_id"], db=db)
        current = RouteVersionRepository.current_version(version["process_route_id"], db=db)
        now = RouteVersionService._now()
        if current is not None and current["id"] != version["id"] and current["status"] == "published":
            RouteVersionRepository.transition_version(
                current["id"], "published", current["row_version"], "superseded", {"effective_to": now}, db
            )
            RouteVersionService._event(
                current,
                "superseded",
                actor,
                event_prefix + ":superseded",
                db,
                from_status="published",
                to_status="superseded",
                payload={"successor_version_id": version["id"]},
            )
        published = RouteVersionRepository.transition_version(
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
        RouteVersionService._event(
            published,
            "approved",
            actor,
            event_prefix + ":approved",
            db,
            from_status="pending_approval",
            to_status="published",
        )
        RouteVersionRepository.update_compatibility_projection(
            version["process_route_id"], published["id"], root["row_version"], db
        )
        RouteVersionService._event(
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
        actor = RouteVersionService._actor(actor_user)
        key = RouteVersionService._key(command)
        with BaseService.transaction() as db:
            replay = RouteVersionRepository.event_by_idempotency_key(key, db=db)
            if replay is not None:
                return RouteVersionRepository.version(replay["version_id"], db=db)
            version = RouteVersionRepository.version(version_id, db=db)
            if version is None:
                raise NotFoundError("路线版本不存在")
            validate_route_version_transition(version["status"], "published")
            expected = require_row_version(command.get("row_version"))
            if expected != int(version["row_version"]):
                from modules.domain.process_versioning import RouteVersionStaleError

                raise RouteVersionStaleError("路线版本已被其他操作修改，请刷新后重试")
            assert_separation_of_duties(
                version["created_by"], actor["id"], entity_type="route"
            )
            return RouteVersionService._publish_pending(version, actor, db, key, command)

    @staticmethod
    def reject(version_id, command, actor_user):
        actor = RouteVersionService._actor(actor_user)
        key = RouteVersionService._key(command)
        reason = RouteVersionService._text(command, "reason", "驳回原因")
        with BaseService.transaction() as db:
            replay = RouteVersionRepository.event_by_idempotency_key(key, db=db)
            if replay is not None:
                return RouteVersionRepository.version(replay["version_id"], db=db)
            version = RouteVersionRepository.version(version_id, db=db)
            if version is None:
                raise NotFoundError("路线版本不存在")
            validate_route_version_transition(version["status"], "rejected")
            assert_separation_of_duties(
                version["created_by"], actor["id"], entity_type="route"
            )
            rejected = RouteVersionRepository.transition_version(
                version_id,
                "pending_approval",
                require_row_version(command.get("row_version")),
                "rejected",
                {},
                db,
            )
            RouteVersionService._event(
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
    def resolve_current_for_business(route_id):
        root = RouteVersionRepository.root(route_id)
        if root is None:
            raise NotFoundError("路线不存在")
        if root.get("lifecycle_status") != "active":
            raise ConflictError("路线已退休，不能用于新业务")
        version = RouteVersionRepository.current_version(route_id)
        if version is None or version.get("status") != "published":
            raise ConflictError("路线尚无已发布版本，不能用于新业务")
        return version
