"""Frozen allocation traces captured before Task 3 changes any domain code.

The golden hashes cover full segments, allocation order, callback inputs,
occupancy datetimes, and exception payloads (including partial occupancy).
"""

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path

import pytest

from modules.domain.production_node_scheduling import NodeSchedulingError
from modules.domain.schedule_capacity_allocation import ScheduleCapacityAllocationPolicy as Policy


BASELINE_SHA = "d81ba2b30af21bc2af3ed05b92b3d214cf8e39c6"
GOLDEN = Path(__file__).with_name("capacity_allocation_behavior_v1.json")
START = datetime(2030, 1, 4, 8)
STANDARD = {"setup_minutes": 3, "standard_minutes_per_unit": 7, "difficulty_factor": 1}


def _batch(node_id=1, **config):
    return {"id": node_id, "capacity_mode": "batch", "capabilities": [{
        "max_batch_quantity": 3, "batch_minutes": 60, "changeover_minutes": 15,
        **config,
    }]}


CASES = {
    "tie_reversed_nodes": {"quantity": 1},
    "earlier_completion_before_node_id": {"quantity": 1, "delays": {1: 1}},
    "ceil_splitting_and_flatten_order": {"quantity": 11},
    "setup_only_once": {"quantity": 9},
    "fractional_minutes": {"quantity": 9, "standard": {
        "setup_minutes": 0.125, "standard_minutes_per_unit": 0.3333333, "difficulty_factor": 1.25}},
    "minimum_duration_and_factor": {"quantity": 4, "standard": {
        "setup_minutes": -1, "standard_minutes_per_unit": 0.01, "difficulty_factor": -2}},
    "duplicate_node_last_value_first_position": {"quantity": 7, "nodes": [
        {"id": 2, "tag": "old"}, {"id": 1}, {"id": 2, "tag": "new"}]},
    "serial_whole_group": {"quantity": 3, "serial_ids": [" S1 ", "", "S2", "S3"]},
    "serial_duplicate": {"quantity": 2, "serial_ids": ["S1", " S1 "]},
    "serial_count_mismatch": {"quantity": 3, "serial_ids": ["S1"]},
    "blank_serials_use_quantity_split": {"quantity": 3, "serial_ids": ["", " "]},
    "serial_batch_fallback_to_exclusive": {"quantity": 4, "serial_ids": ["1", "2", "3", "4"],
        "nodes": [_batch(), {"id": 2}]},
    "serial_batch_too_small": {"quantity": 4, "serial_ids": ["1", "2", "3", "4"], "nodes": [_batch()]},
    "serial_batch_changeover": {"quantity": 3, "serial_ids": [1, 2, 3], "nodes": [_batch()]},
    "serial_exclusive_changeover_metadata": {"quantity": 2, "serial_ids": [1, 2], "nodes": [
        {"id": 1, "capabilities": [{"changeover_minutes": "12.5"}]}]},
    "batch_limit_changeover_once": {"quantity": 8, "nodes": [_batch()]},
    "mixed_batch_and_exclusive": {"quantity": 13, "nodes": [_batch(2), {"id": 1}]},
    "capability_lowest_id": {"quantity": 4, "nodes": [_batch(capabilities_ignored=True)],
        "capabilities": [{"id": 8, "max_batch_quantity": 1, "batch_minutes": 99},
                         {"id": 2, "max_batch_quantity": 3, "batch_minutes": 12, "changeover_minutes": 2}]},
    "batch_bad_size": {"quantity": 2, "nodes": [_batch(max_batch_quantity=0)]},
    "batch_bad_changeover": {"quantity": 2, "nodes": [_batch(changeover_minutes=-1)]},
    "serial_invalid_batch_config_propagates": {"quantity": 2, "serial_ids": [1, 2],
        "nodes": [_batch(batch_minutes=0), {"id": 2}]},
    "zero_before_node_validation": {"quantity": 0, "nodes": [], "serial_ids": [1]},
    "negative_quantity": {"quantity": -3, "nodes": []},
    "no_nodes": {"quantity": 1, "nodes": []},
    "unavailable_calendar": {"quantity": 2, "fail_after": 0},
    "serial_unavailable_calendar": {"quantity": 2, "serial_ids": [1, 2], "fail_after": 0},
    "candidate_domain_error_skipped": {"quantity": 3, "fail_nodes": [1], "failure": "domain"},
    "partial_calendar_failure_has_occupancy": {"quantity": 8, "nodes": [_batch()], "fail_after": 1},
    "partial_unexpected_failure_has_occupancy": {"quantity": 8, "nodes": [_batch()],
        "fail_after": 1, "failure": "runtime"},
    "empty_callback_preserves_index_error": {"quantity": 1, "callback": "empty"},
    "malformed_callback_timestamp_legacy_passthrough": {"quantity": 1, "callback": "bad_timestamp"},
    "fractional_quantity_conservation_failure": {"quantity": 2.5},
    "serial_normalized_quantity_compatibility": {"quantity": 2.5, "serial_ids": [1, 2]},
    "shift_day_weekend_and_downtime": {"quantity": 9, "nodes": [{"id": 1}],
        "standard": {"setup_minutes": 15, "standard_minutes_per_unit": 30, "difficulty_factor": 1},
        "calendar": "weekend"},
    "nested_segment_metadata": {"quantity": 3, "metadata": True},
}


def _canonical(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    return value


def capture_case(config):
    config = deepcopy(config)
    nodes = config.pop("nodes", [{"id": 2}, {"id": 1}])
    if "capabilities" in config:
        nodes[0]["capabilities"] = config.pop("capabilities")
    args = {"nodes": nodes, "earliest": START, "standard": config.pop("standard", STANDARD),
            "quantity": config.pop("quantity"), "serial_ids": config.pop("serial_ids", None),
            "operation": {"process_name": "cut"}, "order": {"product_code": "P1"},
            "allocation_key_prefix": "order:operation"}
    original = deepcopy(args)
    trace = []

    def allocate(node, earliest, duration, additions):
        trace.append({"node": deepcopy(node), "earliest": earliest,
                      "duration": duration, "prior": deepcopy(additions)})
        if (len(trace) > config.get("fail_after", float("inf"))
                or node["id"] in config.get("fail_nodes", [])):
            failure = config.get("failure")
            if failure == "runtime":
                raise RuntimeError("unexpected candidate failure")
            if failure == "domain":
                raise NodeSchedulingError("FIXTURE_BLOCKED", "candidate blocked", {"node": node["id"]})
            raise ValueError("calendar exhausted")
        if config.get("callback") == "empty":
            return []
        if config.get("callback") == "bad_timestamp":
            return [{"start_at": "2030-01-04 08:00", "end_at": "invalid"}]
        slots = [{"start": START, "end": datetime(2030, 1, 4, 18), "shift_id": 1}]
        occupied = []
        if config.get("calendar") == "weekend":
            slots = [
                {"start": START, "end": datetime(2030, 1, 4, 9), "shift_id": 1},
                {"start": datetime(2030, 1, 4, 9, 30), "end": datetime(2030, 1, 4, 10), "shift_id": 2},
                {"start": datetime(2030, 1, 7, 8), "end": datetime(2030, 1, 7, 18), "shift_id": 1},
            ]
            occupied = [(datetime(2030, 1, 4, 8, 15), datetime(2030, 1, 4, 8, 45))]
        delay = config.get("delays", {}).get(node["id"], 0)
        if delay:
            occupied.append((START, START.replace(hour=8 + delay)))
        segments = Policy.allocate_from_slots(slots, earliest, duration, occupied + list(additions),
                                             lambda value: value.isoformat(sep=" "))
        if config.get("metadata"):
            for segment in segments:
                segment["metadata"] = {"tags": ["original"], "at": START}
        return segments

    try:
        result = Policy.allocate_split_on_nodes(**args, candidate_allocator=allocate)
    except Exception as exc:
        payload = {"error": type(exc).__name__, "message": str(exc),
                   "code": getattr(exc, "code", None), "details": getattr(exc, "details", None),
                   "partial_occupancy": getattr(exc, "capacity_occupancy_additions", None)}
    else:
        payload = {"result": result}
        if int(args["quantity"]) > 0:
            assert sum(item["quantity"] for item in result["allocations"]) == int(args["quantity"])
            assert sum(item["quantity"] for item in result["segments"]) == int(args["quantity"])
            for intervals in result["occupancy_additions"].values() if config.get("callback") != "bad_timestamp" else ():
                ordered = sorted(intervals)
                assert all(start < end for start, end in ordered)
                assert all(left[1] <= right[0] for left, right in zip(ordered, ordered[1:]))
    assert args == original, "allocation must not mutate caller facts"
    return _canonical({**payload, "trace": trace})


def case_summary(config):
    payload = capture_case(config)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    result = payload.get("result", {})
    return {"sha256": hashlib.sha256(encoded.encode()).hexdigest(),
            "outcome": payload.get("code") or payload.get("error") or "ok",
            "selected": [[item["production_node_id"], item["quantity"]]
                         for item in result.get("allocations", [])],
            "calls": len(payload["trace"])}


@pytest.mark.parametrize("name", CASES)
def test_allocation_matches_pre_refactor_trace(name):
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert golden["baseline_sha"] == BASELINE_SHA
    assert case_summary(CASES[name]) == golden["cases"][name]


def test_golden_covers_every_protection_case():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert set(golden["cases"]) == set(CASES)
