"""Shared idempotency and workflow-evidence primitives for schedule services.

The generation, replan, and revision workflows all need the same validation,
digest, replay, and audit-event semantics.  Keeping those operations here
prevents a service from subtly changing idempotency behavior while the actual
state transition remains in its owning use case and transaction.
"""

import hashlib
import json

from modules.domain.production_node_scheduling import NodeSchedulingError
from modules.repositories.schedule_revision_repository import ScheduleRevisionRepository


class ScheduleWorkflowEvidence:
    """Pure request normalization plus atomic workflow evidence helpers."""

    @staticmethod
    def normalize_input(reason, idempotency_key, actor_id):
        reason = str(reason or "").strip()
        key = str(idempotency_key or "").strip()
        try:
            actor = int(actor_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("操作人不能为空") from exc
        if actor <= 0:
            raise ValueError("操作人不能为空")
        if not reason or len(reason) > 1024:
            raise ValueError("原因必须填写且不能超过 1024 个字符")
        if len(key) < 8 or len(key) > 128:
            raise ValueError("幂等键长度必须在 8 到 128 个字符之间")
        return reason, key, actor

    @staticmethod
    def digest(payload):
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def replay(db, key, digest):
        event = ScheduleRevisionRepository.find_workflow_event(key, db=db)
        if event is None:
            return None
        if event["input_digest"] != digest:
            raise NodeSchedulingError(
                "IDEMPOTENCY_CONFLICT",
                "幂等键已被不同输入使用",
                {"idempotency_key": key},
            )
        try:
            result = json.loads(event["after_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            result = {}
        return {
            "ok": True,
            "idempotent_replay": True,
            "event": dict(event),
            "result": result,
        }

    @staticmethod
    def record(
        db, *, revision_id, revision_item_id, event_type, actor_id,
        reason, before, after, digest, idempotency_key,
    ):
        before_json = json.dumps(
            before or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        after_json = json.dumps(
            after or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        event = ScheduleRevisionRepository.create_workflow_event(
            revision_id=revision_id,
            revision_item_id=revision_item_id,
            event_type=event_type,
            actor_id=actor_id,
            reason=reason,
            before_json=before_json,
            after_json=after_json,
            input_digest=digest,
            idempotency_key=idempotency_key,
            db=db,
        )
        return {
            "ok": True,
            "idempotent_replay": False,
            "event": dict(event),
            "result": after,
        }
