"""Atomic, dependency-aware publication of process master-data batches."""

from datetime import datetime

from modules.domain.errors import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from modules.domain.price_versioning import (
    PriceBindingMismatchError,
    PriceVersionVoidedError,
    assert_price_snapshot_current,
)
from modules.domain.process_versioning import (
    assert_separation_of_duties,
    canonical_version_payload,
    payload_sha256,
    require_row_version,
    summarize_release_batch,
    validate_release_batch_dependencies,
)
from modules.repositories.master_data_release_repository import MasterDataReleaseRepository
from modules.repositories.payroll_repository import PayrollRepository
from modules.repositories.process_version_repository import ProcessVersionRepository
from modules.repositories.route_version_repository import RouteVersionRepository
from modules.services import BaseService
from modules.services.master_data_impact_service import MasterDataImpactService


class MasterDataReleaseService:
    @staticmethod
    def _actor(actor):
        actor = actor or {}
        try:
            actor_id = int(actor.get("id"))
        except (TypeError, ValueError) as exc:
            raise ValidationError("操作人不能为空") from exc
        if actor_id <= 0:
            raise ValidationError("操作人不能为空")
        return {"id": actor_id, "name": str(actor.get("name") or actor.get("username") or "").strip(), "role": str(actor.get("role") or "").strip()}

    @staticmethod
    def _text(data, field, label):
        value = str((data or {}).get(field) or "").strip()
        if not value:
            raise ValidationError(f"{label}不能为空")
        return value

    @staticmethod
    def _key(data):
        return MasterDataReleaseService._text(data, "idempotency_key", "幂等键")

    @staticmethod
    def _batch_input(batch, exceptions=()):
        process_versions = [dict(item) for item in batch.get("process_versions") or []]
        route_versions = [dict(item) for item in batch.get("route_versions") or []]
        price_versions = batch.get("price_versions") or []
        for version in process_versions:
            impact = MasterDataImpactService.process_impact(version["process_id"])
            version["release_impact_digest"] = payload_sha256(
                canonical_version_payload("process", version, impact["references"])
            )
        for version in route_versions:
            impact = MasterDataImpactService.route_impact(version["process_route_id"])
            version["release_impact_digest"] = payload_sha256(
                canonical_version_payload("route", version, impact["references"])
            )
        published_process = [
            version["id"]
            for version in ProcessVersionRepository.versions_by_ids(
                [item["process_version_id"] for route in route_versions for item in route.get("items") or []]
            )
            if version.get("status") == "published"
        ]
        selected_process_ids = {int(item["process_id"]) for item in process_versions}
        selected_process_by_root = {int(item["process_id"]): int(item["id"]) for item in process_versions}
        selected_route_ids = {int(item["id"]) for item in route_versions}
        selected_route_root_ids = {
            int(item["process_route_id"]) for item in route_versions
        }
        affected = []
        for route in RouteVersionRepository.current_versions_for_process_ids(selected_process_ids):
            if route["id"] in selected_route_ids or int(route["process_route_id"]) in selected_route_root_ids:
                continue
            for item in route.get("items") or []:
                replacement = selected_process_by_root.get(int(item["process_id"]))
                if replacement and int(item["process_version_id"]) != replacement:
                    affected.append({"route_version_id": route["id"], "process_version_id": replacement})
        return {
            "process_versions": process_versions,
            "route_versions": route_versions,
            "price_versions": price_versions,
            "published_process_version_ids": published_process,
            "published_route_version_ids": [],
            "affected_routes": affected,
            "approved_exceptions": list(exceptions or []),
        }

    @staticmethod
    def _summary_digest(batch_input):
        summary = validate_release_batch_dependencies(batch_input)
        return payload_sha256(summary), summary

    @staticmethod
    def _draft_digest(batch_input):
        return payload_sha256(
            summarize_release_batch(
                process_versions=batch_input.get("process_versions"),
                route_versions=batch_input.get("route_versions"),
                price_versions=batch_input.get("price_versions"),
                approved_exceptions=batch_input.get("approved_exceptions"),
            )
        )

    @staticmethod
    def _validate_price_members(batch, db):
        route_nodes = {
            (int(route["id"]), int(item["process_version_id"]))
            for route in batch.get("route_versions") or []
            for item in route.get("items") or []
        }
        for price in batch.get("price_versions") or []:
            if price["status"] not in {"draft", "approved"}:
                if price["status"] == "voided":
                    raise PriceVersionVoidedError(
                        details={"price_version_id": price["id"]}
                    )
                raise PriceBindingMismatchError(
                    details={
                        "price_version_id": price["id"],
                        "status": price["status"],
                    }
                )
            binding = PayrollRepository.exact_price_binding(
                price["route_version_id"], price["process_version_id"], db
            )
            assert_price_snapshot_current(price, binding)
            price_binding = (
                int(price["route_version_id"]),
                int(price["process_version_id"]),
            )
            if price_binding not in route_nodes:
                raise PriceBindingMismatchError(
                    "工价版本未匹配发布批次中的路线节点",
                    details={"price_version_id": price["id"]},
                )

    @staticmethod
    def _assert_approval_separation(batch, actor):
        members = [
            batch,
            *(batch.get("process_versions") or []),
            *(batch.get("route_versions") or []),
            *(batch.get("price_versions") or []),
        ]
        for member in members:
            assert_separation_of_duties(member.get("created_by"), actor["id"])

    @staticmethod
    def _member_replay(batch_id, action, command, actor, db):
        key = MasterDataReleaseService._key(command)
        replay = (
            MasterDataReleaseRepository.release_member_event_by_idempotency_key(
                key, db=db
            )
        )
        if replay is None:
            return None
        expected = {
            "batch_id": int(batch_id),
            "action": action,
            "member_type": str(command.get("member_type") or ""),
            "member_id": int(command.get("member_id") or 0),
            "replacement_member_id": (
                int(command["replacement_member_id"])
                if command.get("replacement_member_id") is not None
                else None
            ),
            "actor_id": actor["id"],
            "reason": str(command.get("reason") or "").strip(),
        }
        if any(replay.get(field) != value for field, value in expected.items()):
            raise ConflictError("幂等键已用于不同的发布批次成员操作")
        return MasterDataReleaseRepository.batch(batch_id, db=db)

    @staticmethod
    def _mutate_member(batch_id, command, actor_user, action):
        actor = MasterDataReleaseService._actor(actor_user)
        key = MasterDataReleaseService._key(command)
        reason = MasterDataReleaseService._text(command, "reason", "变更原因")
        member_type = str(command.get("member_type") or "").strip()
        if member_type not in MasterDataReleaseRepository.MEMBER_TABLES:
            raise ValidationError("发布批次成员类型无效")
        try:
            member_id = int(command.get("member_id"))
            replacement_member_id = (
                int(command.get("replacement_member_id"))
                if action == "replaced"
                else None
            )
        except (TypeError, ValueError) as exc:
            raise ValidationError("发布批次成员 ID 无效") from exc
        if member_id <= 0 or (
            replacement_member_id is not None and replacement_member_id <= 0
        ):
            raise ValidationError("发布批次成员 ID 无效")
        if replacement_member_id == member_id:
            raise ValidationError("替换成员必须不同于原成员")

        with BaseService.transaction() as db:
            replay = MasterDataReleaseService._member_replay(
                batch_id, action, command, actor, db
            )
            if replay is not None:
                return replay
            batch = MasterDataReleaseRepository.batch(batch_id, db=db)
            if batch is None:
                raise NotFoundError("主数据发布批次不存在")
            if batch["status"] != "draft":
                raise ConflictError("只有草稿发布批次可以修改成员")
            if int(batch["created_by"] or 0) != actor["id"]:
                raise AuthorizationError("仅发布批次制单人可以修改草稿成员")
            expected_row_version = require_row_version(command.get("row_version"))
            if expected_row_version != int(batch["row_version"]):
                raise ConflictError(
                    "主数据发布批次状态已变化，请刷新后重试",
                    details={
                        "expected": expected_row_version,
                        "actual": batch["row_version"],
                    },
                )
            MasterDataReleaseRepository.insert_release_member_event(
                {
                    "batch_id": batch_id,
                    "action": action,
                    "member_type": member_type,
                    "member_id": member_id,
                    "replacement_member_id": replacement_member_id,
                    "actor_id": actor["id"],
                    "actor_name": actor["name"],
                    "reason": reason,
                    "idempotency_key": key,
                },
                db,
            )
            if action == "removed":
                MasterDataReleaseRepository.remove_member(
                    batch_id, member_type, member_id, db
                )
            else:
                MasterDataReleaseRepository.replace_member(
                    batch_id,
                    member_type,
                    member_id,
                    replacement_member_id,
                    db,
                )
            changed = MasterDataReleaseRepository.batch(batch_id, db=db)
            impact_digest = MasterDataReleaseService._draft_digest(
                MasterDataReleaseService._batch_input(
                    changed, changed.get("approved_exceptions")
                )
            )
            return MasterDataReleaseRepository.update_draft_after_member_change(
                batch_id, expected_row_version, impact_digest, db
            )

    @staticmethod
    def remove_member(batch_id, command, actor_user):
        return MasterDataReleaseService._mutate_member(
            batch_id, command, actor_user, "removed"
        )

    @staticmethod
    def replace_member(batch_id, command, actor_user):
        return MasterDataReleaseService._mutate_member(
            batch_id, command, actor_user, "replaced"
        )

    @staticmethod
    def _present_batches(batches):
        presented = []
        process_base_ids = [
            version.get("supersedes_version_id")
            for batch in batches
            for version in batch.get("process_versions") or []
            if version.get("supersedes_version_id")
        ]
        route_base_ids = [
            version.get("supersedes_version_id")
            for batch in batches
            for version in batch.get("route_versions") or []
            if version.get("supersedes_version_id")
        ]
        process_bases = {
            version["id"]: version
            for version in ProcessVersionRepository.versions_by_ids(process_base_ids)
        }
        route_bases = {
            version["id"]: version
            for version in RouteVersionRepository.versions_by_ids(route_base_ids)
        }
        for source in batches:
            batch = dict(source)
            batch["process_versions"] = [dict(version) for version in source.get("process_versions") or []]
            batch["route_versions"] = [dict(version) for version in source.get("route_versions") or []]
            batch["price_versions"] = [dict(version) for version in source.get("price_versions") or []]
            batch["approved_exceptions"] = [dict(item) for item in source.get("approved_exceptions") or []]
            for version in batch["process_versions"]:
                version["comparison_base"] = process_bases.get(version.get("supersedes_version_id"))
            for version in batch["route_versions"]:
                version["comparison_base"] = route_bases.get(version.get("supersedes_version_id"))
            presented.append(batch)
        return presented

    @staticmethod
    def list_batches(status=""):
        batches = MasterDataReleaseRepository.list_batches(str(status or "").strip())
        return MasterDataReleaseService._present_batches(batches)

    @staticmethod
    def get_batch(batch_id):
        batch = MasterDataReleaseRepository.batch(batch_id)
        if batch is None:
            raise NotFoundError("主数据发布批次不存在")
        return MasterDataReleaseService._present_batches([batch])[0]

    @staticmethod
    def _validate_exception(exception, batch, db):
        required = (
            "route_version_id",
            "retained_process_version_id",
            "replacement_process_version_id",
            "approved_by",
            "approved_by_name",
            "valid_from",
            "valid_to",
        )
        missing = [field for field in required if exception.get(field) in (None, "")]
        reason = str(exception.get("reason") or "").strip()
        if missing or not reason:
            raise ValidationError(
                "发布例外字段不完整",
                details={"missing_fields": missing + ([] if reason else ["reason"])},
            )
        try:
            valid_from = datetime.fromisoformat(str(exception["valid_from"]))
            valid_to = datetime.fromisoformat(str(exception["valid_to"]))
        except ValueError as exc:
            raise ValidationError("发布例外有效期格式无效") from exc
        if valid_to <= valid_from:
            raise ValidationError("发布例外失效时间必须晚于生效时间")
        route = RouteVersionRepository.version(exception["route_version_id"], db=db)
        retained = ProcessVersionRepository.version(
            exception["retained_process_version_id"], db=db
        )
        replacement = ProcessVersionRepository.version(
            exception["replacement_process_version_id"], db=db
        )
        if route is None or retained is None or replacement is None:
            raise ValidationError("发布例外引用的路线或工序版本不存在")
        retained_items = {
            int(item["process_version_id"]): int(item["process_id"])
            for item in route.get("items") or []
        }
        retained_process_id = retained_items.get(int(retained["id"]))
        batch_replacements = {int(item["id"]) for item in batch["process_versions"]}
        if (
            retained_process_id is None
            or int(retained["process_id"]) != retained_process_id
            or int(replacement["process_id"]) != retained_process_id
            or int(replacement["id"]) not in batch_replacements
        ):
            raise ValidationError("发布例外的保留版本、替代版本和路线节点不匹配")
        if int(exception["approved_by"]) == int(batch["created_by"]):
            raise ConflictError("发布例外批准人与批次制单人必须不同")
        return {
            **exception,
            "route_version_id": int(route["id"]),
            "retained_process_version_id": int(retained["id"]),
            "replacement_process_version_id": int(replacement["id"]),
            "approved_by": int(exception["approved_by"]),
            "approved_by_name": str(exception["approved_by_name"]).strip(),
            "reason": reason,
            "valid_from": str(exception["valid_from"]).strip(),
            "valid_to": str(exception["valid_to"]).strip(),
        }

    @staticmethod
    def create_batch(command, actor_user):
        actor = MasterDataReleaseService._actor(actor_user)
        key = MasterDataReleaseService._key(command)
        reason = MasterDataReleaseService._text(command, "revision_reason", "发布原因")
        with BaseService.transaction() as db:
            replay = MasterDataReleaseRepository.batch_by_idempotency_key(key, db=db)
            if replay is not None:
                return replay
            batch = MasterDataReleaseRepository.create_batch(
                {
                    "release_no": MasterDataReleaseService._text(command, "release_no", "发布批次号"),
                    "revision_reason": reason,
                    "created_by": actor["id"],
                    "created_by_name": actor["name"],
                    "idempotency_key": key,
                }, db
            )
            existing_process = {item["id"] for item in batch["process_versions"]}
            existing_route = {item["id"] for item in batch["route_versions"]}
            existing_price = {item["id"] for item in batch["price_versions"]}
            for version_id in command.get("process_version_ids") or []:
                if int(version_id) not in existing_process:
                    MasterDataReleaseRepository.add_process_version(batch["id"], int(version_id), db)
                    MasterDataReleaseRepository.insert_release_member_event(
                        {
                            "batch_id": batch["id"],
                            "action": "added",
                            "member_type": "process_version",
                            "member_id": int(version_id),
                            "actor_id": actor["id"],
                            "actor_name": actor["name"],
                            "reason": reason,
                            "idempotency_key": f"{key}:member:process_version:{int(version_id)}:added",
                        },
                        db,
                    )
            for version_id in command.get("route_version_ids") or []:
                if int(version_id) not in existing_route:
                    MasterDataReleaseRepository.add_route_version(batch["id"], int(version_id), db)
                    MasterDataReleaseRepository.insert_release_member_event(
                        {
                            "batch_id": batch["id"],
                            "action": "added",
                            "member_type": "route_version",
                            "member_id": int(version_id),
                            "actor_id": actor["id"],
                            "actor_name": actor["name"],
                            "reason": reason,
                            "idempotency_key": f"{key}:member:route_version:{int(version_id)}:added",
                        },
                        db,
                    )
            for version_id in command.get("price_version_ids") or []:
                if int(version_id) not in existing_price:
                    MasterDataReleaseRepository.add_price_version(batch["id"], int(version_id), db)
                    MasterDataReleaseRepository.insert_release_member_event(
                        {
                            "batch_id": batch["id"],
                            "action": "added",
                            "member_type": "price_version",
                            "member_id": int(version_id),
                            "actor_id": actor["id"],
                            "actor_name": actor["name"],
                            "reason": reason,
                            "idempotency_key": f"{key}:member:price_version:{int(version_id)}:added",
                        },
                        db,
                    )
            return MasterDataReleaseRepository.batch(batch["id"], db=db)

    @staticmethod
    def submit(batch_id, command, actor_user):
        actor = MasterDataReleaseService._actor(actor_user)
        key = MasterDataReleaseService._key(command)
        with BaseService.transaction() as db:
            batch = MasterDataReleaseRepository.batch(batch_id, db=db)
            if batch is None:
                raise NotFoundError("主数据发布批次不存在")
            if batch["status"] == "pending_approval":
                return batch
            if batch["status"] != "draft":
                raise ConflictError("只有草稿发布批次可以提交")
            exceptions = batch.get("approved_exceptions") or []
            for exception in command.get("approved_exceptions") or []:
                normalized = MasterDataReleaseService._validate_exception(
                    exception, batch, db
                )
                MasterDataReleaseRepository.add_approved_exception(
                    batch_id, normalized, db
                )
            batch = MasterDataReleaseRepository.batch(batch_id, db=db)
            MasterDataReleaseService._validate_price_members(batch, db)
            digest, _ = MasterDataReleaseService._summary_digest(
                MasterDataReleaseService._batch_input(batch, batch.get("approved_exceptions"))
            )
            return MasterDataReleaseRepository.transition_batch(
                batch_id,
                "draft",
                int(command.get("row_version", batch["row_version"])),
                "pending_approval",
                {"impact_digest": digest},
                db,
            )

    @staticmethod
    def approve(batch_id, command, actor_user):
        actor = MasterDataReleaseService._actor(actor_user)
        key = MasterDataReleaseService._key(command)
        with BaseService.transaction() as db:
            batch = MasterDataReleaseRepository.batch(batch_id, db=db)
            if batch is None:
                raise NotFoundError("主数据发布批次不存在")
            if batch["status"] == "published":
                return batch
            if batch["status"] != "pending_approval":
                raise ConflictError("只有待审批发布批次可以批准")
            expected_row_version = require_row_version(command.get("row_version"))
            if expected_row_version != int(batch["row_version"]):
                raise ConflictError("主数据发布批次状态已变化，请刷新后重试")
            MasterDataReleaseService._validate_price_members(batch, db)
            MasterDataReleaseService._assert_approval_separation(batch, actor)
            digest, _ = MasterDataReleaseService._summary_digest(
                MasterDataReleaseService._batch_input(batch, batch.get("approved_exceptions"))
            )
            if digest != batch.get("impact_digest", ""):
                raise ConflictError(
                    "发布批次影响范围已变化，请重新提交",
                    details={
                        "submitted_impact_digest": batch.get("impact_digest", ""),
                        "current_impact_digest": digest,
                    },
                )
            from modules.services.process_version_service import ProcessVersionService
            from modules.services.route_version_service import RouteVersionService

            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            process_versions = sorted(batch["process_versions"], key=lambda item: (item["process_id"], item["version"], item["id"]))
            route_versions = sorted(batch["route_versions"], key=lambda item: (item["process_route_id"], item["version"], item["id"]))
            available_price_ids = [
                int(item["id"]) for item in batch["price_versions"]
            ]
            route_command = {
                **command,
                "_available_price_version_ids": available_price_ids,
            }
            for version in process_versions:
                current = ProcessVersionRepository.version(version["id"], db=db)
                if current["status"] == "pending_approval":
                    ProcessVersionService._publish_pending(
                        current,
                        actor,
                        db,
                        f"{key}:process:{current['id']}",
                        check_impact=False,
                    )
            for version in route_versions:
                current = RouteVersionRepository.version(version["id"], db=db)
                if current["status"] == "pending_approval":
                    RouteVersionService._publish_pending(
                        current,
                        actor,
                        db,
                        f"{key}:route:{current['id']}",
                        route_command,
                        check_impact=False,
                    )
            for price in sorted(batch["price_versions"], key=lambda item: item["id"]):
                current = PayrollRepository.price_version(price["id"], db=db)
                if current["status"] == "approved":
                    continue
                if current["status"] != "draft":
                    raise ConflictError("发布批次中的工价版本不是可批准草稿")
                assert_separation_of_duties(current["created_by"], actor["id"])
                PayrollRepository.close_prior_price_version(
                    current["id"],
                    current["route_version_id"],
                    current["process_version_id"],
                    current["valid_from"],
                    db,
                )
                PayrollRepository.approve_price_version(
                    current["id"],
                    current["row_version"],
                    {
                        "approved_by": actor["id"],
                        "approved_by_name": actor["name"],
                    },
                    db,
                )
                PayrollRepository.insert_event(
                    {
                        "event_type": "price_version_approved",
                        "operator_id": actor["id"],
                        "operator_name": actor["name"],
                        "idempotency_key": f"{key}:price:{current['id']}",
                        "payload": {
                            "price_version_id": current["id"],
                            "master_data_release_batch_id": batch_id,
                        },
                    },
                    db,
                )
            return MasterDataReleaseRepository.transition_batch(
                batch_id,
                "pending_approval",
                expected_row_version,
                "published",
                {
                    "approved_by": actor["id"],
                    "approved_by_name": actor["name"],
                    "approved_at": now,
                    "published_at": now,
                },
                db,
            )

    @staticmethod
    def reject(batch_id, command, actor_user):
        actor = MasterDataReleaseService._actor(actor_user)
        MasterDataReleaseService._key(command)
        MasterDataReleaseService._text(command, "reason", "驳回原因")
        with BaseService.transaction() as db:
            batch = MasterDataReleaseRepository.batch(batch_id, db=db)
            if batch is None:
                raise NotFoundError("主数据发布批次不存在")
            if batch["status"] == "rejected":
                return batch
            if batch["status"] != "pending_approval":
                raise ConflictError("只有待审批发布批次可以驳回")
            assert_separation_of_duties(batch["created_by"], actor["id"])
            return MasterDataReleaseRepository.transition_batch(
                batch_id,
                "pending_approval",
                require_row_version(command.get("row_version")),
                "rejected",
                {
                    "approved_by": actor["id"],
                    "approved_by_name": actor["name"],
                    "approved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                },
                db,
            )
