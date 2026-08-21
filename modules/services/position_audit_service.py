"""Mandatory transaction-aware audit events for position commands."""

import hashlib
import json

from modules.audit_policy import sanitize_audit_detail
from modules.domain.errors import ValidationError
from modules.domain.position_versioning import canonical_json, position_diff
from modules.repositories.audit_log_repository import AuditLogRepository


class PositionAuditService:
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
    def _event_id(action, idempotency_key):
        canonical = f"{str(action or '').strip()}:{str(idempotency_key or '').strip()}"
        return "position-audit-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _diff(before, after):
        if before and after and before.get("name") and after.get("name"):
            return position_diff(before, after)
        source = after or before or {}
        process_ids = sorted({int(value) for value in source.get("process_ids") or []})
        fields = [
            field
            for field in ("name", "description", "process_ids")
            if field in source
        ]
        return {
            "changed_fields": fields,
            "added_process_ids": process_ids if after else [],
            "removed_process_ids": process_ids if before and not after else [],
        }

    @staticmethod
    def _insert(db, *, actor_id, action, position_id, detail, event_id, request_id):
        return AuditLogRepository.insert_log(
            actor_id,
            action,
            "position",
            position_id,
            detail,
            db=db,
            event_id=event_id,
            request_id=request_id,
        )

    @staticmethod
    def record(
        db,
        *,
        action,
        actor,
        request_id="",
        idempotency_key,
        position_id,
        position_version_id=None,
        before=None,
        after=None,
        reason="",
        impact_digest="",
    ):
        key = str(idempotency_key or "").strip()
        if not key:
            raise ValidationError("幂等键不能为空")
        normalized_actor = PositionAuditService._actor(actor)
        event_id = PositionAuditService._event_id(action, key)
        replay = AuditLogRepository.find_by_event_id(event_id, db=db)
        if replay:
            return replay["id"]
        diff = PositionAuditService._diff(before, after)
        detail = sanitize_audit_detail(
            {
                "actor_name": normalized_actor["name"],
                "actor_role": normalized_actor["role"],
                "position_version_id": position_version_id,
                "changed_fields": diff.get("changed_fields", []),
                "added_process_ids": diff.get("added_process_ids", []),
                "removed_process_ids": diff.get("removed_process_ids", []),
                "reason": str(reason or "").strip(),
                "impact_digest": str(impact_digest or ""),
                "idempotency_key": key,
            }
        )
        # Re-canonicalize the sanitized JSON so callers and tests get one
        # deterministic representation regardless of dict insertion order.
        detail = canonical_json(json.loads(detail))
        return PositionAuditService._insert(
            db,
            actor_id=normalized_actor["id"],
            action=str(action or "").strip(),
            position_id=int(position_id),
            detail=detail,
            event_id=event_id,
            request_id=str(request_id or "")[:120],
        )
