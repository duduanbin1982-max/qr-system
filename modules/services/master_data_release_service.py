"""Atomic, dependency-aware publication of process master-data batches."""

from datetime import datetime

from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.domain.process_versioning import (
    assert_separation_of_duties,
    canonical_version_payload,
    payload_sha256,
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
            for version_id in command.get("route_version_ids") or []:
                if int(version_id) not in existing_route:
                    MasterDataReleaseRepository.add_route_version(batch["id"], int(version_id), db)
            for version_id in command.get("price_version_ids") or []:
                if int(version_id) not in existing_price:
                    MasterDataReleaseRepository.add_price_version(batch["id"], int(version_id), db)
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
            assert_separation_of_duties(batch["created_by"], actor["id"])
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
                        command,
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
                    current["route_id"],
                    current["process_id"],
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
                int(command.get("row_version", batch["row_version"])),
                "published",
                {
                    "approved_by": actor["id"],
                    "approved_by_name": actor["name"],
                    "approved_at": now,
                    "published_at": now,
                },
                db,
            )
