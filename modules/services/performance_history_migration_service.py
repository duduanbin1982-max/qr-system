"""Preflight and controlled generation of historical performance V2 revisions."""

from collections import Counter
from collections.abc import Mapping
import json

from modules.domain import evidence_protocol
from modules.domain.performance_policy import validate_production_month
from modules.domain.reporting_day import reporting_month_bounds
from modules.services.performance_history_planning import (
    PerformanceHistoryMonthInputs,
    build_month_plan,
)
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
        def thaw_json(item):
            if isinstance(item, Mapping):
                return {key: thaw_json(child) for key, child in item.items()}
            if isinstance(item, (list, tuple)):
                return [thaw_json(child) for child in item]
            if isinstance(item, (set, frozenset)):
                return [thaw_json(child) for child in item]
            return item

        if isinstance(value, Mapping):
            return thaw_json(value)
        try:
            parsed = json.loads(value or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("历史绩效迁移来源快照 JSON 无效") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("历史绩效迁移来源快照必须是 JSON 对象")
        return thaw_json(parsed)

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
    def _month_inputs(cls, production_month, db):
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
        work_records = PerformanceHistoryMigrationRepository.work_records(
            period_start, period_end, db
        )
        work_time_records = PerformanceHistoryMigrationRepository.work_time_records(
            period_start, period_end, db
        )
        ambiguity_rows = PerformanceHistoryMigrationRepository.quality_ambiguities(
            period_start, period_end, db
        )
        quality_evaluations = (
            PerformanceHistoryMigrationRepository.process_quality_evaluations(
                period_start, period_end, db
            )
        )
        scrap_records = PerformanceHistoryMigrationRepository.scrap_records(
            period_start, period_end, db
        )
        rework_records = PerformanceHistoryMigrationRepository.rework_records(
            period_start, period_end, db
        )
        inspections = PerformanceHistoryMigrationRepository.quality_inspections(
            period_start, period_end, db
        )
        inspection_candidates = {
            (inspection.get("order_id"), inspection.get("process_id")): (
                PerformanceHistoryMigrationRepository.quality_candidate_work_records(
                    inspection.get("order_id"), inspection.get("process_id"), db
                )
            )
            for inspection in inspections
        }
        return PerformanceHistoryMonthInputs(
            production_month=production_month,
            period_start=period_start,
            period_end=period_end,
            legacy_batch=legacy_batch,
            legacy_manifest=legacy_manifest,
            scores=scores,
            targets=targets,
            work_records=work_records,
            work_time_records=work_time_records,
            ambiguity_rows=ambiguity_rows,
            quality_evaluations=quality_evaluations,
            scrap_records=scrap_records,
            rework_records=rework_records,
            inspections=inspections,
            inspection_candidates=inspection_candidates,
            quality_events=PerformanceHistoryMigrationRepository.quality_events(
                period_start, period_end, db
            ),
            assignments=PerformanceHistoryMigrationRepository.assignments(
                period_start, period_end, db
            ),
            rules=PerformanceHistoryMigrationRepository.published_rules(
                production_month, db
            ),
            improvement_plans=PerformanceHistoryMigrationRepository.improvement_plans(
                production_month, db
            ),
        )

    @classmethod
    def _month_plan(cls, production_month, db):
        inputs = cls._month_inputs(production_month, db)
        return build_month_plan(
            inputs,
            record=cls._record,
            score_record=cls._score_record,
            json_object=cls._json_object,
            calendar_month=cls._calendar_month,
            digest=cls._digest,
        )

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
    def _assert_month_snapshot(cls, planned_month, current_month):
        """Reject writes when the read-only plan no longer matches the source."""
        fields = (
            "production_month",
            "legacy_batch_id",
            "legacy_manifest_id",
            "manifest_sha256",
            "source_snapshot_sha256",
        )
        mismatched = [
            field
            for field in fields
            if planned_month.get(field) != current_month.get(field)
        ]
        if mismatched:
            raise RuntimeError(
                f"生产月 {planned_month['production_month']} 来源快照已漂移: "
                + ", ".join(mismatched)
            )

    @classmethod
    def _write_month_plan(cls, month_plan, preparer_id, actor, actor_name, db):
        """Persist one already-planned month in the caller's short transaction."""
        production_month = month_plan["production_month"]
        event_key = f"{EVENT_PREFIX}:{production_month}:v2:event"
        existing_event = PerformanceHistoryMigrationRepository.event_by_idempotency(
            event_key, db
        )
        if existing_event:
            return cls._stored_result(month_plan, existing_event, db)
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
        quality_backfill = cls._ensure_historical_quality_sources(month_plan, db)
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
        batch = PerformanceHistoryMigrationRepository.batch(created["batch_id"], db)
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
            "source_snapshot_sha256": month_plan.get("source_snapshot_sha256", ""),
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
        return {
            "production_month": production_month,
            "batch": batch,
            "event_id": event_id,
            "comparison": comparison,
            "quality_backfill": quality_backfill,
            "idempotent_replay": False,
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
        # Planning and all source validation are read-only.  Keep them outside
        # the write transaction so a large historical range does not hold a
        # RESERVED lock while pure facts and manifests are being assembled.
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
        applied_months = []
        for planned_month in plan["months"]:
            # Each production month gets its own short atomic write transaction.
            # Re-read and compare the source snapshot while the write lock is held
            # so a concurrent source edit cannot produce a stale V2 revision.
            db.execute("BEGIN IMMEDIATE")
            try:
                current_month = cls._month_plan(
                    planned_month["production_month"], db
                )
                cls._assert_month_snapshot(planned_month, current_month)
                payroll_before = PerformanceHistoryMigrationRepository.payroll_fingerprint(
                    db
                )
                applied_months.append(
                    cls._write_month_plan(
                        planned_month,
                        preparer_id,
                        actor,
                        actor_name,
                        db,
                    )
                )
                payroll_after = PerformanceHistoryMigrationRepository.payroll_fingerprint(
                    db
                )
                if payroll_after != payroll_before:
                    raise RuntimeError("绩效历史迁移不得写入工资台账")
                db.commit()
            except Exception:
                db.rollback()
                raise
        return {"plan": plan, "months": applied_months}
