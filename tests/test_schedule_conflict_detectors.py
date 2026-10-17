"""Detector boundaries, detached snapshots and independent evidence ownership."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import FrozenInstanceError
from itertools import permutations
from types import SimpleNamespace

import pytest

import modules.domain.schedule_conflict as conflict_module
from modules.domain.schedule_conflict import ScheduleConflictPolicy
from modules.domain.schedule_conflict_detectors import (
    CONFLICT_DETECTORS, CapacityConflictDetector, DowntimeConflictDetector,
    LockedTaskConflictDetector, SequenceConflictDetector, SerialConflictDetector,
)
from modules.domain.schedule_conflict_evidence import merge_conflict_evidence
from modules.domain.schedule_conflict_snapshot import build_conflict_snapshot
from tests.test_schedule_conflict_characterization import CASES, fact


def test_snapshot_is_recursively_immutable_and_detached_from_caller():
    inputs = {"candidate_intervals": [fact(1, metadata={"tags": ["before"], "ids": {7}})],
              "operations": [{"allocations": [{"serial_id": "S1", "production_node_id": 7}]}]}
    snapshot = build_conflict_snapshot(**inputs)
    with pytest.raises(FrozenInstanceError):
        snapshot.operations = ()
    with pytest.raises(TypeError):
        snapshot.candidate_intervals[0]["metadata"]["tags"][0] = "changed"
    with pytest.raises(TypeError):
        snapshot.operations[0]["allocations"][0]["serial_id"] = "changed"
    assert snapshot.candidate_intervals[0]["metadata"]["ids"] == frozenset({7})
    inputs["candidate_intervals"][0]["metadata"]["tags"].append("after")
    inputs["candidate_intervals"][0]["metadata"]["ids"].add(8)
    inputs["operations"][0]["allocations"][0]["serial_id"] = "changed"
    assert snapshot.candidate_intervals[0]["metadata"]["tags"] == ("before",)
    assert snapshot.operations[0]["allocations"][0]["serial_id"] == "S1"


@pytest.mark.parametrize("detector,types", [
    (CapacityConflictDetector, {"invalid_capacity_interval", "exclusive_node_overlap",
                                "non_capacity_operation_allocation"}),
    (LockedTaskConflictDetector, {"locked_task_conflict"}),
    (DowntimeConflictDetector, {"downtime_overlap"}),
    (SerialConflictDetector, {"serial_duplicate"}),
    (SequenceConflictDetector, {"sequence_violation"}),
])
def test_each_detector_preserves_its_complete_evidence(detector, types):
    inputs = CASES["all_seven_conflict_types"]
    snapshot = build_conflict_snapshot(**inputs)
    expected = [row for row in ScheduleConflictPolicy.detect(**inputs)
                if row["conflict_type"] in types]
    actual = merge_conflict_evidence([detector.detect(snapshot)])
    assert {row["conflict_type"] for row in actual} == types
    assert actual == expected


def test_coordinator_passes_the_same_snapshot_to_every_detector(monkeypatch):
    snapshots = []

    def spy(detector):
        def detect(snapshot):
            snapshots.append(snapshot)
            return detector.detect(snapshot)
        return SimpleNamespace(detect=detect)

    expected = ScheduleConflictPolicy.detect(**CASES["all_seven_conflict_types"])
    monkeypatch.setattr(conflict_module, "CONFLICT_DETECTORS", tuple(map(spy, CONFLICT_DETECTORS)))
    assert ScheduleConflictPolicy.detect(**CASES["all_seven_conflict_types"]) == expected
    assert len(snapshots) == 5
    assert all(snapshot is snapshots[0] for snapshot in snapshots)


def test_aggregation_is_deduplicated_and_stable_for_every_detector_order():
    inputs = CASES["all_seven_conflict_types"]
    snapshot = build_conflict_snapshot(**inputs)
    expected = ScheduleConflictPolicy.detect(**inputs)
    groups = tuple(detector.detect(snapshot) for detector in CONFLICT_DETECTORS)
    for order in permutations(groups):
        assert merge_conflict_evidence((*order, *order)) == expected
    assert len({row["evidence_digest"] for row in expected}) == len(expected)


def test_detectors_are_reentrant_over_a_shared_snapshot_and_own_their_outputs():
    inputs = CASES["all_seven_conflict_types"]
    original = deepcopy(inputs)
    snapshot = build_conflict_snapshot(**inputs)

    def detect(_):
        return merge_conflict_evidence(detector.detect(snapshot) for detector in CONFLICT_DETECTORS)

    expected = detect(None)
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(detect, range(32)))
    assert all(result == expected for result in results)
    results[0][0]["first"]["order_process_id"] = -1
    serial = next(row for row in results[0] if row["conflict_type"] == "serial_duplicate")
    serial["details"]["production_node_ids"].clear()
    assert results[1] == expected == detect(None)
    assert inputs == original


def test_equal_fact_pairing_is_captured_before_freezing_collection_types():
    snapshot = build_conflict_snapshot(**CASES["container_type_affects_legacy_pair_equality"])
    assert snapshot.candidate_intervals[0] == snapshot.candidate_intervals[1]
    assert snapshot.equal_candidate_positions == (0, 1, 1)


def test_one_shot_input_iterables_remain_supported():
    inputs = CASES["all_seven_conflict_types"]
    expected = ScheduleConflictPolicy.detect(**inputs)
    assert ScheduleConflictPolicy.detect(**{key: iter(value) for key, value in inputs.items()}) == expected
