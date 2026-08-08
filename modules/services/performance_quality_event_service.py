"""Canonical quality-event registration for performance source accounting."""

import hashlib
import json
import math
import re

from modules.domain.errors import ConflictError, NotFoundError, ValidationError
from modules.repositories.performance_fact_repository import PerformanceFactRepository
from modules.services import BaseService


class PerformanceQualityEventService:
    SOURCE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,79}$")
    EVENT_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,79}$")

    @staticmethod
    def _canonical(value):
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )

    @classmethod
    def _source(cls, value):
        if isinstance(value, dict):
            source_type = value.get("source_type")
            source_id = value.get("source_id")
        elif isinstance(value, (list, tuple)) and len(value) == 2:
            source_type, source_id = value
        else:
            raise ValidationError("质量事件来源格式无效")
        source_type = str(source_type or "").strip()
        if not cls.SOURCE_PATTERN.fullmatch(source_type):
            raise ValidationError("质量事件来源类型无效")
        try:
            source_id = int(source_id)
        except (TypeError, ValueError) as exc:
            raise ValidationError("质量事件来源 ID 无效") from exc
        if source_id <= 0:
            raise ValidationError("质量事件来源 ID 必须大于 0")
        return source_type, source_id

    @staticmethod
    def _optional_id(value, field):
        if value in (None, ""):
            return None
        try:
            normalized = int(value)
        except (TypeError, ValueError) as exc:
            raise ValidationError(field + "无效") from exc
        if normalized <= 0:
            raise ValidationError(field + "必须大于 0")
        return normalized

    @staticmethod
    def _quantity(value):
        try:
            normalized = float(value or 0)
        except (TypeError, ValueError) as exc:
            raise ValidationError("质量事件数量必须为数字") from exc
        if not math.isfinite(normalized) or normalized < 0:
            raise ValidationError("质量事件数量必须为非负有限数字")
        return int(normalized) if normalized.is_integer() else normalized

    @classmethod
    def record_event(
        cls,
        *,
        event_type,
        source_type,
        source_id,
        quantity=0,
        order_id=None,
        process_id=None,
        user_id=None,
        business_at="",
        snapshot=None,
        related_sources=None,
        canonical_event_id=None,
        target_work_record_id=None,
        db=None,
    ):
        values = {
            "event_type": event_type,
            "source_type": source_type,
            "source_id": source_id,
            "quantity": quantity,
            "order_id": order_id,
            "process_id": process_id,
            "user_id": user_id,
            "business_at": business_at,
            "snapshot": snapshot,
            "related_sources": related_sources,
            "canonical_event_id": canonical_event_id,
            "target_work_record_id": target_work_record_id,
        }
        if db is not None:
            return cls._record_event_txn(values, db)
        with BaseService.transaction() as txn:
            return cls._record_event_txn(values, txn)

    @classmethod
    def _record_event_txn(cls, values, db):
        event_type = str(values.get("event_type") or "").strip()
        if not cls.EVENT_PATTERN.fullmatch(event_type):
            raise ValidationError("质量事件类型无效")
        primary_source = cls._source(
            (values.get("source_type"), values.get("source_id"))
        )
        sources = [primary_source]
        for item in values.get("related_sources") or []:
            source = cls._source(item)
            if source not in sources:
                sources.append(source)

        order_id = cls._optional_id(values.get("order_id"), "订单 ID")
        process_id = cls._optional_id(values.get("process_id"), "工序 ID")
        user_id = cls._optional_id(values.get("user_id"), "员工 ID")
        target_work_record_id = cls._optional_id(
            values.get("target_work_record_id"), "目标报工 ID"
        )
        snapshot = values.get("snapshot") or {}
        if not isinstance(snapshot, dict):
            raise ValidationError("质量事件快照必须是对象")
        snapshot = dict(snapshot)
        if target_work_record_id:
            work_record = PerformanceFactRepository.work_record_context(
                target_work_record_id, db=db
            )
            if not work_record:
                raise NotFoundError("目标报工记录不存在")
            for field, current in (
                ("order_id", order_id),
                ("process_id", process_id),
                ("user_id", user_id),
            ):
                actual = work_record[field]
                if current is not None and actual is not None and current != actual:
                    raise ConflictError("质量事件与目标报工归属不一致")
            order_id = order_id or work_record["order_id"]
            process_id = process_id or work_record["process_id"]
            user_id = user_id or work_record["user_id"]
            snapshot.setdefault("target_work_record_id", target_work_record_id)

        requested_event_id = cls._optional_id(
            values.get("canonical_event_id"), "规范质量事件 ID"
        )
        mappings = PerformanceFactRepository.source_mappings(sources, db=db)
        mapped_event_ids = {row["quality_event_id"] for row in mappings}
        if len(mapped_event_ids) > 1:
            raise ConflictError("显式关联来源已经指向不同规范质量事件")
        mapped_event_id = next(iter(mapped_event_ids), None)
        if requested_event_id and mapped_event_id and requested_event_id != mapped_event_id:
            raise ConflictError("质量事件来源已绑定其他规范事件")
        event_id = requested_event_id or mapped_event_id
        if event_id and not PerformanceFactRepository.quality_event(event_id, db=db):
            raise NotFoundError("规范质量事件不存在")

        if not event_id:
            business_at = str(values.get("business_at") or "").strip()
            business_at = business_at or PerformanceFactRepository.database_now(db=db)
            payload = {
                "event_type": event_type,
                "quantity": cls._quantity(values.get("quantity")),
                "order_id": order_id,
                "process_id": process_id,
                "user_id": user_id,
                "business_at": business_at,
                "snapshot": snapshot,
                "primary_source": {
                    "source_type": primary_source[0],
                    "source_id": primary_source[1],
                },
            }
            canonical_payload = cls._canonical(payload)
            event_id = PerformanceFactRepository.insert_quality_event(
                {
                    **payload,
                    "snapshot_json": cls._canonical(snapshot),
                    "event_digest": hashlib.sha256(
                        canonical_payload.encode("utf-8")
                    ).hexdigest(),
                },
                db,
            )

        for source_type, source_id in sources:
            mapping = PerformanceFactRepository.insert_quality_event_source(
                event_id, source_type, source_id, db
            )
            if not mapping or mapping["quality_event_id"] != event_id:
                raise ConflictError("质量事件来源已绑定其他规范事件")
        return cls.get_event(event_id, db=db)

    @staticmethod
    def get_event(event_id, db=None):
        event = PerformanceFactRepository.quality_event(event_id, db=db)
        if not event:
            raise NotFoundError("规范质量事件不存在")
        event["sources"] = PerformanceFactRepository.quality_event_sources(
            event_id, db=db
        )
        return event

    @classmethod
    def record_historical_ambiguity(
        cls,
        *,
        source_type,
        source_id,
        candidates,
        snapshot=None,
        user_id=None,
        db=None,
    ):
        values = {
            "source": cls._source((source_type, source_id)),
            "candidates": candidates,
            "snapshot": snapshot,
            "user_id": user_id,
        }
        if db is not None:
            return cls._record_historical_ambiguity_txn(values, db)
        with BaseService.transaction() as txn:
            return cls._record_historical_ambiguity_txn(values, txn)

    @classmethod
    def _record_historical_ambiguity_txn(cls, values, db):
        source_type, source_id = values["source"]
        candidates = []
        for item in values.get("candidates") or []:
            candidate_type, candidate_id = cls._source(item)
            candidate = {
                "source_type": candidate_type,
                "source_id": candidate_id,
            }
            if candidate not in candidates:
                candidates.append(candidate)
        if not candidates:
            raise ValidationError("历史质量来源歧义必须提供候选项")
        snapshot = values.get("snapshot") or {}
        if not isinstance(snapshot, dict):
            raise ValidationError("历史质量来源快照必须是对象")
        existing = PerformanceFactRepository.historical_quality_exception(
            source_type, source_id, db=db
        )
        if existing:
            return existing
        PerformanceFactRepository.insert_historical_quality_exception(
            {
                "source_type": source_type,
                "source_id": source_id,
                "user_id": cls._optional_id(values.get("user_id"), "员工 ID"),
                "snapshot_json": cls._canonical(
                    {**snapshot, "candidates": candidates}
                ),
            },
            db,
        )
        return PerformanceFactRepository.historical_quality_exception(
            source_type, source_id, db=db
        )
