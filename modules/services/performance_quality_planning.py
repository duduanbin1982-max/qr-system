"""Pure, source-specific quality planning stages for history migration.

The planners accept an immutable repository snapshot and return immutable
commands.  They do not open a database, mutate shared state, or persist
quality events; the migration service remains the only persistence boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType(
            {_freeze(key): _freeze(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        items = tuple(_freeze(item) for item in value)
        try:
            return frozenset(items)
        except TypeError:
            return tuple(sorted(items, key=repr))
    return value


def _thaw(value):
    if isinstance(value, Mapping):
        return {_thaw(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_thaw(item) for item in sorted(value, key=repr)]
    return value


@dataclass(frozen=True)
class QualityEventCommand:
    """Immutable command handed from one pure source planner to the writer."""

    source_type: str
    source_id: int
    classification: str
    payload: Mapping
    user_id: int | None = None
    business_at: str = ""

    def __post_init__(self):
        object.__setattr__(self, "source_type", str(self.source_type))
        object.__setattr__(self, "source_id", int(self.source_id))
        object.__setattr__(self, "classification", str(self.classification))
        object.__setattr__(self, "payload", _freeze(self.payload))
        # Preserve scalar types from the repository snapshot.  The historical
        # writer includes these values in its source digest without coercion.
        object.__setattr__(self, "user_id", self.user_id)
        object.__setattr__(self, "business_at", self.business_at or "")

    def materialize(self, record):
        """Convert to the historical record dictionary at the evidence boundary."""
        return record(
            self.source_type,
            self.source_id,
            self.classification,
            _thaw(self.payload),
            user_id=self.user_id,
            business_at=self.business_at,
        )


@dataclass(frozen=True)
class QualitySourcePlan:
    commands: tuple[QualityEventCommand, ...]
    cross_month_ids: tuple[int, ...] = ()
    cross_month_user_ids: tuple[int, ...] = ()
    multi_source_user_ids: tuple[int, ...] = ()
    normalized_source_keys: tuple[tuple[str, int], ...] = ()
    virtual_ambiguity_keys: tuple[tuple[str, int], ...] = ()


def _plan(
    commands,
    *,
    cross_month_ids=(),
    cross_month_user_ids=(),
    multi_source_user_ids=(),
    normalized_source_keys=(),
    virtual_ambiguity_keys=(),
):
    return QualitySourcePlan(
        commands=tuple(commands),
        cross_month_ids=tuple(int(value) for value in cross_month_ids),
        cross_month_user_ids=tuple(sorted({int(value) for value in cross_month_user_ids})),
        multi_source_user_ids=tuple(sorted({int(value) for value in multi_source_user_ids})),
        normalized_source_keys=tuple(
            sorted((str(source_type), int(source_id)) for source_type, source_id in normalized_source_keys)
        ),
        virtual_ambiguity_keys=tuple(
            sorted((str(source_type), int(source_id)) for source_type, source_id in virtual_ambiguity_keys)
        ),
    )


def plan_process_quality_evaluations(
    rows, *, ambiguity_keys, calendar_month, production_month
):
    commands = []
    cross_month_ids = []
    cross_month_user_ids = []
    multi_source_user_ids = []
    normalized_keys = []
    virtual_ambiguity_keys = []
    for evaluation in rows:
        user_id = evaluation.get("target_user_id") or evaluation.get(
            "handoff_target_user_id"
        )
        source_key = ("process_quality_evaluation", int(evaluation["id"]))
        normalized_keys.append(source_key)
        requires_confirmation = source_key in ambiguity_keys or (
            evaluation.get("target_work_record_id") is None and user_id is None
        )
        if requires_confirmation:
            virtual_ambiguity_keys.append(source_key)
        boundary = calendar_month(evaluation.get("created_at")) != production_month
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
                multi_source_user_ids.append(user_id)
        if boundary:
            cross_month_ids.append(evaluation["id"])
            if user_id is not None:
                cross_month_user_ids.append(user_id)
        commands.append(
            QualityEventCommand(
                "process_quality_evaluation",
                evaluation["id"],
                classification,
                {
                    "order_id": evaluation.get("order_id"),
                    "target_process_id": evaluation.get("target_process_id"),
                    "target_work_record_id": evaluation.get("target_work_record_id"),
                    "target_user_id": evaluation.get("target_user_id"),
                    "handoff_target_user_id": evaluation.get("handoff_target_user_id"),
                    "quantity": evaluation.get("quantity") or 0,
                    "total_score": evaluation.get("total_score"),
                    "grade": evaluation.get("grade") or "",
                    "status": evaluation.get("status") or "",
                    "source_handoff_review_id": evaluation.get("source_handoff_review_id"),
                    "created_at": evaluation.get("created_at") or "",
                    "updated_at": evaluation.get("updated_at") or "",
                },
                user_id=user_id,
                business_at=evaluation.get("created_at") or "",
            )
        )
    return _plan(
        commands,
        cross_month_ids=cross_month_ids,
        cross_month_user_ids=cross_month_user_ids,
        multi_source_user_ids=multi_source_user_ids,
        normalized_source_keys=normalized_keys,
        virtual_ambiguity_keys=virtual_ambiguity_keys,
    )


def plan_scrap_records(rows, *, calendar_month, production_month):
    return _plan_quality_records(
        rows,
        source_type="scrap_record",
        event_type="scrap",
        calendar_month=calendar_month,
        production_month=production_month,
    )


def plan_rework_records(rows, *, calendar_month, production_month):
    return _plan_quality_records(
        rows,
        source_type="rework_record",
        event_type="rework",
        calendar_month=calendar_month,
        production_month=production_month,
    )


def _plan_quality_records(rows, *, source_type, event_type, calendar_month, production_month):
    commands = []
    cross_month_ids = []
    cross_month_user_ids = []
    multi_source_user_ids = []
    normalized_keys = []
    for source in rows:
        source_key = (source_type, int(source["id"]))
        normalized_keys.append(source_key)
        business_at = source.get("created_at") or ""
        boundary = calendar_month(business_at) != production_month
        classification = "production_month_boundary" if boundary else "production_month_" + event_type
        if source_type == "rework_record" and source.get("source_ncr_id"):
            classification += "+explicit_source_relation"
            if source.get("user_id") is not None:
                multi_source_user_ids.append(source["user_id"])
        if boundary:
            cross_month_ids.append(source["id"])
            if source.get("user_id") is not None:
                cross_month_user_ids.append(source["user_id"])
        commands.append(
            QualityEventCommand(
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
    return _plan(
        commands,
        cross_month_ids=cross_month_ids,
        cross_month_user_ids=cross_month_user_ids,
        multi_source_user_ids=multi_source_user_ids,
        normalized_source_keys=normalized_keys,
    )


def plan_quality_inspections(
    rows, candidates, *, ambiguity_keys, calendar_month, production_month
):
    commands = []
    cross_month_ids = []
    cross_month_user_ids = []
    multi_source_user_ids = []
    normalized_keys = []
    virtual_ambiguity_keys = []
    for inspection in rows:
        source_key = ("quality_inspection", int(inspection["id"]))
        normalized_keys.append(source_key)
        inspection_candidates = candidates.get(
            (inspection.get("order_id"), inspection.get("process_id")), []
        )
        candidate_user_ids = sorted(
            {
                int(item["user_id"])
                for item in inspection_candidates
                if item.get("user_id") is not None
            }
        )
        user_id = candidate_user_ids[0] if len(candidate_user_ids) == 1 else None
        requires_confirmation = source_key in ambiguity_keys or len(candidate_user_ids) != 1
        if requires_confirmation:
            virtual_ambiguity_keys.append(source_key)
        business_at = inspection.get("business_at") or ""
        boundary = calendar_month(business_at) != production_month
        classification = "production_month_boundary" if boundary else "production_month_quality_inspection"
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
                multi_source_user_ids.append(user_id)
        if boundary and user_id is not None:
            cross_month_user_ids.append(user_id)
        if boundary:
            cross_month_ids.append(inspection["id"])
        commands.append(
            QualityEventCommand(
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
                        int(item["id"]) for item in inspection_candidates
                    ],
                    "candidate_user_ids": candidate_user_ids,
                    "related_ncr_ids": related_ncr_ids,
                },
                user_id=user_id,
                business_at=business_at,
            )
        )
    return _plan(
        commands,
        cross_month_ids=cross_month_ids,
        cross_month_user_ids=cross_month_user_ids,
        multi_source_user_ids=multi_source_user_ids,
        normalized_source_keys=normalized_keys,
        virtual_ambiguity_keys=virtual_ambiguity_keys,
    )


def plan_canonical_quality_events(rows, *, json_object, calendar_month, production_month):
    commands = []
    cross_month_ids = []
    cross_month_user_ids = []
    multi_source_user_ids = []
    for event in rows:
        sources = sorted(
            event.get("sources") or [],
            key=lambda item: (item["source_type"], int(item["source_id"])),
        )
        event_snapshot = json_object(event.get("snapshot_json"))
        if event_snapshot.get("historical_migration"):
            continue
        business_at = event.get("business_at") or ""
        boundary = calendar_month(business_at) != production_month
        classification = "canonical_quality_event_boundary" if boundary else "canonical_quality_event"
        if len(sources) > 1 and event.get("user_id") is not None:
            multi_source_user_ids.append(event["user_id"])
        if boundary:
            cross_month_ids.append(event["id"])
            if event.get("user_id") is not None:
                cross_month_user_ids.append(event["user_id"])
        commands.append(
            QualityEventCommand(
                "quality_event",
                event["id"],
                classification,
                {
                    "event_type": event.get("event_type") or "",
                    "quantity": event.get("quantity") or 0,
                    "order_id": event.get("order_id"),
                    "process_id": event.get("process_id"),
                    "user_id": event.get("user_id"),
                    "business_at": business_at,
                    "event_digest": event.get("event_digest") or "",
                    "snapshot": event_snapshot,
                },
                user_id=event.get("user_id"),
                business_at=business_at,
            )
        )
    return _plan(
        commands,
        cross_month_ids=cross_month_ids,
        cross_month_user_ids=cross_month_user_ids,
        multi_source_user_ids=multi_source_user_ids,
    )


def plan_quality_ambiguities(rows, *, normalized_source_keys, json_object):
    commands = []
    quality_ambiguity_ids = []
    normalized_keys = set(normalized_source_keys)
    for exception in rows:
        snapshot = json_object(exception.get("snapshot_json"))
        quality_ambiguity_ids.append(int(exception["id"]))
        source_type = str(exception.get("source_type") or "")
        source_id = int(exception.get("source_id") or 0)
        if (source_type, source_id) in normalized_keys:
            continue
        commands.append(
            QualityEventCommand(
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
                business_at=snapshot.get("business_at")
                or exception.get("created_at")
                or "",
            )
        )
    return _plan(commands), tuple(quality_ambiguity_ids)


@dataclass(frozen=True)
class QualityPlanningAggregation:
    """Immutable aggregate used by the legacy manifest composer."""

    commands: tuple[QualityEventCommand, ...]
    cross_month_ids: tuple[int, ...]
    cross_month_user_ids: tuple[int, ...]
    multi_source_user_ids: tuple[int, ...]
    normalized_source_keys: tuple[tuple[str, int], ...]
    virtual_ambiguity_keys: tuple[tuple[str, int], ...]
    ambiguity_keys: tuple[tuple[str, int], ...]
    quality_ambiguity_ids: tuple[int, ...]

    @property
    def quality_ambiguity_count(self):
        return len(set(self.ambiguity_keys) | set(self.virtual_ambiguity_keys))


def plan_quality_sources(
    *,
    quality_evaluations,
    scrap_records,
    rework_records,
    inspections,
    inspection_candidates,
    quality_events,
    ambiguity_rows,
    json_object,
    calendar_month,
    production_month,
):
    ambiguity_keys = {
        (str(row.get("source_type") or ""), int(row.get("source_id") or 0))
        for row in ambiguity_rows
    }
    evaluation_plan = plan_process_quality_evaluations(
        quality_evaluations,
        ambiguity_keys=ambiguity_keys,
        calendar_month=calendar_month,
        production_month=production_month,
    )
    scrap_plan = plan_scrap_records(
        scrap_records, calendar_month=calendar_month, production_month=production_month
    )
    rework_plan = plan_rework_records(
        rework_records, calendar_month=calendar_month, production_month=production_month
    )
    inspection_plan = plan_quality_inspections(
        inspections,
        inspection_candidates,
        ambiguity_keys=ambiguity_keys,
        calendar_month=calendar_month,
        production_month=production_month,
    )
    event_plan = plan_canonical_quality_events(
        quality_events,
        json_object=json_object,
        calendar_month=calendar_month,
        production_month=production_month,
    )
    normalized_keys = (
        *evaluation_plan.normalized_source_keys,
        *scrap_plan.normalized_source_keys,
        *rework_plan.normalized_source_keys,
        *inspection_plan.normalized_source_keys,
    )
    ambiguity_plan, ambiguity_ids = plan_quality_ambiguities(
        ambiguity_rows,
        normalized_source_keys=normalized_keys,
        json_object=json_object,
    )
    plans = (evaluation_plan, scrap_plan, rework_plan, inspection_plan, event_plan, ambiguity_plan)
    return QualityPlanningAggregation(
        commands=tuple(command for plan in plans for command in plan.commands),
        # The legacy manifest counted boundary process evaluations only.  Keep
        # that historical coverage field stable while source-specific planners
        # still expose their own boundary IDs for future evidence consumers.
        cross_month_ids=evaluation_plan.cross_month_ids,
        cross_month_user_ids=tuple(
            sorted({value for plan in plans for value in plan.cross_month_user_ids})
        ),
        multi_source_user_ids=tuple(
            sorted({value for plan in plans for value in plan.multi_source_user_ids})
        ),
        normalized_source_keys=tuple(sorted(set(normalized_keys))),
        virtual_ambiguity_keys=tuple(
            sorted(
                set(evaluation_plan.virtual_ambiguity_keys)
                | set(inspection_plan.virtual_ambiguity_keys)
            )
        ),
        ambiguity_keys=tuple(sorted(ambiguity_keys)),
        quality_ambiguity_ids=tuple(ambiguity_ids),
    )
