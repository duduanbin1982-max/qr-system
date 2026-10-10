"""Pure planning-stage value objects and deterministic result summaries.

This module deliberately has no database, Flask, repository, or service imports.
It is the seam used by schedule generation and dynamic re-planning while their
transactional use cases remain in the service layer.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType
from typing import Any, Mapping, Sequence


def _freeze(value: Any) -> Any:
    """Recursively make planning inputs immutable."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return value


def _thaw(value: Any) -> Any:
    """Return JSON-compatible data for stable hashing and API payloads."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_thaw(item) for item in value]
    return value


def _digest(value: Any) -> str:
    payload = json.dumps(
        _thaw(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def decode_run_result_payload(run: Mapping[str, Any]) -> dict[str, Any]:
    """Decode legacy list or Task 5 result-envelope rows."""
    try:
        result = json.loads(run["result_json"] or "[]")
    except (TypeError, json.JSONDecodeError):
        result = []
    if isinstance(result, dict):
        operations = result.get("operations")
        return {
            **result,
            "operations": operations if isinstance(operations, list) else [],
        }
    return {"operations": result if isinstance(result, list) else []}


@dataclass(frozen=True, slots=True)
class PlanningFactsSnapshot:
    """Immutable facts shared by all pure planning stages."""

    order: Mapping[str, Any]
    operations: tuple[Mapping[str, Any], ...]
    order_serial_ids: tuple[str, ...]
    cursor: Any
    standard_as_of: str
    use_node_engine: bool
    occupancy: Mapping[Any, tuple[Any, ...]]
    input_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "order", _freeze(self.order))
        object.__setattr__(
            self,
            "operations",
            tuple(_freeze(operation) for operation in self.operations),
        )
        object.__setattr__(self, "order_serial_ids", tuple(self.order_serial_ids))
        object.__setattr__(self, "occupancy", _freeze(self.occupancy))

    @classmethod
    def create(
        cls,
        *,
        order: Mapping[str, Any],
        operations: Sequence[Mapping[str, Any]],
        order_serial_ids: Sequence[str] = (),
        cursor: Any,
        standard_as_of: str,
        use_node_engine: bool,
        occupancy: Mapping[Any, Sequence[Any]] | None = None,
    ) -> "PlanningFactsSnapshot":
        payload = {
            "order": order,
            "operations": operations,
            "order_serial_ids": tuple(order_serial_ids),
            "cursor": cursor.isoformat() if hasattr(cursor, "isoformat") else cursor,
            "standard_as_of": standard_as_of,
            "use_node_engine": bool(use_node_engine),
            "occupancy": occupancy or {},
        }
        return cls(
            order=order,
            operations=tuple(operations),
            order_serial_ids=tuple(order_serial_ids),
            cursor=cursor,
            standard_as_of=str(standard_as_of or ""),
            use_node_engine=bool(use_node_engine),
            occupancy=occupancy or {},
            input_digest=_digest(payload),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "order": _thaw(self.order),
            "operations": _thaw(self.operations),
            "order_serial_ids": list(self.order_serial_ids),
            "cursor": self.cursor.isoformat()
            if hasattr(self.cursor, "isoformat")
            else self.cursor,
            "standard_as_of": self.standard_as_of,
            "use_node_engine": self.use_node_engine,
            "occupancy": _thaw(self.occupancy),
            "input_digest": self.input_digest,
        }


@dataclass(frozen=True, slots=True)
class WorkTimeMatch:
    """Pure result of exact route/process-version work-time matching."""

    operation_key: Any
    standard: Mapping[str, Any] | None
    match_scope: str
    blocked_code: str = ""
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "standard", _freeze(self.standard or {}))


@dataclass(frozen=True, slots=True)
class OperationPlanningContext:
    """Immutable operation facts handed to the pure planning stages."""

    common: Mapping[str, Any]
    remaining_quantity: int
    completed_quantity: int
    rework_quantity: int
    process_name: str
    route_name: str
    cursor: Any

    def __post_init__(self) -> None:
        object.__setattr__(self, "common", _freeze(self.common))


@dataclass(frozen=True, slots=True)
class OperationPlanningDecision:
    """Immutable decision produced by the pure per-operation planning gates."""

    disposition: str
    blocked_code: str = ""
    blocked_reason: str = ""
    execution_mode: str = "internal"
    external_lead_minutes: float = 0
    standard: Mapping[str, Any] | None = None
    candidates: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "standard", _freeze(self.standard or {}))
        object.__setattr__(
            self, "candidates", tuple(_freeze(candidate) for candidate in self.candidates)
        )


def decide_operation_planning(
    context: OperationPlanningContext,
    *,
    upstream_blocked: bool = False,
    upstream_blocked_code: str = "UPSTREAM_BLOCKED",
    upstream_blocked_reason: str = "前序工序无法排程",
    execution_policy: Mapping[str, Any] | None = None,
    standard: Mapping[str, Any] | None = None,
    standard_resolved: bool = False,
    candidates: Sequence[Mapping[str, Any]] | None = None,
    candidate_blocked_code: str = "NO_COMPATIBLE_NODE",
    candidate_blocked_reason: str = "没有满足能力要求的生产节点",
) -> OperationPlanningDecision:
    """Resolve deterministic planning gates from already-loaded immutable facts.

    Services are responsible for fetching facts and persisting the decision's
    payload.  This pure policy owns the business ordering: completion and
    upstream dependency gates, external routing, exact work-time availability,
    resource availability, then allocation readiness.
    """
    if context.remaining_quantity <= 0:
        return OperationPlanningDecision("completed")
    if upstream_blocked:
        return OperationPlanningDecision(
            "blocked", upstream_blocked_code, upstream_blocked_reason
        )
    policy = dict(execution_policy or {})
    standard_facts = dict(standard or {})
    candidate_facts = (
        tuple(dict(candidate) for candidate in candidates)
        if candidates is not None
        else None
    )
    mode = str(policy.get("execution_mode") or "internal")
    if mode in {"outsourced", "non_scheduled"}:
        return OperationPlanningDecision(
            "external",
            execution_mode=mode,
            external_lead_minutes=max(
                float(policy.get("external_lead_minutes") or 0), 0
            ),
        )
    if standard_resolved and not standard:
        return OperationPlanningDecision(
            "blocked", "MISSING_WORK_TIME_STANDARD", "未配置标准工时"
        )
    if candidates is not None and not candidates:
        return OperationPlanningDecision(
            "blocked", candidate_blocked_code, candidate_blocked_reason,
            standard=standard_facts,
        )
    if not standard_resolved or candidate_facts is None:
        return OperationPlanningDecision("pending", standard=standard_facts)
    return OperationPlanningDecision(
        "allocation_ready", standard=standard_facts, candidates=candidate_facts
    )


def build_operation_context(
    *,
    order: Mapping[str, Any],
    operation: Mapping[str, Any],
    remaining_quantity: int,
    completed_quantity: int,
    rework_quantity: int,
    cursor: Any,
    run_key: str,
    run_id: Any,
    revision_id: Any,
    source_fact_digest: str = "",
) -> OperationPlanningContext:
    """Build the immutable facts shared by completion, blocking and allocation."""
    # SQLite rows implement the mapping protocol but do not expose ``get`` or
    # guarantee a plain-dict copy across all adapters.  Normalize at this
    # pure-domain boundary so every caller (generation, replan, and tests)
    # receives the same immutable input shape without leaking database row
    # objects into planning logic.
    order = dict(order)
    operation = dict(operation)
    process_name = str(
        operation.get("process_name_snapshot") or operation.get("process_name") or ""
    )
    route_name = str(
        operation.get("route_name_snapshot")
        or order.get("route_name_snapshot")
        or ""
    )
    common = {
        "order_id": order["id"] if "id" in order else order.get("order_id"),
        "order_process_id": operation["order_process_id"],
        "process_id": operation["process_id"],
        "seq_order": operation["seq_order"],
        "quantity": int(remaining_quantity),
        "route_version_id": operation.get("route_version_id") or order.get("route_version_id"),
        "completed_quantity_snapshot": int(completed_quantity),
        "rework_quantity_snapshot": int(rework_quantity),
        "remaining_quantity_snapshot": int(remaining_quantity),
        "process_version_id": operation.get("process_version_id"),
        "process_name_snapshot": process_name,
        "route_name_snapshot": route_name,
        "schedule_run_key": run_key,
        "schedule_run_id": run_id,
        "schedule_revision_id": revision_id,
    }
    if source_fact_digest:
        common["source_fact_digest"] = source_fact_digest
    return OperationPlanningContext(
        common=common,
        remaining_quantity=int(remaining_quantity),
        completed_quantity=int(completed_quantity),
        rework_quantity=int(rework_quantity),
        process_name=process_name,
        route_name=route_name,
        cursor=cursor,
    )


def build_completed_payload(
    context: OperationPlanningContext,
    *,
    plan_start: str,
    plan_end: str,
    reason: str,
    standard_version: Any = None,
    standard_minutes_per_unit: Any = 0,
    setup_minutes: Any = 0,
    difficulty_factor: Any = 1,
    planned_start_at: str = "",
    planned_end_at: str = "",
    include_allocations: bool = False,
) -> dict[str, Any]:
    """Create a completed operation payload without persistence or I/O."""
    payload = {
        **_thaw(context.common),
        "process_line_id": None,
        "production_node_id": None,
        "standard_id": None,
        "standard_version": standard_version,
        "standard_minutes_per_unit": standard_minutes_per_unit,
        "setup_minutes": setup_minutes,
        "difficulty_factor": difficulty_factor,
        "planned_minutes": 0,
        "occupied_minutes": 0,
        "plan_start": plan_start,
        "plan_end": plan_end,
        "planned_start_at": planned_start_at,
        "planned_end_at": planned_end_at,
        "status": "completed",
        "blocked_reason": "",
        "blocked_code": "",
        "line_name_snapshot": "",
        "segments": [],
        "reason": reason,
    }
    if include_allocations:
        payload["allocations"] = []
    return payload


def build_blocked_payload(
    context: OperationPlanningContext,
    *,
    cursor_date: str,
    code: str,
    reason: str,
    standard: Mapping[str, Any] | None = None,
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an explicit blocked outcome for an operation."""
    standard = standard or {}
    previous = previous or {}
    return {
        **_thaw(context.common),
        "process_line_id": None,
        "production_node_id": None,
        "standard_id": standard.get("id"),
        "standard_version": standard.get("version", previous.get("standard_version")),
        "standard_minutes_per_unit": standard.get(
            "standard_minutes_per_unit", previous.get("standard_minutes_per_unit", 0)
        ),
        "setup_minutes": standard.get("setup_minutes", previous.get("setup_minutes", 0)),
        "difficulty_factor": standard.get("difficulty_factor", previous.get("difficulty_factor", 1)),
        "planned_minutes": 0,
        "occupied_minutes": 0,
        "plan_start": cursor_date,
        "plan_end": cursor_date,
        "planned_start_at": "",
        "planned_end_at": "",
        "status": "blocked",
        "blocked_reason": reason,
        "blocked_code": code,
        "line_name_snapshot": "",
        "segments": [],
        "allocations": [],
        "reason": reason,
    }


def build_external_payload(
    context: OperationPlanningContext,
    *,
    execution_mode: str,
    lead_minutes: float,
    begin_at: str,
    end_at: str,
    begin_date: str,
    end_date: str,
) -> dict[str, Any]:
    """Create a non-scheduled operation payload without occupying capacity."""
    return {
        **_thaw(context.common),
        "process_line_id": None,
        "production_node_id": None,
        "execution_mode": execution_mode,
        "standard_id": None,
        "standard_version": None,
        "standard_minutes_per_unit": 0,
        "setup_minutes": 0,
        "difficulty_factor": 1,
        "planned_minutes": lead_minutes,
        "occupied_minutes": 0,
        "plan_start": begin_date,
        "plan_end": end_date,
        "planned_start_at": begin_at,
        "planned_end_at": end_at,
        "status": "planned",
        "blocked_reason": "",
        "blocked_code": "",
        "standard_match_scope": "execution_policy",
        "capacity_snapshot_json": json.dumps(
            {
                "execution_mode": execution_mode,
                "external_lead_minutes": lead_minutes,
                "route_version_id": context.common.get("route_version_id"),
                "process_version_id": context.common.get("process_version_id"),
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        "segments": [],
        "line_name_snapshot": "",
        "reason": "外协/非排程工序，不占用内部产能",
    }


@dataclass(frozen=True, slots=True)
class NodeCandidateSet:
    """Pure candidate-node selection result for one operation."""

    operation_key: Any
    candidates: tuple[Mapping[str, Any], ...]
    blocked_code: str = ""
    blocked_reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidates",
            tuple(_freeze(candidate) for candidate in self.candidates),
        )


@dataclass(frozen=True, slots=True)
class BlockedPlanningResult:
    """Explicit blocked outcome; callers must not turn it into an exception."""

    operation_key: Any
    code: str
    reason: str
    details: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", _freeze(self.details))


@dataclass(frozen=True, slots=True)
class PlanningManifest:
    """Stable manifest tying stage digests to one planning result."""

    algorithm: str
    input_digest: str
    stage_digests: Mapping[str, str]
    result_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "stage_digests", _freeze(self.stage_digests))

    def as_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "input_digest": self.input_digest,
            "stage_digests": dict(self.stage_digests),
            "result_digest": self.result_digest,
        }


@dataclass(frozen=True, slots=True)
class PlanningStageBundle:
    """Immutable hand-off between the seven pure planning stages."""

    facts: PlanningFactsSnapshot
    work_time_matches: tuple[WorkTimeMatch, ...]
    node_candidates: tuple[NodeCandidateSet, ...]
    allocations: tuple[Mapping[str, Any], ...]
    blocked: tuple[BlockedPlanningResult, ...]
    conflicts: tuple[Mapping[str, Any], ...]
    risk: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "allocations", tuple(_freeze(item) for item in self.allocations))
        object.__setattr__(self, "conflicts", tuple(_freeze(item) for item in self.conflicts))
        object.__setattr__(self, "risk", _freeze(self.risk or {}))

    def manifest_stages(self) -> dict[str, Any]:
        return {
            "facts": self.facts.as_dict(),
            "work_time_matches": [
                {
                    "operation_key": item.operation_key,
                    "match_scope": item.match_scope,
                    "standard": _thaw(item.standard),
                    "blocked_code": item.blocked_code,
                }
                for item in self.work_time_matches
            ],
            "node_candidates": [
                {
                    "operation_key": item.operation_key,
                    "candidate_ids": [
                        candidate.get("id") for candidate in item.candidates
                    ],
                    "blocked_code": item.blocked_code,
                }
                for item in self.node_candidates
            ],
            "allocations": _thaw(self.allocations),
            "blocked": [
                {
                    "operation_key": item.operation_key,
                    "code": item.code,
                    "reason": item.reason,
                    "details": _thaw(item.details),
                }
                for item in self.blocked
            ],
            "conflicts": _thaw(self.conflicts),
            "risk": _thaw(self.risk),
        }


def match_work_times(
    operations: Sequence[Mapping[str, Any]],
    standards: Mapping[Any, Mapping[str, Any] | None],
) -> tuple[WorkTimeMatch, ...]:
    """Match already-fetched standards without querying persistence."""
    matches: list[WorkTimeMatch] = []
    for operation in operations:
        key = operation.get("order_process_id", operation.get("id"))
        standard = standards.get(key)
        if standard:
            matches.append(
                WorkTimeMatch(
                    operation_key=key,
                    standard=standard,
                    match_scope=str(standard.get("match_scope") or "exact"),
                )
            )
        else:
            matches.append(
                WorkTimeMatch(
                    operation_key=key,
                    standard=None,
                    match_scope="missing",
                    blocked_code="MISSING_WORK_TIME_STANDARD",
                    blocked_reason="未配置标准工时",
                )
            )
    return tuple(matches)


def select_node_candidates(
    operations: Sequence[Mapping[str, Any]],
    candidates_by_operation: Mapping[Any, Sequence[Mapping[str, Any]]],
    *,
    blocked_code: str = "NO_COMPATIBLE_NODE",
    blocked_reason: str = "没有满足能力要求的生产节点",
) -> tuple[NodeCandidateSet, ...]:
    """Select candidate nodes from a supplied fact map."""
    selected: list[NodeCandidateSet] = []
    for operation in operations:
        key = operation.get("order_process_id", operation.get("id"))
        candidates = tuple(candidates_by_operation.get(key) or ())
        selected.append(
            NodeCandidateSet(
                operation_key=key,
                candidates=candidates,
                blocked_code="" if candidates else blocked_code,
                blocked_reason="" if candidates else blocked_reason,
            )
        )
    return tuple(selected)


def blocked_results(
    matches: Sequence[WorkTimeMatch],
    candidate_sets: Sequence[NodeCandidateSet],
) -> tuple[BlockedPlanningResult, ...]:
    """Combine independent blocking stages into explicit outcomes."""
    candidate_by_key = {item.operation_key: item for item in candidate_sets}
    result: list[BlockedPlanningResult] = []
    for match in matches:
        if match.blocked_code:
            result.append(
                BlockedPlanningResult(
                    match.operation_key,
                    match.blocked_code,
                    match.blocked_reason,
                    {"stage": "work_time"},
                )
            )
            continue
        candidate = candidate_by_key.get(match.operation_key)
        if candidate and candidate.blocked_code:
            result.append(
                BlockedPlanningResult(
                    candidate.operation_key,
                    candidate.blocked_code,
                    candidate.blocked_reason,
                    {"stage": "node_candidates"},
                )
            )
    return tuple(result)


def derive_stage_bundle(
    facts: PlanningFactsSnapshot,
    operations: Sequence[Mapping[str, Any]],
    *,
    conflicts: Sequence[Mapping[str, Any]] = (),
    risk: Mapping[str, Any] | None = None,
) -> PlanningStageBundle:
    """Derive immutable stage outputs from scheduler facts and operation results.

    Persistence-specific IDs are retained only as values; no stage performs I/O.
    This adapter lets the existing use cases migrate one stage at a time without
    changing their transaction/savepoint orchestration.
    """
    standards: dict[Any, Mapping[str, Any] | None] = {}
    candidate_map: dict[Any, tuple[Mapping[str, Any], ...]] = {}
    blocked_metadata: dict[Any, tuple[str, str]] = {}
    allocations: list[Mapping[str, Any]] = []
    for operation in operations:
        key = operation.get("order_process_id", operation.get("id"))
        standard = {
            "id": operation.get("standard_id"),
            "version": operation.get("standard_version"),
            "standard_minutes_per_unit": operation.get("standard_minutes_per_unit") or 0,
            "setup_minutes": operation.get("setup_minutes") or 0,
            "difficulty_factor": operation.get("difficulty_factor") or 1,
            "match_scope": operation.get("standard_match_scope") or "",
        }
        matched = bool(operation.get("standard_id")) or operation.get("execution_mode") in {
            "outsourced", "non_scheduled",
        }
        standards[key] = standard if matched else None
        resource_items = tuple(operation.get("nodes") or operation.get("lines") or ())
        candidate_map[key] = resource_items
        if operation.get("status") == "blocked":
            blocked_metadata[key] = (
                operation.get("blocked_code") or "UNKNOWN",
                operation.get("blocked_reason") or operation.get("reason") or "",
            )
        allocations.extend(operation.get("allocations") or ())
    matches = match_work_times(operations, standards)
    candidates = select_node_candidates(
        operations,
        candidate_map,
        blocked_code="NO_COMPATIBLE_NODE",
        blocked_reason="没有满足能力要求的生产节点",
    )
    blocked_by_key = {
        item.operation_key: item
        for item in blocked_results(matches, candidates)
    }
    for key, (code, reason) in blocked_metadata.items():
        blocked_by_key[key] = BlockedPlanningResult(
            key, code, reason, {"stage": "planning"}
        )
    return PlanningStageBundle(
        facts=facts,
        work_time_matches=matches,
        node_candidates=candidates,
        allocations=tuple(allocations),
        blocked=tuple(blocked_by_key.values()),
        conflicts=tuple(conflicts),
        risk=risk or {},
    )


def summarize_schedule_result(
    result: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    *,
    input_digest: str = "",
    manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a stable, persistence-independent schedule result summary."""
    if isinstance(result, Mapping):
        operations = tuple(result.get("operations") or ())
        conflicts = tuple(result.get("conflicts") or ())
        conflicts += tuple(result.get("revision_conflicts") or ())
        risk = result.get("risk") or {}
    else:
        operations = tuple(result or ())
        conflicts = ()
        risk = {}

    planned = tuple(item for item in operations if item.get("status") == "planned")
    blocked = tuple(item for item in operations if item.get("status") == "blocked")
    completed = tuple(item for item in operations if item.get("status") == "completed")
    external = tuple(
        item
        for item in operations
        if item.get("execution_mode") in {"outsourced", "non_scheduled"}
        or item.get("standard_match_scope") == "execution_policy"
    )
    planned_quantity = sum(int(item.get("quantity") or 0) for item in planned)
    allocated_quantity = 0
    quantity_conserved = True
    node_ids: set[int] = set()
    planned_minutes = 0.0
    occupied_minutes = 0.0
    for item in operations:
        allocations = tuple(item.get("allocations") or ())
        segments = tuple(item.get("segments") or ())
        if allocations:
            allocated = sum(int(allocation.get("quantity") or 0) for allocation in allocations)
            allocated_quantity += allocated
            if item.get("status") == "planned" and allocated != int(item.get("quantity") or 0):
                quantity_conserved = False
        elif item.get("status") == "planned" and item.get("execution_mode") not in {"outsourced", "non_scheduled"}:
            segmented = sum(int(segment.get("quantity") or 0) for segment in segments)
            if segmented and segmented != int(item.get("quantity") or 0):
                quantity_conserved = False
        for segment in segments:
            if segment.get("production_node_id") is not None:
                node_ids.add(int(segment["production_node_id"]))
        if item.get("production_node_id") is not None:
            node_ids.add(int(item["production_node_id"]))
        planned_minutes += float(item.get("planned_minutes") or 0)
        occupied_minutes += float(item.get("occupied_minutes") or 0)

    blocked_codes = Counter(str(item.get("blocked_code") or "UNKNOWN") for item in blocked)
    summary = {
        "operation_count": len(operations),
        "planned_operation_count": len(planned),
        "blocked_operation_count": len(blocked),
        "completed_operation_count": len(completed),
        "external_operation_count": len(external),
        "planned_quantity": planned_quantity,
        "allocated_quantity": allocated_quantity,
        "planned_minutes": round(planned_minutes, 6),
        "occupied_minutes": round(occupied_minutes, 6),
        "node_count": len(node_ids),
        "conflict_count": len(conflicts),
        "node_conflict_count": sum(
            1
            for conflict in conflicts
            if str(conflict.get("conflict_type") or conflict.get("code") or "").lower()
            in {"node", "node_capacity", "node_capacity_conflict", "downtime"}
        ),
        "blocked_codes": dict(sorted(blocked_codes.items())),
        "quantity_conserved": bool(quantity_conserved),
        "risk_level": str(risk.get("risk_level") or "none"),
        "delay_minutes": int(risk.get("delay_minutes") or 0),
        "input_digest": input_digest or "",
        "manifest_digest": _digest(manifest) if manifest else "",
    }
    summary["summary_digest"] = _digest(summary)
    return summary


def build_manifest(
    *,
    input_digest: str,
    stage_outputs: Mapping[str, Any],
    result: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    algorithm: str = "schedule-pure-planning-v1",
) -> PlanningManifest:
    """Build a deterministic stage manifest from immutable/pure outputs."""
    stage_digests = {name: _digest(value) for name, value in stage_outputs.items()}
    result_digest = _digest(result)
    return PlanningManifest(
        algorithm=algorithm,
        input_digest=input_digest,
        stage_digests=stage_digests,
        result_digest=result_digest,
    )


__all__ = [
    "BlockedPlanningResult",
    "NodeCandidateSet",
    "OperationPlanningContext",
    "PlanningFactsSnapshot",
    "PlanningManifest",
    "PlanningStageBundle",
    "WorkTimeMatch",
    "blocked_results",
    "build_manifest",
    "build_blocked_payload",
    "build_completed_payload",
    "build_external_payload",
    "build_operation_context",
    "derive_stage_bundle",
    "decode_run_result_payload",
    "match_work_times",
    "select_node_candidates",
    "summarize_schedule_result",
]
