"""Pure planning stages for historical performance migration.

The planner accepts repository snapshots and never opens a database.
The application service remains responsible for loading rows and transaction scope.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from modules.domain import evidence_protocol
from modules.services import performance_quality_planning


MANIFEST_FORMAT = "performance_history_migration_manifest_v1"


@dataclass(frozen=True)
class PerformanceHistoryMonthInputs:
    production_month: str
    period_start: str
    period_end: str
    legacy_batch: Mapping
    legacy_manifest: Mapping
    scores: tuple
    targets: Mapping
    work_records: tuple
    work_time_records: tuple
    ambiguity_rows: tuple
    quality_evaluations: tuple
    scrap_records: tuple
    rework_records: tuple
    inspections: tuple
    inspection_candidates: Mapping
    quality_events: tuple
    assignments: tuple
    rules: tuple
    improvement_plans: tuple

    def __post_init__(self):
        """Freeze the complete repository snapshot, including nested values.

        ``frozen=True`` only protects assignment to dataclass attributes.  The
        planner must also be protected from a caller mutating a nested row
        after the snapshot has been loaded, so every list/dict/set is copied and
        recursively frozen here.
        """
        for field_name in self.__dataclass_fields__:
            object.__setattr__(
                self,
                field_name,
                _freeze_snapshot(getattr(self, field_name)),
            )


def _freeze_snapshot(value):
    """Return a recursively immutable copy of a repository snapshot value."""
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                _freeze_snapshot(key): _freeze_snapshot(item)
                for key, item in value.items()
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_snapshot(item) for item in value)
    if isinstance(value, (set, frozenset)):
        items = tuple(_freeze_snapshot(item) for item in value)
        try:
            return frozenset(items)
        except TypeError:
            # A repository snapshot may contain a set of structured rows.  A
            # tuple is still immutable and preserves every value when the
            # members themselves are not hashable.
            return tuple(sorted(items, key=repr))
    return value


def _thaw_snapshot(value):
    """Convert an immutable snapshot back to JSON-compatible containers."""
    if isinstance(value, Mapping):
        return {
            (
                _thaw_snapshot(key)
                if isinstance(key, (str, int, float, bool)) or key is None
                else repr(_thaw_snapshot(key))
            ): _thaw_snapshot(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_thaw_snapshot(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_thaw_snapshot(item) for item in sorted(value, key=repr)]
    return value


def _snapshot_document(inputs):
    """Return a deterministic, JSON-compatible document for month inputs."""
    return {
        field_name: _thaw_snapshot(getattr(inputs, field_name))
        for field_name in inputs.__dataclass_fields__
    }


@dataclass(frozen=True)
class ScorePlanningResult:
    records: tuple
    overwritten_score_count: int
    missing_position_count: int
    missing_target_user_ids: tuple


@dataclass(frozen=True)
class WorkPlanningResult:
    records: tuple
    cross_month_work_count: int
    cross_month_work_ids: tuple
    cross_month_work_user_ids: tuple


@dataclass(frozen=True)
class QualityPlanningResult:
    records: tuple
    cross_month_quality_count: int
    cross_month_quality_ids: tuple
    quality_ambiguity_count: int
    quality_ambiguity_ids: tuple
    cross_month_quality_user_ids: tuple
    multi_source_quality_user_ids: tuple


@dataclass(frozen=True)
class ReferencePlanningResult:
    records: tuple


@dataclass(frozen=True)
class CoverageStatistics:
    """Stable counts and identifiers derived from all pure planning phases."""

    legacy_score_count: int
    overwritten_score_count: int
    missing_position_count: int
    cross_month_work_count: int
    cross_month_quality_count: int
    quality_ambiguity_count: int
    missing_target_count: int
    cross_month_work_ids: tuple
    cross_month_quality_ids: tuple
    quality_ambiguity_ids: tuple
    cross_month_work_user_ids: tuple
    cross_month_quality_user_ids: tuple
    multi_source_quality_user_ids: tuple
    missing_target_user_ids: tuple


@dataclass(frozen=True)
class ManifestSummary:
    """The sorted evidence records and digest emitted by the pure planner."""

    records: tuple
    manifest_sha256: str


@dataclass(frozen=True)
class PerformanceHistoryMonthPlan:
    """Immutable stage output; conversion to legacy dictionaries is explicit."""

    production_month: str
    period_start: str
    period_end: str
    legacy_batch_id: int
    legacy_manifest_id: int
    legacy_manifest_sha256: str
    coverage: CoverageStatistics
    manifest: ManifestSummary
    source_snapshot_sha256: str = ""

    def as_dict(self):
        coverage = self.coverage
        return {
            "production_month": self.production_month,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "legacy_batch_id": self.legacy_batch_id,
            "legacy_manifest_id": self.legacy_manifest_id,
            "legacy_manifest_sha256": self.legacy_manifest_sha256,
            "legacy_score_count": coverage.legacy_score_count,
            "overwritten_score_count": coverage.overwritten_score_count,
            "missing_position_count": coverage.missing_position_count,
            "cross_month_work_count": coverage.cross_month_work_count,
            "cross_month_quality_count": coverage.cross_month_quality_count,
            "quality_ambiguity_count": coverage.quality_ambiguity_count,
            "missing_target_count": coverage.missing_target_count,
            "cross_month_work_ids": list(coverage.cross_month_work_ids),
            "cross_month_quality_ids": list(coverage.cross_month_quality_ids),
            "quality_ambiguity_ids": list(coverage.quality_ambiguity_ids),
            "cross_month_work_user_ids": list(coverage.cross_month_work_user_ids),
            "cross_month_quality_user_ids": list(coverage.cross_month_quality_user_ids),
            "multi_source_quality_user_ids": list(
                coverage.multi_source_quality_user_ids
            ),
            "missing_target_user_ids": list(coverage.missing_target_user_ids),
            "records": _thaw_snapshot(self.manifest.records),
            "manifest_sha256": self.manifest.manifest_sha256,
            "source_snapshot_sha256": self.source_snapshot_sha256,
        }


def canonical_json(value):
    return evidence_protocol.canonical_json_v1(value)


def digest(value):
    return evidence_protocol.sha256_digest_v1(value)


def _plan_scores(inputs, *, score_record, production_month):
    """Plan legacy score facts and validate their immutable manifest counts."""
    records = []
    missing_target_user_ids = set()
    overwritten_score_count = 0
    missing_position_count = 0
    for score in inputs.scores:
        score_record_result = score_record(
            score, production_month, inputs.targets
        )
        records.append(score_record_result)
        if score.get("prior_revisions_unavailable"):
            overwritten_score_count += 1
        if score.get("position_id_snapshot") is None or not score.get(
            "position_name_snapshot"
        ):
            missing_position_count += 1
        if "missing_position_target" in score_record_result["classification"]:
            missing_target_user_ids.add(int(score["user_id"]))

    mismatched_legacy_counts = [
        field
        for field, actual in (
            ("overwritten_score_count", overwritten_score_count),
            ("missing_position_count", missing_position_count),
        )
        if int(inputs.legacy_manifest.get(field) or 0) != actual
    ]
    if mismatched_legacy_counts:
        raise RuntimeError(
            f"生产月 {production_month} Legacy manifest 分类数量不一致: "
            + ", ".join(mismatched_legacy_counts)
        )
    return ScorePlanningResult(
        records=tuple(records),
        overwritten_score_count=overwritten_score_count,
        missing_position_count=missing_position_count,
        missing_target_user_ids=tuple(sorted(missing_target_user_ids)),
    )


def _plan_work(inputs, *, record, calendar_month, production_month):
    """Plan work and work-time facts, including production-month boundaries."""
    records = []
    cross_work = []
    cross_work_user_ids = set()
    for work in inputs.work_records:
        classification = (
            "production_month_boundary"
            if calendar_month(work["business_at"]) != production_month
            else "production_month_work"
        )
        if classification == "production_month_boundary":
            cross_work.append(work)
            if work.get("user_id") is not None:
                cross_work_user_ids.add(int(work["user_id"]))
        records.append(
            record(
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

    for work_time in inputs.work_time_records:
        records.append(
            record(
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
    return WorkPlanningResult(
        records=tuple(records),
        cross_month_work_count=len(cross_work),
        cross_month_work_ids=tuple(int(row["id"]) for row in cross_work),
        cross_month_work_user_ids=tuple(sorted(cross_work_user_ids)),
    )


def plan_quality_facts(
    inputs, *, record, json_object, calendar_month, production_month
):
    """Adapt immutable source commands to the historical result contract."""
    aggregation = performance_quality_planning.plan_quality_sources(
        quality_evaluations=inputs.quality_evaluations,
        scrap_records=inputs.scrap_records,
        rework_records=inputs.rework_records,
        inspections=inputs.inspections,
        inspection_candidates=inputs.inspection_candidates,
        quality_events=inputs.quality_events,
        ambiguity_rows=inputs.ambiguity_rows,
        json_object=json_object,
        calendar_month=calendar_month,
        production_month=production_month,
    )
    return QualityPlanningResult(
        records=tuple(command.materialize(record) for command in aggregation.commands),
        cross_month_quality_count=len(aggregation.cross_month_ids),
        cross_month_quality_ids=aggregation.cross_month_ids,
        quality_ambiguity_count=aggregation.quality_ambiguity_count,
        quality_ambiguity_ids=aggregation.quality_ambiguity_ids,
        cross_month_quality_user_ids=aggregation.cross_month_user_ids,
        multi_source_quality_user_ids=aggregation.multi_source_user_ids,
    )


def _plan_reference_records(inputs, *, record, production_month):
    """Plan assignment, target, rule, and improvement-plan reference facts."""
    records = []
    for assignment in inputs.assignments:
        records.append(
            record(
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
    for target in inputs.targets.values():
        records.append(
            record(
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
    for rule in inputs.rules:
        records.append(
            record(
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
    for plan in inputs.improvement_plans:
        records.append(
            record(
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
    return ReferencePlanningResult(records=tuple(records))


def plan_history_score_facts(inputs, *, score_record, production_month):
    """Public pure stage for legacy history score facts."""
    return _plan_scores(
        inputs,
        score_record=score_record,
        production_month=production_month,
    )


def plan_work_time_facts(inputs, *, record, calendar_month, production_month):
    """Public pure stage for work and work-time facts."""
    return _plan_work(
        inputs,
        record=record,
        calendar_month=calendar_month,
        production_month=production_month,
    )


def plan_reference_facts(inputs, *, record, production_month):
    """Public pure stage for position and personnel reference facts."""
    return _plan_reference_records(
        inputs,
        record=record,
        production_month=production_month,
    )


def plan_coverage_statistics(inputs, *, score_plan, work_plan, quality_plan):
    """Compute coverage and missing-source statistics without database access."""
    return CoverageStatistics(
        legacy_score_count=len(inputs.scores),
        overwritten_score_count=score_plan.overwritten_score_count,
        missing_position_count=score_plan.missing_position_count,
        cross_month_work_count=work_plan.cross_month_work_count,
        cross_month_quality_count=quality_plan.cross_month_quality_count,
        quality_ambiguity_count=quality_plan.quality_ambiguity_count,
        missing_target_count=len(score_plan.missing_target_user_ids),
        cross_month_work_ids=work_plan.cross_month_work_ids,
        cross_month_quality_ids=quality_plan.cross_month_quality_ids,
        quality_ambiguity_ids=quality_plan.quality_ambiguity_ids,
        cross_month_work_user_ids=work_plan.cross_month_work_user_ids,
        cross_month_quality_user_ids=quality_plan.cross_month_quality_user_ids,
        multi_source_quality_user_ids=quality_plan.multi_source_quality_user_ids,
        missing_target_user_ids=score_plan.missing_target_user_ids,
    )


def build_manifest_records(inputs, *, score_plan, work_plan, quality_plan, reference_plan, record):
    """Build the sorted evidence records, keeping the historical record format."""
    production_month = inputs.production_month
    period_start = inputs.period_start
    legacy_batch = inputs.legacy_batch
    legacy_manifest = inputs.legacy_manifest
    records = [
        *score_plan.records,
        *work_plan.records,
        *quality_plan.records,
        *reference_plan.records,
    ]
    records.append(
        record(
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
    return tuple(records)


def summarize_manifest(inputs, *, records, digest):
    """Create the manifest document and digest as a pure terminal stage."""
    frozen_records = tuple(_freeze_snapshot(record) for record in records)
    manifest_document = {
        "format": MANIFEST_FORMAT,
        "production_month": inputs.production_month,
        "period_start": inputs.period_start,
        "period_end": inputs.period_end,
        "legacy_batch_id": inputs.legacy_batch["id"],
        "legacy_manifest_id": inputs.legacy_manifest["id"],
        "legacy_manifest_sha256": inputs.legacy_manifest.get("manifest_sha256") or "",
        "records": _thaw_snapshot(frozen_records),
    }
    return ManifestSummary(
        records=frozen_records,
        manifest_sha256=digest(manifest_document),
    )


def build_month_plan_result(
    inputs,
    *,
    record,
    score_record,
    json_object,
    calendar_month,
    digest,
):
    """Compose independent pure stages into an immutable month plan result."""
    score_plan = plan_history_score_facts(
        inputs,
        score_record=score_record,
        production_month=inputs.production_month,
    )
    work_plan = plan_work_time_facts(
        inputs,
        record=record,
        calendar_month=calendar_month,
        production_month=inputs.production_month,
    )
    quality_plan = plan_quality_facts(
        inputs,
        record=record,
        json_object=json_object,
        calendar_month=calendar_month,
        production_month=inputs.production_month,
    )
    reference_plan = plan_reference_facts(
        inputs,
        record=record,
        production_month=inputs.production_month,
    )
    coverage = plan_coverage_statistics(
        inputs,
        score_plan=score_plan,
        work_plan=work_plan,
        quality_plan=quality_plan,
    )
    records = build_manifest_records(
        inputs,
        score_plan=score_plan,
        work_plan=work_plan,
        quality_plan=quality_plan,
        reference_plan=reference_plan,
        record=record,
    )
    manifest = summarize_manifest(inputs, records=records, digest=digest)
    return PerformanceHistoryMonthPlan(
        production_month=inputs.production_month,
        period_start=inputs.period_start,
        period_end=inputs.period_end,
        legacy_batch_id=inputs.legacy_batch["id"],
        legacy_manifest_id=inputs.legacy_manifest["id"],
        legacy_manifest_sha256=inputs.legacy_manifest.get("manifest_sha256") or "",
        coverage=coverage,
        manifest=manifest,
        source_snapshot_sha256=digest(_snapshot_document(inputs)),
    )


def build_month_plan(
    inputs,
    *,
    record,
    score_record,
    json_object,
    calendar_month,
    digest,
):
    """Compatibility boundary returning the historical dictionary shape."""
    return build_month_plan_result(
        inputs,
        record=record,
        score_record=score_record,
        json_object=json_object,
        calendar_month=calendar_month,
        digest=digest,
    ).as_dict()
