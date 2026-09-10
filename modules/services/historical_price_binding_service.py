"""Business-facing workflow for historical exact-price confirmations.

The controlled V083 repair manifest deliberately uses internal keys such as
``manual:<route-version>:<process-version>``.  Those keys are useful audit
evidence, but are not meaningful to a payroll preparer.  This service turns
the immutable preflight evidence into an order/product/route/process review
screen and keeps every internal key inside the server-side workflow.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json

from modules.domain.errors import AuthorizationError, ConflictError, NotFoundError
from modules.domain.payroll_policy import normalize_timestamp, require_row_version, yuan_to_micros
from modules.domain.process_versioning import payload_sha256
from modules.repositories.historical_price_binding_repository import HistoricalPriceBindingRepository
from modules.repositories.payroll_repository import PayrollRepository
from modules.services import BaseService


def _canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value):
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _actor(actor_user):
    actor = actor_user or {}
    actor_id = actor.get("id")
    if not actor_id:
        raise AuthorizationError("当前登录人无效")
    return int(actor_id), actor.get("name") or actor.get("username") or "system"


def _timestamp_now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class HistoricalPriceBindingService:
    """Create and independently approve readable manual historical prices."""

    @staticmethod
    def _parent_item(review_id, db, *, include_resolved=False):
        item = HistoricalPriceBindingRepository.parent_item(
            review_id, db, include_resolved=include_resolved
        )
        if not item:
            raise NotFoundError("历史工价人工确认项不存在或已完成")
        if item["source_run_status"] not in {"partially_applied", "applied"}:
            raise ConflictError("历史工价修复项尚未完成预检，暂不能人工确认")
        return item

    @staticmethod
    def _current_fact_rows(item, db):
        """Read the still-unpriced facts using the same shape as V083 preflight."""
        return HistoricalPriceBindingRepository.current_fact_rows(item, db)

    @staticmethod
    def _fact_evidence(rows):
        records = [
            {
                "id": int(row["work_record_id"]),
                "order_id": int(row["order_id"]),
                "order_no": str(row["order_no"]),
                "quantity": int(row["quantity"] or 0),
                "created_at": row["created_at"],
                "route_id": int(row["route_id"] or 0),
                "route_version_id": int(row["route_version_id"] or 0),
                "process_id": int(row["process_id"] or 0),
                "process_version_id": int(row["process_version_id"] or 0),
            }
            for row in rows
        ]
        return {
            "work_record_count": len(records),
            "quantity": sum(record["quantity"] for record in records),
            "work_record_digest": _digest(records),
        }

    @staticmethod
    def _assert_evidence_current(item, db):
        rows = HistoricalPriceBindingService._current_fact_rows(item, db)
        evidence = HistoricalPriceBindingService._fact_evidence(rows)
        expected = {
            "work_record_count": int(item["affected_work_record_count"]),
            "quantity": int(item["affected_quantity"]),
            "work_record_digest": item["affected_work_record_digest"],
        }
        if evidence != expected:
            raise ConflictError(
                "报工事实或精确版本绑定已变化，请重新执行历史工价预检后再确认",
                details={"expected": expected, "actual": evidence},
            )
        binding = PayrollRepository.exact_price_binding(
            item["target_route_version_id"], item["target_process_version_id"], db
        )
        if not binding or (
            binding["route_id"] != item["target_route_id"]
            or binding["process_id"] != item["target_process_id"]
            or binding["route_content_digest"] != item["target_route_content_digest"]
            or binding["process_content_digest"] != item["target_process_content_digest"]
        ):
            raise ConflictError("路线或工序版本内容已变化，请重新预检后确认")
        if binding["route_version_status"] != "superseded":
            raise ConflictError("该历史路线版本状态已变化，不能按历史工价确认")
        if binding["process_version_status"] != "published":
            raise ConflictError("该历史工序版本不是已发布状态，不能按历史工价确认")
        return rows, binding

    @staticmethod
    def _affected_orders(rows):
        grouped = {}
        for row in rows:
            key = (int(row["order_id"]), str(row["order_no"]))
            current = grouped.setdefault(key, {
                "order_id": key[0], "order_no": key[1],
                "product_code": str(row.get("product_code") or ""),
                "product_name": str(row.get("product_name") or ""),
                "work_record_count": 0, "quantity": 0,
                "first_work_at": row["created_at"], "last_work_at": row["created_at"],
            })
            current["work_record_count"] += 1
            current["quantity"] += int(row["quantity"] or 0)
            current["first_work_at"] = min(current["first_work_at"], row["created_at"])
            current["last_work_at"] = max(current["last_work_at"], row["created_at"])
        return list(grouped.values())

    @staticmethod
    def _candidates(item, db):
        # Candidate values are informational only.  Selecting one never creates
        # an automatic price link or implies that it is correct for this route.
        return HistoricalPriceBindingRepository.candidates(item, db)

    @staticmethod
    def _drafts(review_id, db):
        return HistoricalPriceBindingRepository.drafts(review_id, db)

    @staticmethod
    def _draft_payload(draft):
        """Return only the fields a preparer or approver may see.

        The database record intentionally also contains the repair-item foreign
        key, idempotency key and request digest.  Those are audit controls, not
        UI concepts, so never let a route accidentally serialise the raw database row.
        """
        if not draft:
            return None
        visible = (
            "id", "status", "normal_unit_price_micros",
            "rework_rate_basis_points", "rework_rate_configured",
            "valid_from", "valid_to", "confirmation_reason",
            "created_by", "created_by_name", "created_at",
            "approved_by", "approved_by_name", "approved_at",
            "voided_by", "voided_by_name", "voided_at", "void_reason",
            "row_version", "price_version_id",
        )
        return {field: draft.get(field) for field in visible}

    @staticmethod
    def _review_payload(item, db):
        rows = HistoricalPriceBindingService._current_fact_rows(item, db)
        route = HistoricalPriceBindingRepository.route_version(item["target_route_version_id"], db)
        process = HistoricalPriceBindingRepository.process_version(item["target_process_version_id"], db)
        first_work_at = min((row["created_at"] for row in rows), default="")
        last_work_at = max((row["created_at"] for row in rows), default="")
        return {
            "review_id": int(item["id"]),
            "status": "待人工确认",
            "route": {
                "name": (route["name"] if route else ""),
                "version": (route["version"] if route else ""),
                "category": (route["category"] if route else ""),
            },
            "process": {
                "name": (process["name"] if process else ""),
                "version": (process["version"] if process else ""),
            },
            "affected_orders": HistoricalPriceBindingService._affected_orders(rows),
            "evidence": {
                "work_record_count": len(rows),
                "quantity": sum(int(row["quantity"] or 0) for row in rows),
                "first_work_at": first_work_at,
                "last_work_at": last_work_at,
            },
            "candidate_prices": HistoricalPriceBindingService._candidates(item, db),
            "drafts": [
                HistoricalPriceBindingService._draft_payload(draft)
                for draft in HistoricalPriceBindingService._drafts(item["id"], db)
            ],
        }

    @staticmethod
    def list_manual_reviews():
        with BaseService.transaction() as db:
            rows = HistoricalPriceBindingRepository.list_manual_items(db)
            items = []
            for row in rows:
                payload = HistoricalPriceBindingService._review_payload(row, db)
                # A completed manual item remains immutable evidence, but once
                # an exact approved price covers all of its facts there is no
                # longer an operator action to perform.  Keep it out of the
                # "待确认" queue without deleting the audit trail.
                if payload["evidence"]["work_record_count"]:
                    items.append(payload)
            return {"items": items}

    @staticmethod
    def _draft_values(data, review_id):
        try:
            normal_unit_price_micros = yuan_to_micros(data.get("normal_unit_price"))
        except ValueError:
            raise
        if normal_unit_price_micros <= 0:
            raise ValueError("工价必须大于 0")
        configured = bool(data.get("rework_rate_configured"))
        rate = 0
        if configured:
            try:
                rate = round(float(data.get("rework_rate_percent")) * 100)
            except (TypeError, ValueError) as exc:
                raise ValueError("返工倍率格式无效") from exc
            if not 0 <= rate <= 10000:
                raise ValueError("返工倍率必须在 0% 到 100% 之间")
        valid_from = normalize_timestamp(data.get("valid_from"), "生效时间")
        valid_to = data.get("valid_to")
        valid_to = normalize_timestamp(valid_to, "失效时间") if valid_to else None
        if valid_to and valid_to <= valid_from:
            raise ValueError("失效时间必须晚于生效时间")
        reason = str(data.get("confirmation_reason") or "").strip()
        if len(reason) < 2:
            raise ValueError("确认理由至少需要 2 个字符")
        key = str(data.get("idempotency_key") or "").strip()
        if not key:
            raise ValueError("缺少幂等键")
        values = {
            "repair_item_id": int(review_id),
            "normal_unit_price_micros": normal_unit_price_micros,
            "rework_rate_basis_points": rate,
            "rework_rate_configured": int(configured),
            "valid_from": valid_from,
            "valid_to": valid_to,
            "confirmation_reason": reason,
            "idempotency_key": key,
        }
        values["request_digest"] = payload_sha256({
            field: value for field, value in values.items() if field != "idempotency_key"
        })
        return values

    @staticmethod
    def create_draft(review_id, data, actor_user):
        actor_id, actor_name = _actor(actor_user)
        values = HistoricalPriceBindingService._draft_values(data, review_id)
        with BaseService.transaction() as db:
            item = HistoricalPriceBindingService._parent_item(review_id, db)
            HistoricalPriceBindingService._assert_evidence_current(item, db)
            replay = HistoricalPriceBindingRepository.draft_by_idempotency(
                values["idempotency_key"], db
            )
            if replay:
                if replay["request_digest"] != values["request_digest"]:
                    raise ConflictError("幂等键已用于不同的工价确认请求")
                return {
                    "draft": HistoricalPriceBindingService._draft_payload(replay),
                    "replayed": True,
                }
            open_draft = HistoricalPriceBindingRepository.open_draft(review_id, db)
            if open_draft:
                raise ConflictError("该历史工序已有待批准的人工工价草稿，请先作废或由独立审批人处理")
            draft_id = HistoricalPriceBindingRepository.insert_draft(
                values, actor_id, actor_name, db
            )
            PayrollRepository.insert_event({
                "event_type": "historical_price_manual_draft_created",
                "operator_id": actor_id, "operator_name": actor_name,
                "idempotency_key": values["idempotency_key"] + ":event",
                "payload": {"manual_review_id": int(review_id), "draft_id": draft_id},
            }, db)
            draft = HistoricalPriceBindingRepository.draft(draft_id, db)
            return {
                "draft": HistoricalPriceBindingService._draft_payload(draft),
                "replayed": False,
            }

    @staticmethod
    def void_draft(draft_id, data, actor_user):
        actor_id, actor_name = _actor(actor_user)
        reason = str(data.get("reason") or "").strip()
        if len(reason) < 2:
            raise ValueError("作废原因至少需要 2 个字符")
        key = str(data.get("idempotency_key") or "").strip()
        if not key:
            raise ValueError("缺少幂等键")
        expected_row_version = require_row_version(data.get("row_version"))
        request_digest = payload_sha256({
            "draft_id": int(draft_id), "row_version": expected_row_version,
            "reason": reason, "actor_id": actor_id,
        })
        with BaseService.transaction() as db:
            replay_event = PayrollRepository.event_by_idempotency_key(key, db)
            if replay_event:
                payload = json.loads(replay_event.get("payload_json") or "{}")
                if payload.get("request_digest") != request_digest:
                    raise ConflictError("幂等键已用于不同的作废请求")
                row = HistoricalPriceBindingRepository.draft(draft_id, db)
                return {
                    "draft": HistoricalPriceBindingService._draft_payload(row),
                    "replayed": True,
                }
            draft = HistoricalPriceBindingRepository.draft(draft_id, db)
            if not draft:
                raise NotFoundError("历史人工工价草稿不存在")
            if draft["status"] != "draft":
                raise ConflictError("只有待批准的人工工价草稿可以作废")
            if int(draft["created_by"]) != actor_id:
                raise AuthorizationError("仅制单人可作废自己的历史工价草稿")
            if HistoricalPriceBindingRepository.void_draft(
                draft_id, actor_id, actor_name, _timestamp_now(), reason,
                expected_row_version, db
            ) != 1:
                raise ConflictError("草稿状态已变化，请刷新后重试")
            PayrollRepository.insert_event({
                "event_type": "historical_price_manual_draft_voided",
                "operator_id": actor_id, "operator_name": actor_name,
                "reason": reason, "idempotency_key": key,
                "payload": {"draft_id": int(draft_id), "request_digest": request_digest},
            }, db)
            row = HistoricalPriceBindingRepository.draft(draft_id, db)
            return {
                "draft": HistoricalPriceBindingService._draft_payload(row),
                "replayed": False,
            }

    @staticmethod
    def _assert_interval_available(item, draft, db):
        overlap = HistoricalPriceBindingRepository.overlap(item, draft, db)
        if overlap:
            raise ConflictError(
                "该路线版本和工序版本在所填生效区间已有已批准工价；请调整生效区间，不会自动覆盖历史工价",
                details={"existing_valid_from": overlap["valid_from"], "existing_valid_to": overlap["valid_to"]},
            )

    @staticmethod
    def approve_draft(draft_id, data, actor_user):
        approver_id, approver_name = _actor(actor_user)
        expected_row_version = require_row_version(data.get("row_version"))
        key = str(data.get("idempotency_key") or "").strip()
        if not key:
            raise ValueError("缺少幂等键")
        with BaseService.transaction() as db:
            replay_run = HistoricalPriceBindingRepository.repair_run_by_idempotency(key, db)
            if replay_run:
                replay_manifest = json.loads(replay_run["manifest_json"] or "{}")
                if int(replay_manifest.get("manual_draft_id") or 0) != int(draft_id):
                    raise ConflictError("幂等键已用于其他历史工价批准")
                draft = HistoricalPriceBindingRepository.draft(draft_id, db)
                return {
                    "draft": HistoricalPriceBindingService._draft_payload(draft),
                    "replayed": True,
                }

            draft = HistoricalPriceBindingRepository.draft(draft_id, db)
            if not draft:
                raise NotFoundError("历史人工工价草稿不存在")
            if draft["status"] != "draft":
                raise ConflictError("只有待批准的人工工价草稿可以批准")
            if int(draft["row_version"]) != expected_row_version:
                raise ConflictError("草稿状态已变化，请刷新后重试")
            if int(draft["created_by"]) == approver_id:
                raise AuthorizationError("历史工价制单人与批准人必须不同")
            item = HistoricalPriceBindingService._parent_item(draft["repair_item_id"], db)
            rows, binding = HistoricalPriceBindingService._assert_evidence_current(item, db)
            HistoricalPriceBindingService._assert_interval_available(item, draft, db)

            now = _timestamp_now()
            evidence = HistoricalPriceBindingService._fact_evidence(rows)
            manifest = {
                "schema": "qr-system-historical-price-manual-confirmation/v1",
                "manual_draft_id": int(draft_id),
                "manual_review_id": int(item["id"]),
                "target": {
                    "route_id": item["target_route_id"],
                    "route_version_id": item["target_route_version_id"],
                    "process_id": item["target_process_id"],
                    "process_version_id": item["target_process_version_id"],
                    "route_content_digest": item["target_route_content_digest"],
                    "process_content_digest": item["target_process_content_digest"],
                },
                "price": {
                    "normal_unit_price_micros": draft["normal_unit_price_micros"],
                    "rework_rate_basis_points": draft["rework_rate_basis_points"],
                    "rework_rate_configured": draft["rework_rate_configured"],
                    "valid_from": draft["valid_from"], "valid_to": draft["valid_to"],
                },
                "evidence": evidence,
                "approval": {
                    "operator_id": draft["created_by"], "operator_name": draft["created_by_name"],
                    "approver_id": approver_id, "approver_name": approver_name,
                    "approved_at": now, "reason": draft["confirmation_reason"],
                    "idempotency_key": key,
                },
            }
            manifest_digest = _digest(manifest)
            before_summary = _canonical_json({"manual_review_id": int(item["id"]), **evidence})
            user_version = HistoricalPriceBindingRepository.user_version(db)
            run_id = HistoricalPriceBindingRepository.insert_repair_run(
                {
                    "idempotency_key": key,
                    "manifest_digest": manifest_digest,
                    "operator_id": draft["created_by"],
                    "operator_name": draft["created_by_name"],
                    "approver_id": approver_id,
                    "approver_name": approver_name,
                    "approved_at": now,
                    "reason": draft["confirmation_reason"],
                    "source_user_version": user_version,
                    "target_user_version": user_version,
                    "before_summary_json": before_summary,
                    "after_summary_json": "{}",
                    "manifest_json": _canonical_json(manifest),
                },
                db,
            )
            repair_item_key = f"manual-approved:{item['id']}:{draft_id}"
            repair_item_id = HistoricalPriceBindingRepository.insert_repair_item(
                {
                    "run_id": run_id,
                    "item_key": repair_item_key,
                    "action": "manual",
                    "source_price_version_id": None,
                    "target_route_id": item["target_route_id"],
                    "target_route_version_id": item["target_route_version_id"],
                    "target_process_id": item["target_process_id"],
                    "target_process_version_id": item["target_process_version_id"],
                    "normal_unit_price_micros": draft["normal_unit_price_micros"],
                    "rework_rate_basis_points": draft["rework_rate_basis_points"],
                    "rework_rate_configured": draft["rework_rate_configured"],
                    "valid_from": draft["valid_from"],
                    "valid_to": draft["valid_to"],
                    "target_route_content_digest": item["target_route_content_digest"],
                    "target_process_content_digest": item["target_process_content_digest"],
                    "affected_work_record_count": evidence["work_record_count"],
                    "affected_quantity": evidence["quantity"],
                    "affected_work_record_digest": evidence["work_record_digest"],
                    "manual_decision_reason": draft["confirmation_reason"],
                    "manual_decision_by": draft["created_by"],
                    "manual_decision_at": now,
                    "manual_parent_item_key": item["item_key"],
                },
                db,
            )
            price_id = HistoricalPriceBindingRepository.insert_price_version(
                {
                    "route_id": item["target_route_id"],
                    "route_version_id": item["target_route_version_id"],
                    "process_id": item["target_process_id"],
                    "process_version_id": item["target_process_version_id"],
                    "normal_unit_price_micros": draft["normal_unit_price_micros"],
                    "rework_rate_basis_points": draft["rework_rate_basis_points"],
                    "rework_rate_configured": draft["rework_rate_configured"],
                    "valid_from": draft["valid_from"],
                    "valid_to": draft["valid_to"],
                    "created_by": draft["created_by"],
                    "created_by_name": draft["created_by_name"],
                    "approved_by": approver_id,
                    "approved_by_name": approver_name,
                    "approved_at": now,
                    "remark": "受控历史精确工价人工确认",
                    "idempotency_key": f"historical-price-manual:{draft_id}",
                    "request_digest": draft["request_digest"],
                    "route_content_digest_snapshot": item["target_route_content_digest"],
                    "process_content_digest_snapshot": item["target_process_content_digest"],
                    "historical_price_repair_item_id": repair_item_id,
                },
                db,
            )
            HistoricalPriceBindingRepository.mark_repair_item_applied(
                repair_item_id, price_id, now, db
            )
            HistoricalPriceBindingRepository.approve_draft(
                draft_id, approver_id, approver_name, now, price_id,
                expected_row_version, db
            )
            HistoricalPriceBindingRepository.mark_repair_run_applied(
                run_id, _canonical_json({"created_price_version_id": price_id, **evidence}), now, db
            )
            PayrollRepository.insert_event({
                "event_type": "historical_price_manual_draft_approved",
                "operator_id": approver_id, "operator_name": approver_name,
                "reason": draft["confirmation_reason"], "idempotency_key": key + ":event",
                "payload": {"manual_review_id": int(item["id"]), "draft_id": int(draft_id), "price_version_id": price_id},
            }, db)
            approved_draft = HistoricalPriceBindingRepository.draft(draft_id, db)
            return {
                "draft": HistoricalPriceBindingService._draft_payload(approved_draft),
                "price_version_id": price_id,
                "replayed": False,
            }
