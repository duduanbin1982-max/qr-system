"""Capture immutable, reproducible inputs for one performance batch."""

from datetime import datetime, timedelta
import hashlib
import json

from modules.domain.errors import ConflictError, NotFoundError
from modules.domain.reporting_day import reporting_month_bounds
from modules.repositories.performance_assignment_repository import (
    PerformanceAssignmentRepository,
)
from modules.repositories.performance_fact_repository import PerformanceFactRepository
from modules.services import BaseService


class PerformanceFactCollector:
    DERIVED_SCORING_EXCEPTION_TYPES = {
        "ambiguous_department_snapshot",
        "ambiguous_position_snapshot",
        "missing_position_snapshot",
        "missing_position_target",
    }
    FACT_INPUT_FIELDS = (
        "fact_type",
        "source_type",
        "source_id",
        "canonical_event_id",
        "business_at",
        "user_id",
        "employee_name_snapshot",
        "employee_no_snapshot",
        "department_id_snapshot",
        "department_name_snapshot",
        "position_id_snapshot",
        "position_name_snapshot",
        "order_id",
        "order_no_snapshot",
        "product_id",
        "product_code_snapshot",
        "product_name_snapshot",
        "process_id",
        "process_name_snapshot",
        "quantity",
        "payload_json",
        "source_digest",
    )
    EXCEPTION_INPUT_FIELDS = (
        "user_id",
        "exception_type",
        "source_type",
        "source_id",
        "snapshot_json",
    )

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
    def _digest(cls, value):
        return hashlib.sha256(cls._canonical(value).encode("utf-8")).hexdigest()

    @staticmethod
    def _json_object(value):
        if isinstance(value, dict):
            return dict(value)
        try:
            parsed = json.loads(value or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("绩效来源快照 JSON 无效") from exc
        if not isinstance(parsed, dict):
            raise ValueError("绩效来源快照必须是 JSON 对象")
        return parsed

    @staticmethod
    def _number(value):
        number = float(value or 0)
        return int(number) if number.is_integer() else number

    @staticmethod
    def _production_day(business_at):
        try:
            value = datetime.fromisoformat(str(business_at))
        except (TypeError, ValueError) as exc:
            raise ValueError("绩效来源业务时间无效") from exc
        return (value - timedelta(hours=7)).strftime("%Y-%m-%d")

    @classmethod
    def collect(cls, batch_id, db=None):
        """Freeze source facts for a draft batch; retries return persisted facts."""
        if db is not None:
            return cls._collect_txn(batch_id, db)
        with BaseService.transaction() as txn:
            return cls._collect_txn(batch_id, txn)

    @classmethod
    def _collect_txn(cls, batch_id, db):
        batch = PerformanceFactRepository.batch(batch_id, db=db)
        if not batch:
            raise NotFoundError("绩效批次不存在")
        if batch["status"] != "draft":
            raise ConflictError("只有草稿绩效批次可以采集来源事实")
        expected_bounds = reporting_month_bounds(batch["production_month"])
        if (batch["period_start"], batch["period_end"]) != expected_bounds:
            raise ConflictError("绩效批次区间不符合 07:00 生产月口径")

        cutoff = str(batch.get("source_cutoff_at") or "").strip()
        if not cutoff:
            cutoff = PerformanceFactRepository.database_now(db=db)
        try:
            datetime.fromisoformat(cutoff)
        except ValueError as exc:
            raise ConflictError("绩效来源截止时间无效") from exc
        if cutoff < batch["period_start"]:
            raise ConflictError("绩效来源截止时间不能早于生产月开始时间")

        if batch.get("input_digest"):
            return cls._saved_result(batch, db)
        if PerformanceFactRepository.list_batch_facts(batch_id, db=db):
            raise ConflictError("绩效批次已有事实但缺少输入摘要，禁止覆盖采集")

        facts, exceptions = cls._gather(batch, cutoff, db)

        facts.sort(key=cls._fact_sort_key)
        exceptions.sort(key=cls._exception_sort_key)
        for fact in facts:
            PerformanceFactRepository.insert_source_fact(fact, db)
        for exception in exceptions:
            PerformanceFactRepository.insert_batch_exception(exception, db)

        persisted_facts = PerformanceFactRepository.list_batch_facts(batch_id, db=db)
        persisted_exceptions = PerformanceFactRepository.list_batch_exceptions(
            batch_id, db=db
        )
        input_json, input_digest = cls._input_summary(
            batch, cutoff, persisted_facts, persisted_exceptions
        )
        if not PerformanceFactRepository.save_collection_digest(
            batch_id, cutoff, input_digest, db
        ):
            raise ConflictError("绩效批次来源摘要已被其他操作写入")
        saved_batch = PerformanceFactRepository.batch(batch_id, db=db)
        return cls._result(
            saved_batch,
            persisted_facts,
            persisted_exceptions,
            input_json,
            input_digest,
        )

    @classmethod
    def _gather(cls, batch, cutoff, db):
        batch_id = int(batch["id"])
        exceptions = []
        facts = []
        for assignment in PerformanceAssignmentRepository.list_for_collection(
            batch["period_start"], batch["period_end"], cutoff, db=db
        ):
            facts.append(
                cls._assignment_fact(
                    batch_id,
                    batch["period_start"],
                    batch["period_end"],
                    cutoff,
                    assignment,
                    exceptions,
                    db,
                )
            )
        for source in PerformanceFactRepository.list_work_records(
            batch["period_start"], batch["period_end"], cutoff, db=db
        ):
            facts.append(cls._work_fact(batch_id, source, exceptions, db))
        for source in PerformanceFactRepository.list_work_time_records(
            batch["period_start"], batch["period_end"], cutoff, db=db
        ):
            facts.append(cls._work_time_fact(batch_id, source, exceptions, db))
        for event in PerformanceFactRepository.list_quality_events(
            batch["period_start"],
            batch["period_end"],
            db=db,
            source_cutoff_at=cutoff,
        ):
            fact = cls._quality_fact(batch_id, event, cutoff, exceptions, db)
            if fact:
                facts.append(fact)
        for plan in PerformanceFactRepository.list_plan_statuses(
            batch["period_start"], batch["period_end"], cutoff, db=db
        ):
            facts.append(cls._plan_fact(batch_id, plan, exceptions, db))

        for item in PerformanceFactRepository.list_ambiguous_quality_exceptions(
            batch["period_start"], batch["period_end"], cutoff, db=db
        ):
            snapshot = cls._json_object(item.get("snapshot_json"))
            snapshot["historical_exception_id"] = item["id"]
            exceptions.append(
                {
                    "batch_id": batch_id,
                    "user_id": item.get("user_id"),
                    "exception_type": "ambiguous_quality_source",
                    "source_type": item.get("source_type") or "",
                    "source_id": item.get("source_id") or 0,
                    "snapshot_json": cls._canonical(snapshot),
                }
            )
        facts.sort(key=cls._fact_sort_key)
        exceptions.sort(key=cls._exception_sort_key)
        return facts, exceptions

    @classmethod
    def verify_frozen_input(cls, batch_id, db=None):
        batch = PerformanceFactRepository.batch(batch_id, db=db)
        if not batch:
            raise NotFoundError("绩效批次不存在")
        facts = PerformanceFactRepository.list_batch_facts(batch_id, db=db)
        exceptions = PerformanceFactRepository.list_batch_exceptions(batch_id, db=db)
        _, calculated_digest = cls._input_summary(
            batch, batch["source_cutoff_at"], facts, exceptions
        )
        return {
            "valid": calculated_digest == batch["input_digest"],
            "saved_input_digest": batch["input_digest"],
            "calculated_input_digest": calculated_digest,
        }

    @classmethod
    def current_input_status(cls, batch_id, db=None):
        batch = PerformanceFactRepository.batch(batch_id, db=db)
        if not batch:
            raise NotFoundError("绩效批次不存在")
        frozen = cls.verify_frozen_input(batch_id, db=db)
        current_cutoff = PerformanceFactRepository.database_now(db=db)
        if current_cutoff < batch["source_cutoff_at"]:
            current_cutoff = batch["source_cutoff_at"]
        facts, exceptions = cls._gather(batch, current_cutoff, db)
        _, current_digest = cls._input_summary(
            batch, batch["source_cutoff_at"], facts, exceptions
        )
        return {
            **frozen,
            "current_source_cutoff_at": current_cutoff,
            "current_input_digest": current_digest,
            "input_drift_detected": (
                not frozen["valid"]
                or current_digest != batch["input_digest"]
            ),
            "current_fact_count": len(facts),
            "current_exception_count": len(exceptions),
        }

    @classmethod
    def _saved_result(cls, batch, db):
        facts = PerformanceFactRepository.list_batch_facts(batch["id"], db=db)
        exceptions = PerformanceFactRepository.list_batch_exceptions(batch["id"], db=db)
        input_json, calculated_digest = cls._input_summary(
            batch, batch["source_cutoff_at"], facts, exceptions
        )
        if calculated_digest != batch["input_digest"]:
            raise ConflictError("绩效批次已保存事实与输入摘要不一致")
        return cls._result(
            batch,
            facts,
            exceptions,
            input_json,
            calculated_digest,
        )

    @classmethod
    def _result(cls, batch, facts, exceptions, input_json, input_digest):
        candidate_ids = set(
            int(fact["user_id"])
            for fact in facts
            if fact.get("user_id") is not None
        )
        return {
            "batch_id": batch["id"],
            "production_month": batch["production_month"],
            "period_start": batch["period_start"],
            "period_end": batch["period_end"],
            "source_cutoff_at": batch["source_cutoff_at"],
            "candidate_user_ids": sorted(candidate_ids),
            "facts": facts,
            "exceptions": exceptions,
            "fact_count": len(facts),
            "exception_count": len(exceptions),
            "input_json": input_json,
            "input_digest": input_digest,
        }

    @classmethod
    def _input_summary(cls, batch, cutoff, facts, exceptions):
        fact_inputs = []
        for row in facts:
            item = {field: row.get(field) for field in cls.FACT_INPUT_FIELDS}
            item["quantity"] = float(item.get("quantity") or 0)
            item["payload"] = cls._json_object(item.pop("payload_json"))
            fact_inputs.append(item)
        fact_inputs.sort(key=cls._fact_sort_key)

        exception_inputs = []
        for row in exceptions:
            if row.get("exception_type") in cls.DERIVED_SCORING_EXCEPTION_TYPES:
                continue
            item = {field: row.get(field) for field in cls.EXCEPTION_INPUT_FIELDS}
            item["snapshot"] = cls._json_object(item.pop("snapshot_json"))
            exception_inputs.append(item)
        exception_inputs.sort(key=cls._exception_sort_key)
        payload = {
            "production_month": batch["production_month"],
            "period_start": batch["period_start"],
            "period_end": batch["period_end"],
            "source_cutoff_at": cutoff,
            "facts": fact_inputs,
            "exceptions": exception_inputs,
        }
        input_json = cls._canonical(payload)
        return input_json, hashlib.sha256(input_json.encode("utf-8")).hexdigest()

    @staticmethod
    def _fact_sort_key(item):
        return (
            str(item.get("fact_type") or ""),
            str(item.get("source_type") or ""),
            int(item.get("source_id") or 0),
            int(item.get("canonical_event_id") or 0),
        )

    @staticmethod
    def _exception_sort_key(item):
        return (
            str(item.get("exception_type") or ""),
            str(item.get("source_type") or ""),
            int(item.get("source_id") or 0),
            int(item.get("user_id") or 0),
        )

    @classmethod
    def _assignment(cls, user_id, business_at, fact_identity, exceptions, db):
        if user_id is None:
            return {}
        assignment = PerformanceAssignmentRepository.assignment_at(
            user_id, business_at, db=db
        )
        if assignment:
            return assignment
        exceptions.append(
            {
                "batch_id": fact_identity["batch_id"],
                "user_id": user_id,
                "exception_type": "missing_assignment_history",
                "source_type": fact_identity["source_type"],
                "source_id": fact_identity["source_id"],
                "snapshot_json": cls._canonical(
                    {
                        "business_at": business_at,
                        "fact_type": fact_identity["fact_type"],
                        "user_id": user_id,
                    }
                ),
            }
        )
        return {}

    @classmethod
    def _fact(
        cls,
        *,
        batch_id,
        fact_type,
        source_type,
        source_id,
        business_at,
        user_id,
        quantity,
        payload,
        context,
        exceptions,
        canonical_event_id=None,
        db,
    ):
        identity = {
            "batch_id": batch_id,
            "fact_type": fact_type,
            "source_type": source_type,
            "source_id": source_id,
        }
        assignment = cls._assignment(
            user_id, business_at, identity, exceptions, db
        )
        product_code = context.get("order_product_code") or context.get(
            "current_product_code"
        ) or context.get("product_code") or ""
        product_name = context.get("order_product_name") or context.get(
            "current_product_name"
        ) or context.get("product_name") or ""
        process_name = context.get("process_name") or context.get(
            "current_process_name"
        ) or ""
        payload_json = cls._canonical(payload)
        fact = {
            **identity,
            "canonical_event_id": canonical_event_id,
            "business_at": business_at,
            "user_id": user_id,
            "employee_name_snapshot": assignment.get(
                "employee_name_snapshot",
                context.get("source_employee_name_snapshot") or "",
            ),
            "employee_no_snapshot": assignment.get(
                "employee_no_snapshot",
                context.get("source_employee_no_snapshot") or "",
            ),
            "department_id_snapshot": assignment.get("department_id"),
            "department_name_snapshot": assignment.get(
                "department_name_snapshot", ""
            ),
            "position_id_snapshot": assignment.get("position_id"),
            "position_name_snapshot": assignment.get("position_name_snapshot", ""),
            "order_id": context.get("order_id"),
            "order_no_snapshot": context.get("order_no")
            or context.get("current_order_no")
            or "",
            "product_id": context.get("product_id"),
            "product_code_snapshot": product_code,
            "product_name_snapshot": product_name,
            "process_id": context.get("process_id"),
            "process_name_snapshot": process_name,
            "quantity": cls._number(quantity),
            "payload_json": payload_json,
        }
        digest_payload = {
            field: fact.get(field)
            for field in cls.FACT_INPUT_FIELDS
            if field not in ("payload_json", "source_digest")
        }
        digest_payload["payload"] = payload
        fact["source_digest"] = cls._digest(digest_payload)
        return fact

    @classmethod
    def _assignment_fact(
        cls,
        batch_id,
        period_start,
        period_end,
        cutoff,
        row,
        exceptions,
        db,
    ):
        effective_from = max(row["valid_from"], period_start)
        observed_valid_to = row.get("valid_to") or ""
        if observed_valid_to and observed_valid_to > cutoff:
            observed_valid_to = ""
        effective_to = min(
            observed_valid_to or period_end,
            period_end,
            cutoff,
        )
        payload = {
            "valid_from": row["valid_from"],
            "valid_to": observed_valid_to,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "source_type": row.get("source_type") or "",
            "source_key": row.get("source_key") or "",
            "department_revision_id": row.get("department_revision_id"),
            "department_revision": row.get("department_revision"),
            "department_revision_source_key": row.get(
                "department_revision_source_key"
            )
            or "",
            "department_revision_approved_at": row.get(
                "department_revision_approved_at"
            )
            or "",
        }
        return cls._fact(
            batch_id=batch_id,
            fact_type="assignment",
            source_type="performance_assignment_history",
            source_id=row["id"],
            business_at=effective_from,
            user_id=row["user_id"],
            quantity=0,
            payload=payload,
            context={},
            exceptions=exceptions,
            db=db,
        )

    @classmethod
    def _work_fact(cls, batch_id, row, exceptions, db):
        payload = {
            "record_type": row.get("type") or "normal",
            "status": row.get("status") or "",
            "serial_no": row.get("serial_no") or "",
            "remark": row.get("remark") or "",
            "report_source": row.get("report_source") or "standard",
            "actual_completed_at": row.get("actual_completed_at") or "",
            "backfill_reason": row.get("backfill_reason") or "",
            "submit_position_id": row.get("submit_position_id"),
            "submit_position_name": row.get("submit_position_name") or "",
            "production_day": cls._production_day(row["business_at"]),
        }
        return cls._fact(
            batch_id=batch_id,
            fact_type="work",
            source_type="work_record",
            source_id=row["id"],
            business_at=row["business_at"],
            user_id=row.get("user_id"),
            quantity=row.get("quantity"),
            payload=payload,
            context=row,
            exceptions=exceptions,
            db=db,
        )

    @classmethod
    def _work_time_fact(cls, batch_id, row, exceptions, db):
        context = dict(row)
        context["order_no"] = row.get("order_no") or row.get("current_order_no") or ""
        context["order_product_code"] = (
            row.get("product_code") or row.get("order_product_code") or ""
        )
        context["order_product_name"] = (
            row.get("product_name") or row.get("order_product_name") or ""
        )
        context["process_name"] = (
            row.get("process_name") or row.get("current_process_name") or ""
        )
        context["source_employee_name_snapshot"] = row.get("user_name") or ""
        payload = {
            "status": row.get("status") or "",
            "review_status": row.get("review_status") or "",
            "source_work_record_id": row.get("source_work_record_id"),
            "standard_id": row.get("standard_id"),
            "standard_missing": int(row.get("standard_missing") or 0),
            "standard_minutes": cls._number(row.get("standard_minutes")),
            "actual_minutes": cls._number(row.get("actual_minutes")),
            "effective_minutes": cls._number(row.get("effective_minutes")),
            "pause_minutes": cls._number(row.get("pause_minutes")),
            "abnormal_reason": row.get("abnormal_reason") or "",
            "production_day": cls._production_day(row["business_at"]),
        }
        return cls._fact(
            batch_id=batch_id,
            fact_type="work_time",
            source_type="work_time_record",
            source_id=row["id"],
            business_at=row["business_at"],
            user_id=row.get("user_id"),
            quantity=row.get("quantity"),
            payload=payload,
            context=context,
            exceptions=exceptions,
            db=db,
        )

    @classmethod
    def _quality_fact(cls, batch_id, event, cutoff, exceptions, db):
        snapshot = cls._json_object(event.get("snapshot_json"))
        rating = snapshot.get("rating")
        evaluation = None
        evaluation_status = ""
        for source in event.get("sources") or []:
            if source.get("source_type") == "process_quality_evaluation":
                evaluation = PerformanceFactRepository.process_quality_evaluation(
                    source["source_id"], cutoff, db=db
                )
                evaluation_status = evaluation.get("status") if evaluation else ""
                break
        if event.get("event_type") == "process_handoff":
            if evaluation:
                if (
                    evaluation.get("reviewed_at")
                    and evaluation["reviewed_at"] > cutoff
                ):
                    evaluation_status = snapshot.get("status")
                if evaluation_status != "confirmed" or evaluation.get(
                    "has_pending_appeal"
                ):
                    return None
                rating = cls._number(evaluation.get("total_score")) / 20
            else:
                status = str(snapshot.get("status") or "").strip()
                if status and status != "confirmed":
                    return None
                if rating is None and snapshot.get("total_score") is not None:
                    rating = cls._number(snapshot["total_score"]) / 20

        context = PerformanceFactRepository.business_context(
            event.get("order_id"), event.get("process_id"), db=db
        )
        payload = {
            "event_type": event.get("event_type") or "",
            "event_digest": event.get("event_digest") or "",
            "rating": cls._number(rating) if rating is not None else None,
            "snapshot": snapshot,
            "sources": sorted(
                [
                    {
                        "source_type": source.get("source_type") or "",
                        "source_id": int(source.get("source_id") or 0),
                    }
                    for source in event.get("sources") or []
                ],
                key=lambda source: (source["source_type"], source["source_id"]),
            ),
        }
        if evaluation:
            payload["evaluation_status"] = evaluation_status or ""
            payload["evaluation_severity"] = evaluation.get("severity") or ""
        return cls._fact(
            batch_id=batch_id,
            fact_type="quality_event",
            source_type="performance_quality_event",
            source_id=event["id"],
            canonical_event_id=event["id"],
            business_at=event["business_at"],
            user_id=event.get("user_id"),
            quantity=event.get("quantity"),
            payload=payload,
            context=context,
            exceptions=exceptions,
            db=db,
        )

    @classmethod
    def _plan_fact(cls, batch_id, row, exceptions, db):
        event_id = row.get("event_id")
        event_payload = cls._json_object(row.get("event_payload_json"))
        context = {
            "source_employee_name_snapshot": row.get("employee_name_snapshot") or "",
            "source_employee_no_snapshot": row.get("employee_no_snapshot") or "",
        }
        payload = {
            "plan_id": int(row["id"]),
            "plan_production_month": row.get("production_month") or "",
            "status": row.get("status_snapshot") or row.get("status") or "",
            "reassessment_round": int(row.get("event_round") or 0),
            "warning_level": row.get("warning_level_snapshot") or "",
            "reason": (
                event_payload.get("reason") or ""
                if event_id is not None
                else row.get("reason") or ""
            ),
            "event": event_payload,
        }
        return cls._fact(
            batch_id=batch_id,
            fact_type="plan_status",
            source_type=(
                "performance_plan_event"
                if event_id is not None
                else "performance_improvement_plan"
            ),
            source_id=event_id if event_id is not None else row["id"],
            business_at=row["business_at"],
            user_id=row.get("user_id"),
            quantity=0,
            payload=payload,
            context=context,
            exceptions=exceptions,
            db=db,
        )
