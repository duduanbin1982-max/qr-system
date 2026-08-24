"""Approved, time-effective route price versions for payroll."""

import json
import sqlite3

from modules import config
from modules.domain.errors import AuthorizationError, NotFoundError
from modules.domain.payroll_policy import normalize_timestamp, yuan_to_micros
from modules.domain.price_versioning import (
    GroupReleaseRequiredError,
    IdempotencyConflictError,
    PendingRoutePriceWriteDisabledError,
    PriceBindingMismatchError,
    PriceVersionVoidedError,
    ProcessVersionNotFrozenError,
    assert_exact_price_binding,
    assert_expected_digest,
    assert_price_snapshot_current,
    pricing_mode,
)
from modules.domain.process_versioning import payload_sha256
from modules.repositories.payroll_repository import PayrollRepository
from modules.services import BaseService


class PriceVersionService:
    @staticmethod
    def _actor(actor_user):
        actor = actor_user or {}
        return actor.get("id"), actor.get("name") or actor.get("username") or "system"

    @staticmethod
    def _request_values(data):
        try:
            route_id = int(data.get("route_id"))
            process_id = int(data.get("process_id"))
            route_version_id = int(data.get("route_version_id"))
            process_version_id = int(data.get("process_version_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("路线版本和工序版本必须有效") from exc
        normal_micros = data.get("normal_unit_price_micros")
        if normal_micros is None:
            normal_micros = yuan_to_micros(data.get("normal_unit_price"))
        else:
            normal_micros = int(normal_micros)
            if normal_micros <= 0:
                raise ValueError("工价必须大于 0")
        rate = data.get("rework_rate_basis_points")
        configured = 0
        if rate is None and data.get("rework_rate_percent") is not None:
            rate = round(float(data["rework_rate_percent"]) * 100)
        if rate is not None:
            rate = int(rate)
            if not 0 <= rate <= 10000:
                raise ValueError("返工倍率必须在 0 到 10000 之间")
            configured = 1
        valid_from = normalize_timestamp(data.get("valid_from"), "生效时间")
        key = str(data.get("idempotency_key") or "").strip()
        if not key:
            raise ValueError("缺少幂等键")
        values = {
            "route_id": route_id,
            "route_version_id": route_version_id,
            "process_id": process_id,
            "process_version_id": process_version_id,
            "normal_unit_price_micros": normal_micros,
            "rework_rate_basis_points": rate or 0,
            "rework_rate_configured": configured,
            "valid_from": valid_from,
            "remark": str(data.get("remark") or "").strip(),
            "idempotency_key": key,
        }
        values["request_digest"] = payload_sha256({
            field: value for field, value in values.items() if field != "idempotency_key"
        })
        return values

    @staticmethod
    def _response(version, binding):
        result = dict(version)
        mode = pricing_mode(binding["route_version_status"])
        result["pricing_mode"] = mode
        result["approval_mode"] = (
            "grouped_release_only"
            if mode == "pending_group_release"
            else "independent_approval"
        )
        result["route_version_status"] = binding["route_version_status"]
        result["process_version_status"] = binding["process_version_status"]
        return result

    @staticmethod
    def create(data, actor_user):
        actor_id, actor_name = PriceVersionService._actor(actor_user)
        values = PriceVersionService._request_values(data)
        with BaseService.transaction() as db:
            existing = PayrollRepository.price_version_by_idempotency_key(
                values["idempotency_key"], db=db
            )
            if existing is not None:
                if existing["request_digest"] != values["request_digest"]:
                    raise IdempotencyConflictError()
                binding = PayrollRepository.exact_price_binding(
                    existing["route_version_id"], existing["process_version_id"], db
                )
                return PriceVersionService._response(existing, binding)

            binding = PayrollRepository.exact_price_binding(
                values["route_version_id"], values["process_version_id"], db
            )
            assert_exact_price_binding(binding, values["route_id"], values["process_id"])
            assert_expected_digest(
                data.get("expected_route_content_digest"), binding["route_content_digest"]
            )
            assert_expected_digest(
                data.get("expected_process_content_digest"),
                binding["process_content_digest"],
            )
            mode = pricing_mode(binding["route_version_status"])
            process_status = binding["process_version_status"]
            if process_status not in {"published", "pending_approval"}:
                raise ProcessVersionNotFrozenError(
                    details={"process_version_id": values["process_version_id"]}
                )
            if mode == "published_adjustment" and process_status != "published":
                raise PriceBindingMismatchError(
                    details={"process_version_id": values["process_version_id"]}
                )
            if mode == "pending_group_release":
                if not config.ROUTE_PRICE_PENDING_WRITE_ENABLED:
                    raise PendingRoutePriceWriteDisabledError()
                duplicate = PayrollRepository.draft_price_for_binding(
                    values["route_version_id"], values["process_version_id"], db
                )
                if duplicate is not None:
                    raise PriceBindingMismatchError(
                        "待发布路线节点已有工价草稿，请先作废原草稿",
                        details={"price_version_id": duplicate["id"]},
                    )

            create_payload = {
                **values,
                "route_content_digest_snapshot": binding["route_content_digest"],
                "process_content_digest_snapshot": binding["process_content_digest"],
                "created_by": actor_id,
                "created_by_name": actor_name,
            }
            try:
                version_id = PayrollRepository.create_price_version(create_payload, db)
            except sqlite3.IntegrityError as exc:
                replay = PayrollRepository.price_version_by_idempotency_key(
                    values["idempotency_key"], db=db
                )
                if replay is None:
                    raise
                if replay["request_digest"] != values["request_digest"]:
                    raise IdempotencyConflictError() from exc
                return PriceVersionService._response(replay, binding)
            PayrollRepository.insert_event(
                {
                    "event_type": "price_version_created",
                    "operator_id": actor_id,
                    "operator_name": actor_name,
                    "idempotency_key": values["idempotency_key"] + ":created",
                    "payload": {
                        "price_version_id": version_id,
                        "route_id": values["route_id"],
                        "route_version_id": values["route_version_id"],
                        "process_id": values["process_id"],
                        "process_version_id": values["process_version_id"],
                        "request_digest": values["request_digest"],
                    },
                },
                db,
            )
            return PriceVersionService._response(
                PayrollRepository.price_version(version_id, db), binding
            )

    @staticmethod
    def approve(version_id, actor_user, expected_row_version):
        actor_id, actor_name = PriceVersionService._actor(actor_user)
        try:
            expected_row_version = int(expected_row_version)
        except (TypeError, ValueError) as exc:
            raise ValueError("缺少有效的 row_version") from exc
        with BaseService.transaction() as db:
            version = PayrollRepository.price_version(version_id, db)
            if not version:
                raise NotFoundError("工价版本不存在")
            if version["status"] == "voided":
                raise PriceVersionVoidedError(details={"price_version_id": version_id})
            if version["status"] != "draft":
                raise ValueError("只有草稿工价可以批准")
            binding = PayrollRepository.exact_price_binding(
                version["route_version_id"], version["process_version_id"], db
            )
            if binding is None:
                raise PriceBindingMismatchError(details={"price_version_id": version_id})
            if binding["route_version_status"] != "published":
                raise GroupReleaseRequiredError(details={"price_version_id": version_id})
            if binding["process_version_status"] != "published":
                raise ProcessVersionNotFrozenError(
                    details={"process_version_id": version["process_version_id"]}
                )
            assert_price_snapshot_current(version, binding)
            if version.get("created_by") == actor_id:
                raise ValueError("工价制单人与审批人必须不同")
            PayrollRepository.close_prior_price_version(
                version_id,
                version["route_version_id"],
                version["process_version_id"],
                version["valid_from"],
                db,
            )
            PayrollRepository.approve_price_version(
                version_id,
                expected_row_version,
                {"approved_by": actor_id, "approved_by_name": actor_name},
                db,
            )
            PayrollRepository.insert_event(
                {
                    "event_type": "price_version_approved",
                    "operator_id": actor_id,
                    "operator_name": actor_name,
                    "payload": {"price_version_id": version_id},
                },
                db,
            )
            return PayrollRepository.price_version(version_id, db)

    @staticmethod
    def void(version_id, data, actor_user):
        actor_id, actor_name = PriceVersionService._actor(actor_user)
        try:
            expected_row_version = int(data.get("row_version"))
        except (TypeError, ValueError) as exc:
            raise ValueError("缺少有效的 row_version") from exc
        reason = str(data.get("reason") or "").strip()
        key = str(data.get("idempotency_key") or "").strip()
        if len(reason) < 2:
            raise ValueError("作废原因至少需要 2 个字符")
        if not key:
            raise ValueError("缺少幂等键")
        request_digest = payload_sha256(
            {
                "price_version_id": int(version_id),
                "row_version": expected_row_version,
                "reason": reason,
                "actor_id": actor_id,
            }
        )
        with BaseService.transaction() as db:
            replay_event = PayrollRepository.event_by_idempotency_key(key, db=db)
            if replay_event is not None:
                payload = json.loads(replay_event.get("payload_json") or "{}")
                if payload.get("request_digest") != request_digest:
                    raise IdempotencyConflictError()
                return PayrollRepository.price_version(version_id, db)
            version = PayrollRepository.price_version(version_id, db)
            if not version:
                raise NotFoundError("工价版本不存在")
            if version["status"] == "voided":
                raise PriceVersionVoidedError(details={"price_version_id": version_id})
            if version["status"] != "draft":
                raise ValueError("只有草稿工价可以作废")
            if version.get("created_by") != actor_id:
                raise AuthorizationError("仅工价制单人可作废自己的草稿")
            voided = PayrollRepository.void_price_version(
                version_id,
                expected_row_version,
                {
                    "voided_by": actor_id,
                    "voided_by_name": actor_name,
                    "void_reason": reason,
                },
                db,
            )
            PayrollRepository.insert_event(
                {
                    "event_type": "price_version_voided",
                    "operator_id": actor_id,
                    "operator_name": actor_name,
                    "reason": reason,
                    "idempotency_key": key,
                    "payload": {
                        "price_version_id": version_id,
                        "request_digest": request_digest,
                    },
                },
                db,
            )
            return voided

    @staticmethod
    def list_versions(
        route_id=None, status="", route_version_id=None, process_version_id=None
    ):
        return PayrollRepository.list_price_versions(
            route_id,
            status,
            route_version_id=route_version_id,
            process_version_id=process_version_id,
        )

    @staticmethod
    def reference_items(include_pending=False):
        pending_enabled = bool(
            include_pending and config.ROUTE_PRICE_PENDING_REFERENCE_ENABLED
        )
        if not config.ROUTE_PRICE_PENDING_COMPAT_AUDIT_ENABLED:
            return PayrollRepository.list_route_process_references(
                include_pending=pending_enabled
            )
        with BaseService.transaction() as db:
            legacy = PayrollRepository.list_legacy_route_process_reference_identities(db=db)
            items = PayrollRepository.list_route_process_references(
                include_pending=pending_enabled, db=db
            )
            published = [
                {
                    "route_id": row["route_id"],
                    "route_version_id": row["route_version_id"],
                    "process_id": row["process_id"],
                    "process_version_id": row["process_version_id"],
                    "seq_order": row["seq_order"],
                }
                for row in items
                if row["route_version_status"] == "published"
            ]
            legacy_digest = payload_sha256(legacy)
            versioned_digest = payload_sha256(published)
            PayrollRepository.record_reference_compat_audit(
                legacy_digest, versioned_digest, db
            )
            return items
