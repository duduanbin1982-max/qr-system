"""Preflight and controlled generation of historical performance V2 revisions."""

from collections import Counter
import json

from modules.domain import evidence_protocol
from modules.domain.performance_policy import validate_production_month
from modules.domain.reporting_day import reporting_month_bounds
from modules.repositories.performance_history_migration_repository import (
    PerformanceHistoryMigrationRepository,
)
from modules.repositories.performance_ledger_repository import (
    PerformanceLedgerRepository,
)
from modules.services.performance_ledger_service import PerformanceLedgerService
from modules.services.performance_quality_event_service import (
    PerformanceQualityEventService,
)


MANIFEST_FORMAT = "performance_history_migration_manifest_v1"
EVENT_PREFIX = "performance-history-migration"
REQUIRED_TABLES = {
    "performance_batches",
    "performance_score_revisions",
    "performance_batch_events",
    "performance_migration_manifests",
    "performance_source_facts",
    "performance_data_exceptions",
    "performance_assignment_history",
    "performance_quality_events",
    "performance_quality_event_sources",
    "performance_rule_versions",
    "performance_position_target_versions",
    "process_quality_evaluations",
    "quality_inspections",
    "scrap_records",
    "rework_records",
}
BASELINE_FIELDS = (
    "overwritten_score_count",
    "missing_position_count",
    "cross_month_work_count",
    "cross_month_quality_count",
)


class PerformanceHistoryMigrationService:
    @staticmethod
    def _canonical(value):
        return evidence_protocol.canonical_json_v1(value)

    @classmethod
    def _digest(cls, value):
        return evidence_protocol.sha256_digest_v1(value)

    @staticmethod
    def _json_object(value):
        if isinstance(value, dict):
            return dict(value)
        try:
            parsed = json.loads(value or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("历史绩效迁移来源快照 JSON 无效") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("历史绩效迁移来源快照必须是 JSON 对象")
        return parsed

    @staticmethod
    def _month_bounds(start_month="", end_month=""):
        start = validate_production_month(start_month) if start_month else ""
        end = validate_production_month(end_month) if end_month else ""
        if start and end and start > end:
            raise ValueError("历史绩效迁移起始月份不能晚于结束月份")
        return start, end

    @classmethod
    def _require_schema(cls, db):
        tables = PerformanceHistoryMigrationRepository.table_names(db)
        missing = sorted(REQUIRED_TABLES - tables)
        if missing:
            raise RuntimeError("绩效历史迁移缺少 V56 表: " + ", ".join(missing))

    @staticmethod
    def _calendar_month(value):
        return str(value or "")[:7]

    @classmethod
    def _record(cls, source_type, source_id, classification, payload, *, user_id=None, business_at=""):
        try:
            numeric_id = int(source_id)
        except (TypeError, ValueError):
            numeric_id = 0
        document = {
            "source_type": source_type,
            "source_id": numeric_id,
            "classification": classification,
            "user_id": user_id,
            "business_at": business_at or "",
            "payload": payload,
        }
        document["source_digest"] = cls._digest(document)
        document["stable_key"] = f"{source_type}:{numeric_id:020d}"
        return document

    @classmethod
    def _score_record(cls, score, month, targets):
        position_id = score.get("position_id_snapshot")
        position_name = score.get("position_name_snapshot") or ""
        classifications = []
        if score.get("prior_revisions_unavailable"):
            classifications.append("prior_revisions_unavailable")
        if position_id is None or not position_name:
            classifications.append("missing_position_snapshot")
        elif int(position_id) not in targets:
            classifications.append("missing_position_target")
        if not classifications:
            classifications.append("legacy_baseline")
        source_id = score.get("legacy_score_id") or score["id"]
        payload = {
            "legacy_score_id": source_id,
            "legacy_revision_id": score["id"],
            "position_id_snapshot": position_id,
            "position_name_snapshot": position_name,
            "prior_revisions_unavailable": int(
                bool(score.get("prior_revisions_unavailable"))
            ),
            "input_digest": score.get("input_digest") or "",
            "legacy_score_json": cls._json_object(score.get("legacy_score_json")),
            "score_details_json": cls._json_object(score.get("score_details_json")),
        }
        return cls._record(
            "legacy_score",
            source_id,
            "+".join(classifications),
            payload,
            user_id=score.get("user_id"),
            business_at=month + "-01 07:00:00",
        )

    @classmethod
    def _month_plan(cls, production_month, db):
        period_start, period_end = reporting_month_bounds(production_month)
        legacy_batch = PerformanceHistoryMigrationRepository.legacy_batch(
            production_month, db
        )
        if not legacy_batch:
            raise RuntimeError(f"未找到生产月 {production_month} 的 Legacy V1 批次")
        legacy_manifest = PerformanceHistoryMigrationRepository.legacy_manifest(
            production_month, db
        )
        if not legacy_manifest:
            raise RuntimeError(f"生产月 {production_month} 缺少 Legacy 迁移 manifest")

        scores = PerformanceHistoryMigrationRepository.legacy_scores(
            legacy_batch["id"], db
        )
        if int(legacy_manifest["source_score_count"] or 0) != len(scores):
            raise RuntimeError(
                f"生产月 {production_month} Legacy 评分数量与 manifest 不一致"
            )
        targets = {}
        for target in PerformanceHistoryMigrationRepository.approved_targets(
            production_month, db
        ):
            targets.setdefault(int(target["position_id"]), target)

        records = []
        missing_target_user_ids = set()
        overwritten_score_count = 0
        missing_position_count = 0
        for score in scores:
            record = cls._score_record(score, production_month, targets)
            records.append(record)
            if score.get("prior_revisions_unavailable"):
                overwritten_score_count += 1
            if score.get("position_id_snapshot") is None or not score.get(
                "position_name_snapshot"
            ):
                missing_position_count += 1
            if "missing_position_target" in record["classification"]:
                missing_target_user_ids.add(int(score["user_id"]))
        legacy_count_pairs = (
            (
                "overwritten_score_count",
                overwritten_score_count,
            ),
            (
                "missing_position_count",
                missing_position_count,
            ),
        )
        mismatched_legacy_counts = [
            field
            for field, actual in legacy_count_pairs
            if int(legacy_manifest.get(field) or 0) != actual
        ]
        if mismatched_legacy_counts:
            raise RuntimeError(
                f"生产月 {production_month} Legacy manifest 分类数量不一致: "
                + ", ".join(mismatched_legacy_counts)
            )

        work_records = PerformanceHistoryMigrationRepository.work_records(
            period_start, period_end, db
        )
        cross_work = []
        cross_work_user_ids = set()
        for work in work_records:
            classification = (
                "production_month_boundary"
                if cls._calendar_month(work["business_at"]) != production_month
                else "production_month_work"
            )
            if classification == "production_month_boundary":
                cross_work.append(work)
                if work.get("user_id") is not None:
                    cross_work_user_ids.add(int(work["user_id"]))
            records.append(
                cls._record(
                    "work_record",
                    work["id"],
                    classification,
                    {
                        "user_id": work.get("user_id"),
                        "order_id": work.get("order_id"),
                        "process_id": work.get("process_id"),
                        "type": work.get("type") or "",
                        "quantity": work.get("quantity") or 0,
                        "status": work.get("status") or "",
                        "created_at": work.get("created_at") or "",
                        "actual_completed_at": work.get("actual_completed_at") or "",
                        "business_at": work.get("business_at") or "",
                    },
                    user_id=work.get("user_id"),
                    business_at=work.get("business_at") or "",
                )
            )

        for work_time in PerformanceHistoryMigrationRepository.work_time_records(
            period_start, period_end, db
        ):
            records.append(
                cls._record(
                    "work_time_record",
                    work_time["id"],
                    "production_month_work_time",
                    {
                        "user_id": work_time.get("user_id"),
                        "order_id": work_time.get("order_id"),
                        "process_id": work_time.get("process_id"),
                        "review_status": work_time.get("review_status") or "",
                        "start_time": work_time.get("start_time") or "",
                        "end_time": work_time.get("end_time") or "",
                        "quantity": work_time.get("quantity") or 0,
                        "standard_minutes": work_time.get("standard_minutes") or 0,
                        "actual_minutes": work_time.get("actual_minutes") or 0,
                        "effective_minutes": work_time.get("effective_minutes") or 0,
                        "created_at": work_time.get("created_at") or "",
                        "business_at": work_time.get("business_at") or "",
                    },
                    user_id=work_time.get("user_id"),
                    business_at=work_time.get("business_at") or "",
                )
            )

        ambiguity_rows = PerformanceHistoryMigrationRepository.quality_ambiguities(
            period_start, period_end, db
        )
        ambiguity_keys = {
            (str(row.get("source_type") or ""), int(row.get("source_id") or 0))
            for row in ambiguity_rows
        }
        quality_evaluations = (
            PerformanceHistoryMigrationRepository.process_quality_evaluations(
                period_start, period_end, db
            )
        )
        cross_quality = []
        cross_quality_user_ids = set()
        multi_source_quality_user_ids = set()
        virtual_ambiguity_keys = set()
        normalized_quality_source_keys = set()
        for evaluation in quality_evaluations:
            user_id = evaluation.get("target_user_id") or evaluation.get(
                "handoff_target_user_id"
            )
            source_key = ("process_quality_evaluation", int(evaluation["id"]))
            normalized_quality_source_keys.add(source_key)
            requires_confirmation = (
                source_key in ambiguity_keys
                or (
                    evaluation.get("target_work_record_id") is None
                    and user_id is None
                )
            )
            if requires_confirmation:
                virtual_ambiguity_keys.add(source_key)
            boundary = (
                cls._calendar_month(evaluation.get("created_at"))
                != production_month
            )
            classification = (
                "production_month_boundary"
                if boundary
                else "production_month_quality_evaluation"
            )
            if requires_confirmation:
                classification += "+quality_source_confirmation_required"
            if evaluation.get("source_handoff_review_id"):
                classification += "+explicit_source_relation"
                if user_id is not None:
                    multi_source_quality_user_ids.add(int(user_id))
            if boundary:
                cross_quality.append(evaluation)
                if user_id is not None:
                    cross_quality_user_ids.add(int(user_id))
            records.append(
                cls._record(
                    "process_quality_evaluation",
                    evaluation["id"],
                    classification,
                    {
                        "order_id": evaluation.get("order_id"),
                        "target_process_id": evaluation.get("target_process_id"),
                        "target_work_record_id": evaluation.get("target_work_record_id"),
                        "target_user_id": evaluation.get("target_user_id"),
                        "handoff_target_user_id": evaluation.get(
                            "handoff_target_user_id"
                        ),
                        "quantity": evaluation.get("quantity") or 0,
                        "total_score": evaluation.get("total_score"),
                        "grade": evaluation.get("grade") or "",
                        "status": evaluation.get("status") or "",
                        "source_handoff_review_id": evaluation.get(
                            "source_handoff_review_id"
                        ),
                        "created_at": evaluation.get("created_at") or "",
                        "updated_at": evaluation.get("updated_at") or "",
                    },
                    user_id=user_id,
                    business_at=evaluation.get("created_at") or "",
                )
            )

        quality_source_specs = (
            (
                "scrap_record",
                "scrap",
                PerformanceHistoryMigrationRepository.scrap_records(
                    period_start, period_end, db
                ),
            ),
            (
                "rework_record",
                "rework",
                PerformanceHistoryMigrationRepository.rework_records(
                    period_start, period_end, db
                ),
            ),
        )
        for source_type, event_type, source_rows in quality_source_specs:
            for source in source_rows:
                source_key = (source_type, int(source["id"]))
                normalized_quality_source_keys.add(source_key)
                business_at = source.get("created_at") or ""
                boundary = cls._calendar_month(business_at) != production_month
                classification = (
                    "production_month_boundary"
                    if boundary
                    else "production_month_" + event_type
                )
                if source_type == "rework_record" and source.get("source_ncr_id"):
                    classification += "+explicit_source_relation"
                    multi_source_quality_user_ids.add(int(source["user_id"]))
                if boundary and source.get("user_id") is not None:
                    cross_quality_user_ids.add(int(source["user_id"]))
                records.append(
                    cls._record(
                        source_type,
                        source["id"],
                        classification,
                        {
                            "event_type": event_type,
                            "order_id": source.get("order_id"),
                            "process_id": source.get("process_id"),
                            "user_id": source.get("user_id"),
                            "quantity": source.get("quantity") or 0,
                            "reason": source.get("reason") or "",
                            "source_ncr_id": source.get("source_ncr_id"),
                            "created_at": business_at,
                        },
                        user_id=source.get("user_id"),
                        business_at=business_at,
                    )
                )

        inspections = PerformanceHistoryMigrationRepository.quality_inspections(
            period_start, period_end, db
        )
        for inspection in inspections:
            source_key = ("quality_inspection", int(inspection["id"]))
            normalized_quality_source_keys.add(source_key)
            candidates = (
                PerformanceHistoryMigrationRepository.quality_candidate_work_records(
                    inspection.get("order_id"), inspection.get("process_id"), db
                )
            )
            candidate_user_ids = sorted(
                {
                    int(item["user_id"])
                    for item in candidates
                    if item.get("user_id") is not None
                }
            )
            user_id = candidate_user_ids[0] if len(candidate_user_ids) == 1 else None
            requires_confirmation = (
                source_key in ambiguity_keys or len(candidate_user_ids) != 1
            )
            if requires_confirmation:
                virtual_ambiguity_keys.add(source_key)
            business_at = inspection.get("business_at") or ""
            boundary = cls._calendar_month(business_at) != production_month
            classification = (
                "production_month_boundary"
                if boundary
                else "production_month_quality_inspection"
            )
            if requires_confirmation:
                classification += "+quality_source_confirmation_required"
            related_ncr_ids = sorted(
                int(value)
                for value in str(inspection.get("related_ncr_ids") or "").split(",")
                if value
            )
            if related_ncr_ids:
                classification += "+explicit_source_relation"
                if user_id is not None:
                    multi_source_quality_user_ids.add(user_id)
            if boundary and user_id is not None:
                cross_quality_user_ids.add(user_id)
            records.append(
                cls._record(
                    "quality_inspection",
                    inspection["id"],
                    classification,
                    {
                        "order_id": inspection.get("order_id"),
                        "process_id": inspection.get("process_id"),
                        "quantity_failed": inspection.get("quantity_failed") or 0,
                        "defect_quantity": inspection.get("defect_quantity") or 0,
                        "result": inspection.get("result") or "",
                        "business_at": business_at,
                        "candidate_work_record_ids": [
                            int(item["id"]) for item in candidates
                        ],
                        "candidate_user_ids": candidate_user_ids,
                        "related_ncr_ids": related_ncr_ids,
                    },
                    user_id=user_id,
                    business_at=business_at,
                )
            )

        quality_events = PerformanceHistoryMigrationRepository.quality_events(
            period_start, period_end, db
        )
        for event in quality_events:
            sources = sorted(
                event.get("sources") or [],
                key=lambda item: (item["source_type"], int(item["source_id"])),
            )
            event_snapshot = cls._json_object(event.get("snapshot_json"))
            if event_snapshot.get("historical_migration"):
                continue
            classification = (
                "canonical_quality_event_boundary"
                if cls._calendar_month(event.get("business_at")) != production_month
                else "canonical_quality_event"
            )
            if len(sources) > 1:
                if event.get("user_id") is not None:
                    multi_source_quality_user_ids.add(int(event["user_id"]))
            if cls._calendar_month(event.get("business_at")) != production_month:
                if event.get("user_id") is not None:
                    cross_quality_user_ids.add(int(event["user_id"]))
            records.append(
                cls._record(
                    "quality_event",
                    event["id"],
                    classification,
                    {
                        "event_type": event.get("event_type") or "",
                        "quantity": event.get("quantity") or 0,
                        "order_id": event.get("order_id"),
                        "process_id": event.get("process_id"),
                        "user_id": event.get("user_id"),
                        "business_at": event.get("business_at") or "",
                        "event_digest": event.get("event_digest") or "",
                        "snapshot": event_snapshot,
                    },
                    user_id=event.get("user_id"),
                    business_at=event.get("business_at") or "",
                )
            )

        quality_ambiguity_ids = []
        for exception in ambiguity_rows:
            snapshot = cls._json_object(exception.get("snapshot_json"))
            quality_ambiguity_ids.append(int(exception["id"]))
            source_type = str(exception.get("source_type") or "")
            source_id = int(exception.get("source_id") or 0)
            if (source_type, source_id) in normalized_quality_source_keys:
                continue
            records.append(
                cls._record(
                    "quality_ambiguity_" + source_type,
                    source_id,
                    "quality_source_confirmation_required",
                    {
                        "user_id": exception.get("user_id"),
                        "source_type": source_type,
                        "source_id": source_id,
                        "status": exception.get("status") or "pending",
                        "snapshot": snapshot,
                    },
                    user_id=exception.get("user_id"),
                    business_at=snapshot.get("business_at") or exception.get("created_at") or "",
                )
            )

        for assignment in PerformanceHistoryMigrationRepository.assignments(
            period_start, period_end, db
        ):
            records.append(
                cls._record(
                    "assignment_history",
                    assignment["id"],
                    "historical_assignment_snapshot",
                    {
                        "user_id": assignment.get("user_id"),
                        "position_id": assignment.get("position_id"),
                        "position_name_snapshot": assignment.get("position_name_snapshot") or "",
                        "department_id": assignment.get("department_id"),
                        "department_name_snapshot": assignment.get("department_name_snapshot") or "",
                        "valid_from": assignment.get("valid_from") or "",
                        "valid_to": assignment.get("valid_to") or "",
                        "source_type": assignment.get("source_type") or "",
                        "source_key": assignment.get("source_key") or "",
                    },
                    user_id=assignment.get("user_id"),
                    business_at=assignment.get("valid_from") or "",
                )
            )

        for target in targets.values():
            records.append(
                cls._record(
                    "position_target",
                    target["id"],
                    "approved_position_target",
                    {
                        "position_id": target.get("position_id"),
                        "target_output_qty": target.get("target_output_qty"),
                        "minimum_effective_work_days": target.get("minimum_effective_work_days"),
                        "effective_from_month": target.get("effective_from_month") or "",
                        "effective_to_month": target.get("effective_to_month") or "",
                        "status": target.get("status") or "",
                    },
                    business_at=production_month + "-01 07:00:00",
                )
            )

        for rule in PerformanceHistoryMigrationRepository.published_rules(
            production_month, db
        ):
            records.append(
                cls._record(
                    "rule_version",
                    rule["id"],
                    "published_rule",
                    {
                        "version_code": rule.get("version_code") or "",
                        "effective_from_month": rule.get("effective_from_month") or "",
                        "effective_to_month": rule.get("effective_to_month") or "",
                        "weights_json": rule.get("weights_json") or "{}",
                        "warning_levels_json": rule.get("warning_levels_json") or "{}",
                        "scoring_parameters_json": rule.get("scoring_parameters_json") or "{}",
                    },
                    business_at=production_month + "-01 07:00:00",
                )
            )

        for plan in PerformanceHistoryMigrationRepository.improvement_plans(
            production_month, db
        ):
            records.append(
                cls._record(
                    "improvement_plan",
                    plan["id"],
                    "historical_plan_snapshot",
                    {
                        "user_id": plan.get("user_id"),
                        "status": plan.get("status") or "",
                        "updated_at": plan.get("updated_at") or "",
                        "reassessment_round": plan.get("reassessment_round") or 0,
                        "legacy_plan_id": plan.get("legacy_plan_id"),
                    },
                    user_id=plan.get("user_id"),
                    business_at=plan.get("updated_at") or plan.get("created_at") or "",
                )
            )

        records.append(
            cls._record(
                "legacy_manifest",
                legacy_manifest["id"],
                "legacy_v1_manifest",
                {
                    "production_month": production_month,
                    "legacy_batch_id": legacy_batch["id"],
                    "source_score_count": legacy_manifest.get("source_score_count") or 0,
                    "overwritten_score_count": legacy_manifest.get("overwritten_score_count") or 0,
                    "missing_position_count": legacy_manifest.get("missing_position_count") or 0,
                    "records_json": legacy_manifest.get("records_json") or "[]",
                    "manifest_sha256": legacy_manifest.get("manifest_sha256") or "",
                },
                business_at=period_start,
            )
        )

        records.sort(key=lambda item: item["stable_key"])
        manifest_document = {
            "format": MANIFEST_FORMAT,
            "production_month": production_month,
            "period_start": period_start,
            "period_end": period_end,
            "legacy_batch_id": legacy_batch["id"],
            "legacy_manifest_id": legacy_manifest["id"],
            "legacy_manifest_sha256": legacy_manifest.get("manifest_sha256") or "",
            "records": records,
        }
        manifest_sha256 = cls._digest(manifest_document)
        return {
            "production_month": production_month,
            "period_start": period_start,
            "period_end": period_end,
            "legacy_batch_id": legacy_batch["id"],
            "legacy_manifest_id": legacy_manifest["id"],
            "legacy_manifest_sha256": legacy_manifest.get("manifest_sha256") or "",
            "legacy_score_count": len(scores),
            "overwritten_score_count": overwritten_score_count,
            "missing_position_count": missing_position_count,
            "cross_month_work_count": len(cross_work),
            "cross_month_quality_count": len(cross_quality),
            "quality_ambiguity_count": len(ambiguity_keys | virtual_ambiguity_keys),
            "missing_target_count": len(missing_target_user_ids),
            "cross_month_work_ids": [int(row["id"]) for row in cross_work],
            "cross_month_quality_ids": [int(row["id"]) for row in cross_quality],
            "quality_ambiguity_ids": quality_ambiguity_ids,
            "cross_month_work_user_ids": sorted(cross_work_user_ids),
            "cross_month_quality_user_ids": sorted(cross_quality_user_ids),
            "multi_source_quality_user_ids": sorted(multi_source_quality_user_ids),
            "missing_target_user_ids": sorted(missing_target_user_ids),
            "records": records,
            "manifest_sha256": manifest_sha256,
        }

    @classmethod
    def analyze(cls, db, start_month="", end_month=""):
        cls._require_schema(db)
        start_month, end_month = cls._month_bounds(start_month, end_month)
        months = PerformanceHistoryMigrationRepository.legacy_months(
            start_month, end_month, db
        )
        month_plans = [cls._month_plan(month, db) for month in months]
        totals = {
            "legacy_score_count": sum(item["legacy_score_count"] for item in month_plans),
            "overwritten_score_count": sum(
                item["overwritten_score_count"] for item in month_plans
            ),
            "missing_position_count": sum(
                item["missing_position_count"] for item in month_plans
            ),
            "cross_month_work_count": sum(
                item["cross_month_work_count"] for item in month_plans
            ),
            "cross_month_quality_count": sum(
                item["cross_month_quality_count"] for item in month_plans
            ),
            "quality_ambiguity_count": sum(
                item["quality_ambiguity_count"] for item in month_plans
            ),
            "missing_target_count": sum(
                item["missing_target_count"] for item in month_plans
            ),
        }
        global_document = {
            "format": MANIFEST_FORMAT,
            "start_month": start_month,
            "end_month": end_month,
            "months": [
                {
                    "production_month": item["production_month"],
                    "legacy_batch_id": item["legacy_batch_id"],
                    "manifest_sha256": item["manifest_sha256"],
                    "legacy_score_count": item["legacy_score_count"],
                    "overwritten_score_count": item["overwritten_score_count"],
                    "missing_position_count": item["missing_position_count"],
                    "cross_month_work_count": item["cross_month_work_count"],
                    "cross_month_quality_count": item["cross_month_quality_count"],
                    "quality_ambiguity_count": item["quality_ambiguity_count"],
                    "missing_target_count": item["missing_target_count"],
                }
                for item in month_plans
            ],
            "totals": totals,
        }
        return {
            "format": MANIFEST_FORMAT,
            "start_month": start_month,
            "end_month": end_month,
            "months": month_plans,
            "totals": totals,
            "manifest_sha256": cls._digest(global_document),
        }

    @classmethod
    def validate_counts(cls, plan, expected_counts):
        if not isinstance(expected_counts, dict):
            raise RuntimeError("必须提供历史绩效审计基线")
        missing = [field for field in BASELINE_FIELDS if field not in expected_counts]
        if missing:
            raise RuntimeError("历史绩效审计基线缺少: " + ", ".join(missing))
        mismatched = []
        actual = plan.get("totals") or {}
        for field in BASELINE_FIELDS:
            try:
                expected = int(expected_counts[field])
            except (TypeError, ValueError) as exc:
                raise RuntimeError("历史绩效审计基线必须是整数") from exc
            if expected < 0:
                raise RuntimeError("历史绩效审计基线不能为负数")
            if int(actual.get(field, 0)) != expected:
                mismatched.append(
                    f"{field}: expected={expected}, actual={int(actual.get(field, 0))}"
                )
        if mismatched:
            raise RuntimeError("历史绩效审计基线不一致: " + "; ".join(mismatched))
        return True

    @classmethod
    def _ensure_historical_quality_sources(cls, month_plan, db):
        evaluations = (
            PerformanceHistoryMigrationRepository.process_quality_evaluations(
                month_plan["period_start"], month_plan["period_end"], db
            )
        )
        mapped_evaluations = 0
        mapped_scrap = 0
        mapped_rework = 0
        mapped_inspections = 0
        ambiguity_created = 0
        for evaluation in evaluations:
            if evaluation.get("quality_event_id"):
                continue
            user_id = evaluation.get("target_user_id") or evaluation.get(
                "handoff_target_user_id"
            )
            target_work_record_id = evaluation.get("target_work_record_id")
            source_type = "process_quality_evaluation"
            source_id = int(evaluation["id"])
            if target_work_record_id is not None or user_id is not None:
                related_sources = []
                if evaluation.get("source_handoff_review_id"):
                    related_sources.append(
                        (
                            "process_handoff_review",
                            int(evaluation["source_handoff_review_id"]),
                        )
                    )
                PerformanceQualityEventService.record_event(
                    event_type="process_handoff",
                    source_type=source_type,
                    source_id=source_id,
                    quantity=evaluation.get("quantity") or 0,
                    order_id=evaluation.get("order_id"),
                    process_id=evaluation.get("target_process_id"),
                    user_id=(None if target_work_record_id else user_id),
                    business_at=evaluation.get("created_at") or "",
                    target_work_record_id=target_work_record_id,
                    related_sources=related_sources,
                    snapshot={
                        "historical_migration": True,
                        "evaluator_process_id": evaluation.get(
                            "evaluator_process_id"
                        ),
                        "evaluator_user_id": evaluation.get("evaluator_user_id"),
                        "total_score": evaluation.get("total_score"),
                        "grade": evaluation.get("grade") or "",
                        "status": evaluation.get("status") or "",
                        "source_handoff_review_id": evaluation.get(
                            "source_handoff_review_id"
                        ),
                    },
                    db=db,
                )
                mapped_evaluations += 1
                continue

            existing = (
                PerformanceHistoryMigrationRepository.historical_quality_ambiguity(
                    source_type, source_id, db
                )
            )
            if existing:
                continue
            candidates = (
                PerformanceHistoryMigrationRepository.quality_candidate_work_records(
                    evaluation.get("order_id"),
                    evaluation.get("target_process_id"),
                    db,
                )
            )
            snapshot = {
                "business_at": evaluation.get("created_at") or "",
                "order_id": evaluation.get("order_id"),
                "process_id": evaluation.get("target_process_id"),
                "quantity": evaluation.get("quantity") or 0,
                "candidates": [
                    {
                        "source_type": "work_record",
                        "source_id": int(item["id"]),
                        "user_id": item.get("user_id"),
                    }
                    for item in candidates
                ],
            }
            PerformanceHistoryMigrationRepository.insert_historical_quality_ambiguity(
                {
                    "source_type": source_type,
                    "source_id": source_id,
                    "user_id": None,
                    "snapshot_json": cls._canonical(snapshot),
                },
                db,
            )
            ambiguity_created += 1

        inspections = PerformanceHistoryMigrationRepository.quality_inspections(
            month_plan["period_start"], month_plan["period_end"], db
        )
        for inspection in inspections:
            if inspection.get("quality_event_id"):
                continue
            source_type = "quality_inspection"
            source_id = int(inspection["id"])
            candidates = (
                PerformanceHistoryMigrationRepository.quality_candidate_work_records(
                    inspection.get("order_id"), inspection.get("process_id"), db
                )
            )
            candidate_user_ids = sorted(
                {
                    int(item["user_id"])
                    for item in candidates
                    if item.get("user_id") is not None
                }
            )
            if len(candidate_user_ids) == 1:
                related_sources = [
                    ("quality_ncr", int(value))
                    for value in str(
                        inspection.get("related_ncr_ids") or ""
                    ).split(",")
                    if value
                ]
                PerformanceQualityEventService.record_event(
                    event_type="inspection_failed",
                    source_type=source_type,
                    source_id=source_id,
                    quantity=inspection.get("quantity_failed") or 0,
                    order_id=inspection.get("order_id"),
                    process_id=inspection.get("process_id"),
                    user_id=candidate_user_ids[0],
                    business_at=inspection.get("business_at") or "",
                    related_sources=related_sources,
                    snapshot={
                        "historical_migration": True,
                        "result": inspection.get("result") or "",
                        "defect_quantity": inspection.get("defect_quantity") or 0,
                    },
                    db=db,
                )
                mapped_inspections += 1
                continue
            existing = (
                PerformanceHistoryMigrationRepository.historical_quality_ambiguity(
                    source_type, source_id, db
                )
            )
            if existing:
                continue
            PerformanceHistoryMigrationRepository.insert_historical_quality_ambiguity(
                {
                    "source_type": source_type,
                    "source_id": source_id,
                    "user_id": None,
                    "snapshot_json": cls._canonical(
                        {
                            "business_at": inspection.get("business_at") or "",
                            "order_id": inspection.get("order_id"),
                            "process_id": inspection.get("process_id"),
                            "quantity": inspection.get("quantity_failed") or 0,
                            "candidates": [
                                {
                                    "source_type": "work_record",
                                    "source_id": int(item["id"]),
                                    "user_id": item.get("user_id"),
                                }
                                for item in candidates
                            ],
                        }
                    ),
                },
                db,
            )
            ambiguity_created += 1

        source_specs = (
            (
                "scrap_record",
                "scrap",
                PerformanceHistoryMigrationRepository.scrap_records(
                    month_plan["period_start"], month_plan["period_end"], db
                ),
            ),
            (
                "rework_record",
                "rework",
                PerformanceHistoryMigrationRepository.rework_records(
                    month_plan["period_start"], month_plan["period_end"], db
                ),
            ),
        )
        for source_type, event_type, rows in source_specs:
            for source in rows:
                if source.get("quality_event_id"):
                    continue
                related_sources = []
                if source_type == "rework_record" and source.get("source_ncr_id"):
                    related_sources.append(
                        ("quality_ncr", int(source["source_ncr_id"]))
                    )
                PerformanceQualityEventService.record_event(
                    event_type=event_type,
                    source_type=source_type,
                    source_id=source["id"],
                    quantity=source.get("quantity") or 0,
                    order_id=source.get("order_id"),
                    process_id=source.get("process_id"),
                    user_id=source.get("user_id"),
                    business_at=source.get("created_at") or "",
                    related_sources=related_sources,
                    snapshot={
                        "historical_migration": True,
                        "reason": source.get("reason") or "",
                        "source_ncr_id": source.get("source_ncr_id"),
                    },
                    db=db,
                )
                if source_type == "scrap_record":
                    mapped_scrap += 1
                else:
                    mapped_rework += 1
        return {
            "mapped_quality_evaluation_count": mapped_evaluations,
            "mapped_scrap_count": mapped_scrap,
            "mapped_rework_count": mapped_rework,
            "mapped_quality_inspection_count": mapped_inspections,
            "created_quality_ambiguity_count": ambiguity_created,
        }

    @classmethod
    def _comparison(cls, month_plan, batch_id, db):
        legacy_batch = PerformanceHistoryMigrationRepository.legacy_batch(
            month_plan["production_month"], db
        )
        legacy_rows = {
            int(row["user_id"]): row
            for row in PerformanceHistoryMigrationRepository.legacy_scores(
                legacy_batch["id"], db
            )
        }
        v2_rows = {
            int(row["user_id"]): row
            for row in PerformanceHistoryMigrationRepository.score_revisions(
                batch_id, db
            )
        }
        users = sorted(set(legacy_rows) | set(v2_rows))
        boundary_users = set(month_plan["cross_month_work_user_ids"]) | set(
            month_plan["cross_month_quality_user_ids"]
        )
        quality_users = set(month_plan["multi_source_quality_user_ids"])
        target_users = set(month_plan["missing_target_user_ids"])
        comparison_fields = (
            "eligibility_status",
            "output_qty",
            "report_count",
            "work_days",
            "scrap_qty",
            "rework_qty",
            "inspection_failed_qty",
            "output_score",
            "quality_score",
            "delivery_score",
            "discipline_score",
            "improvement_score",
            "total_score",
            "rank_no",
            "rank_total",
            "discipline_deduction",
            "discipline_reason",
            "improvement_deduction",
            "improvement_reason",
            "manual_score",
            "manual_comment",
        )
        review_fields = {
            "discipline_score",
            "improvement_score",
            "discipline_deduction",
            "discipline_reason",
            "improvement_deduction",
            "improvement_reason",
            "manual_score",
            "manual_comment",
        }
        quality_fields = {"quality_score", "scrap_qty", "rework_qty", "inspection_failed_qty"}
        rows = []
        reason_counts = Counter()
        for user_id in users:
            legacy = legacy_rows.get(user_id)
            v2 = v2_rows.get(user_id)
            changed_fields = []
            for field in comparison_fields:
                if (legacy or {}).get(field) != (v2 or {}).get(field):
                    changed_fields.append(field)
            reasons = []
            if user_id in boundary_users:
                reasons.append("month_boundary")
            if user_id in target_users or "output_score" in changed_fields:
                reasons.append("position_target")
            if user_id in quality_users or quality_fields.intersection(changed_fields):
                reasons.append("quality_deduplication")
            if (legacy or {}).get("eligibility_status") != (v2 or {}).get(
                "eligibility_status"
            ) or (v2 and v2.get("eligibility_status") == "insufficient_data"):
                reasons.append("eligibility")
            if review_fields.intersection(changed_fields):
                reasons.append("supervisor_review")
            if changed_fields and not reasons:
                reasons.append("rule_change")
            for reason in reasons:
                reason_counts[reason] += 1
            rows.append(
                {
                    "user_id": user_id,
                    "employee_name": (v2 or legacy or {}).get(
                        "employee_name_snapshot", ""
                    ),
                    "employee_no": (v2 or legacy or {}).get(
                        "employee_no_snapshot", ""
                    ),
                    "legacy_score": (legacy or {}).get("total_score"),
                    "v2_score": (v2 or {}).get("total_score"),
                    "legacy_eligibility": (legacy or {}).get("eligibility_status"),
                    "v2_eligibility": (v2 or {}).get("eligibility_status"),
                    "changed_fields": changed_fields,
                    "reasons": reasons,
                }
            )
        return {"rows": rows, "reason_counts": dict(sorted(reason_counts.items()))}

    @classmethod
    def _stored_result(cls, month_plan, event, db):
        payload = cls._json_object(event.get("payload_json"))
        if payload.get("migration_manifest_sha256") != month_plan["manifest_sha256"]:
            raise RuntimeError(
                f"生产月 {month_plan['production_month']} 迁移清单与当前来源不一致"
            )
        if payload.get("legacy_batch_id") != month_plan["legacy_batch_id"]:
            raise RuntimeError("历史绩效迁移 Legacy 批次关联不一致")
        batch = PerformanceHistoryMigrationRepository.batch(event["batch_id"], db)
        if not batch:
            raise RuntimeError("历史绩效迁移事件关联的 V2 批次不存在")
        return {
            "production_month": month_plan["production_month"],
            "batch": batch,
            "event_id": event["id"],
            "comparison": payload.get("comparison") or {"rows": [], "reason_counts": {}},
            "quality_backfill": payload.get("quality_backfill") or {},
            "idempotent_replay": True,
        }

    @classmethod
    def apply(
        cls,
        db,
        start_month,
        end_month,
        preparer_id,
        expected_counts,
    ):
        db.execute("BEGIN IMMEDIATE")
        try:
            plan = cls.analyze(db, start_month, end_month)
            cls.validate_counts(plan, expected_counts)
            if not plan["months"]:
                raise RuntimeError("指定范围没有可迁移的 Legacy 绩效月份")
            preparer = PerformanceHistoryMigrationRepository.preparer(
                preparer_id, db
            )
            if not preparer or preparer.get("status") not in (None, "active"):
                raise RuntimeError("指定的历史绩效制单人不存在或未启用")
            actor_name = preparer.get("name") or preparer.get("username") or ""
            actor = {
                "id": int(preparer_id),
                "name": actor_name,
                "_permissions": ["performance:prepare"],
            }
            payroll_before = PerformanceHistoryMigrationRepository.payroll_fingerprint(db)
            applied_months = []
            for month_plan in plan["months"]:
                production_month = month_plan["production_month"]
                event_key = f"{EVENT_PREFIX}:{production_month}:v2:event"
                existing_event = PerformanceHistoryMigrationRepository.event_by_idempotency(
                    event_key, db
                )
                if existing_event:
                    applied_months.append(cls._stored_result(month_plan, existing_event, db))
                    continue
                idempotency_key = f"{EVENT_PREFIX}:{production_month}:v2"
                incomplete_batch = PerformanceHistoryMigrationRepository.batch_by_idempotency(
                    idempotency_key, db
                )
                if incomplete_batch:
                    raise RuntimeError(
                        f"生产月 {production_month} 存在未完成的历史绩效 V2 批次"
                    )
                next_version = PerformanceHistoryMigrationRepository.next_version(
                    production_month, db
                )
                if next_version != 2:
                    raise RuntimeError(
                        f"生产月 {production_month} 下一版本不是 V2，而是 V{next_version}"
                    )
                quality_backfill = cls._ensure_historical_quality_sources(
                    month_plan, db
                )
                created = PerformanceLedgerService.create_batch(
                    {
                        "production_month": production_month,
                        "source_cutoff_at": "",
                        "idempotency_key": idempotency_key,
                        "revision_reason": "历史 Legacy V1 影子迁移，待主管复核",
                        "request_id": f"{EVENT_PREFIX}:{production_month}:v2:request",
                    },
                    actor,
                    db=db,
                )
                batch = PerformanceHistoryMigrationRepository.batch(
                    created["batch_id"], db
                )
                if not batch or int(batch["version"]) != 2:
                    raise RuntimeError(f"生产月 {production_month} V2 批次生成失败")
                if batch["status"] not in ("draft", "supervisor_review"):
                    raise RuntimeError("历史绩效迁移只能生成草稿或主管复核批次")
                comparison = cls._comparison(month_plan, batch["id"], db)
                payload = {
                    "format": MANIFEST_FORMAT,
                    "production_month": production_month,
                    "legacy_batch_id": month_plan["legacy_batch_id"],
                    "legacy_manifest_id": month_plan["legacy_manifest_id"],
                    "migration_manifest_sha256": month_plan["manifest_sha256"],
                    "batch_input_digest": batch["input_digest"],
                    "audit_counts": {
                        field: month_plan[field]
                        for field in (
                            "legacy_score_count",
                            "overwritten_score_count",
                            "missing_position_count",
                            "cross_month_work_count",
                            "cross_month_quality_count",
                            "quality_ambiguity_count",
                            "missing_target_count",
                        )
                    },
                    "records": month_plan["records"],
                    "comparison": comparison,
                    "quality_backfill": quality_backfill,
                }
                event_id = PerformanceLedgerRepository.insert_batch_event(
                    {
                        "batch_id": batch["id"],
                        "event_type": "historical_revision_generated",
                        "from_status": "",
                        "to_status": batch["status"],
                        "operator_id": preparer_id,
                        "operator_name": actor_name,
                        "reason": "历史 Legacy V1 影子迁移，待主管复核",
                        "payload_json": cls._canonical(payload),
                        "request_id": f"{EVENT_PREFIX}:{production_month}:v2:request",
                        "idempotency_key": event_key,
                    },
                    db,
                )
                applied_months.append(
                    {
                        "production_month": production_month,
                        "batch": batch,
                        "event_id": event_id,
                        "comparison": comparison,
                        "quality_backfill": quality_backfill,
                        "idempotent_replay": False,
                    }
                )
            payroll_after = PerformanceHistoryMigrationRepository.payroll_fingerprint(db)
            if payroll_after != payroll_before:
                raise RuntimeError("绩效历史迁移不得写入工资台账")
            db.commit()
            return {"plan": plan, "months": applied_months}
        except Exception:
            db.rollback()
            raise
