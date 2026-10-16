"""Conflict evidence and deadline risks frozen before Task 4 extraction.

The golden digest includes every evidence field, its digest, list ordering,
summary and deadline-risk output, or the original exception type and message.
"""

from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path

import pytest

from modules.domain.schedule_conflict import ScheduleConflictPolicy
from modules.domain.schedule_planning import PlanningAssessmentFacts
from modules.domain.schedule_planning_assessment import SchedulePlanningAssessment


BASELINE_SHA = "839b47ed16f06f33e382aaa5df68d27fb6fb5269"
GOLDEN = Path(__file__).with_name("schedule_conflict_behavior_v1.json")


def fact(identifier, **values):
    return {
        "order_id": 12, "order_process_id": identifier, "process_id": identifier,
        "process_name": "焊接", "production_node_id": 7, "node_name": "节点7",
        "revision_item_id": identifier + 100, "schedule_id": identifier + 200,
        "start_at": "2026-10-16 08:00", "end_at": "2026-10-16 09:00",
        **values,
    }


def operation(identifier, **values):
    return fact(identifier, **{
        "seq_order": identifier, "planned_start_at": "2026-10-16 08:00",
        "planned_end_at": "2026-10-16 09:00", **values,
    })


def serials(*nodes):
    return [{"serial_id": " S1 " if index else "S1", "production_node_id": node}
            for index, node in enumerate(nodes)]


CASES = {
    "empty": {},
    "valid_touching": {"candidate_intervals": [fact(1), fact(2,
        start_at="2026-10-16 09:00", end_at="2026-10-16 10:00")],
        "operations": [operation(1), operation(2,
            planned_start_at="2026-10-16 09:00")]},
    "exclusive_candidates": {"candidate_intervals": [fact(3), fact(1), fact(2)]},
    "occupied_and_multiple_candidates": {"candidate_intervals": [fact(3), fact(1)],
        "occupied_intervals": [fact(9), fact(8, production_node_id=8)]},
    "locked_candidate": {"candidate_intervals": [fact(1, locked=True), fact(2)]},
    "locked_occupied": {"candidate_intervals": [fact(1)],
        "occupied_intervals": [fact(2, locked=1)]},
    "both_locked": {"candidate_intervals": [fact(1, locked=True), fact(2, locked=True)]},
    "batch_overlap_allowed_even_locked": {"candidate_intervals": [
        fact(1, capacity_mode="batch", locked=True), fact(2, capacity_mode="batch")]},
    "mixed_capacity_modes": {"candidate_intervals": [fact(1, capacity_mode="batch"),
        fact(2, capacity_mode="exclusive"), fact(3, capacity_mode="batch")]},
    "different_resources": {"candidate_intervals": [fact(1), fact(2, production_node_id=8)]},
    "legacy_line_and_fallback_name": {"candidate_intervals": [fact(1,
        production_node_id=None, process_line_id="9", node_name=""), fact(2,
        production_node_id="", process_line_id=9, node_name="")]},
    "node_takes_priority_over_line": {"candidate_intervals": [fact(1, process_line_id=7),
        fact(2, production_node_id=None, process_line_id=7)]},
    "invalid_candidate_intervals": {"candidate_intervals": [fact(1, start_at="bad"),
        fact(2, end_at=None), fact(3, end_at="2026-10-16 07:00"),
        fact(4, end_at="2026-10-16 08:00"), fact(5, production_node_id=None)]},
    "invalid_occupied_and_downtime_ignored": {"candidate_intervals": [fact(1)],
        "occupied_intervals": [fact(2, start_at="bad"), fact(3, production_node_id=None)],
        "unavailable_intervals": [fact(4, end_at="bad"), fact(5, production_node_id=None)]},
    "downtime_evidence_and_deduplication": {"candidate_intervals": [fact(1), fact(1)],
        "unavailable_intervals": [fact(9, id=17, reason="检修", unavailable_type="maintenance"),
            fact(9, id=17, reason="检修", unavailable_type="maintenance"),
            fact(8, id=18, node_name="", reason="")]},
    "subminute_overlap": {"candidate_intervals": [fact(1,
        start_at="2026-10-16 08:59:40"), fact(2, start_at="2026-10-16 08:59:50")]},
    "offset_and_cross_midnight": {"candidate_intervals": [fact(1,
        start_at="2026-10-15T16:00:00Z", end_at="2026-10-15T17:00:00Z"), fact(2,
        start_at="2026-10-16T00:30:00+08:00", end_at="2026-10-16T01:30:00+08:00")]},
    "equal_candidates_and_occupied": {"candidate_intervals": [fact(1), fact(1), fact(2)],
        "occupied_intervals": [fact(1), fact(2)]},
    "container_type_affects_legacy_pair_equality": {"candidate_intervals": [
        fact(1, metadata=[]), fact(1, metadata=())], "occupied_intervals": [fact(1, metadata=())]},
    "serial_duplicates_same_node_and_blank": {"operations": [operation(1,
        allocations=serials(7, 7) + [{"serial_id": " ", "production_node_id": 8}])]},
    "serial_duplicates_multiple_nodes": {"operations": [operation(1, allocations=serials(8, 7))]},
    "blocked_serial_still_checked": {"operations": [operation(1, status="blocked",
        allocations=serials(None, "")), operation(2)]},
    "outsourced_and_non_scheduled_skip_other_checks": {"operations": [
        operation(1, execution_mode="outsourced", allocations=serials(7, 8)),
        operation(2, execution_mode="non_scheduled", production_node_id=None, segments=[{}]),
        operation(3, execution_mode="outsourced", production_node_id=None)]},
    "sequence_sort_and_fallback_fields": {"operations": [
        operation(2, planned_start_at=None, plan_start="2026-10-16 08:30"),
        operation(1, planned_end_at=None, plan_end="2026-10-16 09:00"),
        operation(3, planned_start_at="bad")]},
    "sequence_equal_keys_keep_input_order": {"operations": [
        operation(1, process_id=2), operation(1, process_id=3)]},
    "sequence_is_not_regrouped_by_order": {"operations": [
        operation(1, order_id=12), operation(2, order_id=13)]},
    "all_seven_conflict_types": {"candidate_intervals": [fact(1), fact(2),
        fact(3, locked=True), fact(4, start_at="bad")],
        "unavailable_intervals": [fact(9, id=19)], "operations": [
            operation(1, allocations=serials(7, 8)), operation(2),
            operation(3, execution_mode="outsourced")]},
    "completed_risk_precedence": {"candidate_intervals": [fact(1), fact(2)],
        "order": {"quantity": 3, "completed": 3, "deadline": "2026-10-15"}},
    "blocked_risk_precedence": {"candidate_intervals": [fact(1), fact(2)],
        "operations": [operation(1, status="blocked", blocked_reason="缺工时")]},
    "late_risk": {"operations": [operation(1)],
        "order": {"quantity": 3, "deadline": "2026-10-15"}},
    "invalid_resource_error": {"candidate_intervals": [fact(1, production_node_id="bad")]},
    "invalid_occupied_resource_error": {"occupied_intervals": [fact(1, process_line_id="bad",
        production_node_id=None)]},
    "invalid_unavailable_resource_error": {"unavailable_intervals": [fact(1,
        production_node_id="bad")]},
    "invalid_sequence_error": {"operations": [operation(1, seq_order="bad")]},
    "mixed_serial_node_types_error": {"operations": [operation(1, allocations=serials(7, "8"))]},
}


def capture_case(config, policy=ScheduleConflictPolicy):
    inputs = deepcopy(config)
    original = deepcopy(inputs)
    arguments = {key: inputs.get(key, ()) for key in (
        "candidate_intervals", "occupied_intervals", "unavailable_intervals", "operations")}
    try:
        conflicts = policy.detect(**arguments)
        summary = policy.summarize(conflicts)
        facts = PlanningAssessmentFacts(
            order=inputs.get("order", {"quantity": 3, "deadline": "2026-10-17"}),
            now=datetime(2026, 10, 16, 7), **arguments)
        risk, planned_count = SchedulePlanningAssessment.deadline_risk(facts, conflicts, summary)
        result = {"conflicts": conflicts, "summary": summary,
                  "risk": risk, "planned_count": planned_count}
    except Exception as error:
        result = {"exception": type(error).__name__, "message": str(error)}
    assert inputs == original, "detection must not mutate caller facts"
    return result


def result_digest(result):
    payload = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("name", CASES)
def test_conflict_evidence_summary_risk_and_errors_match_frozen_baseline(name):
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert golden["baseline_sha"] == BASELINE_SHA
    assert set(golden["cases"]) == set(CASES)
    result = capture_case(CASES[name])
    assert result_digest(result) == golden["cases"][name], result


def test_valid_schedule_has_zero_conflicts_and_invalid_sample_covers_all_types():
    assert capture_case(CASES["valid_touching"])["conflicts"] == []
    result = capture_case(CASES["all_seven_conflict_types"])
    assert set(result["summary"]["by_type"]) == ScheduleConflictPolicy.BLOCKING_TYPES
    assert result["summary"]["blocking_count"] == len(result["conflicts"])
