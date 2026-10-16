"""Behavior contracts at the frozen strategy boundaries."""

from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from modules.domain.production_time import parse_database_timestamp
from modules.domain.schedule_allocation_results import AllocationResultAccumulator
from modules.domain.schedule_planning import (
    CapacityAllocationFacts, CapacityCandidate, CapacityDemand, CapacityNodeFacts,
)


def _candidate():
    return CapacityCandidate(
        completion=parse_database_timestamp("2030-01-04 09:00"), node_id=7,
        segments=({"start_at": "2030-01-04 08:00", "end_at": "2030-01-04 09:00",
                   "metadata": {"labels": ["before"], "captured_at": datetime(2030, 1, 4)}},),
        quantity=2, capability={"rules": ["original"]}, capacity_mode="exclusive",
    )


def test_allocation_stage_inputs_and_candidates_are_recursively_frozen():
    source = {"setup_minutes": 1, "nested": {"values": [1]}}
    facts = CapacityAllocationFacts(datetime(2030, 1, 4), source, {"ids": [1]}, {})
    progress = CapacityNodeFacts({"id": 7, "capabilities": [{"ids": [1]}]}, 0, ())
    candidate = _candidate()
    source["nested"]["values"].append(2)
    assert facts.standard["nested"]["values"] == (1,)
    for mapping, key in [
        (facts.standard["nested"], "values"), (progress.node["capabilities"][0], "ids"),
        (candidate.segments[0]["metadata"], "labels"), (candidate.capability, "rules"),
    ]:
        with pytest.raises(TypeError):
            mapping[key] = ()
    with pytest.raises(FrozenInstanceError):
        candidate.quantity = 99
    with pytest.raises(FrozenInstanceError):
        CapacityDemand(2, 10).quantity = 99


def test_result_snapshot_and_legacy_output_are_independent_native_values():
    progress = AllocationResultAccumulator([{"id": 7}], "order:op")
    progress.record_quantity(_candidate())
    snapshot = progress.result(2)
    with pytest.raises(TypeError):
        snapshot.allocations[0]["quantity"] = 9
    with pytest.raises(TypeError):
        snapshot.occupancy_additions[7] = ()
    with pytest.raises(TypeError):
        snapshot.segments[0]["metadata"]["labels"] = ()
    payload = snapshot.as_legacy_result()
    start, end = payload["occupancy_additions"][7][0]
    assert isinstance(start, datetime) and isinstance(end, datetime)
    assert isinstance(payload["occupancy_additions"][7][0], tuple)
    assert payload["segments"][0]["metadata"]["captured_at"] == datetime(2030, 1, 4)
    payload["segments"][0]["metadata"]["labels"].append("changed")
    payload["allocations"][0]["quantity"] = 9
    payload["occupancy_additions"][7].clear()
    assert snapshot.as_legacy_result()["segments"][0]["metadata"]["labels"] == ["before"]
    assert snapshot.allocations[0]["quantity"] == 2
    assert len(snapshot.occupancy_additions[7]) == 1
    # Later progress cannot change a previously produced result or node snapshot.
    node_snapshot = progress.snapshot()
    progress.record_quantity(_candidate())
    assert len(snapshot.allocations) == len(node_snapshot[0].occupancy) == 1
