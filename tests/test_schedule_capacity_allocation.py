from datetime import datetime

import pytest

from modules.domain.schedule_capacity_allocation import (
    ScheduleCapacityAllocationPolicy,
)


def _format(value):
    return value.strftime("%Y-%m-%d %H:%M")


@pytest.mark.unit
def test_merge_intervals_combines_overlapping_and_adjacent_occupancy():
    intervals = [
        (datetime(2030, 1, 7, 9), datetime(2030, 1, 7, 10)),
        (datetime(2030, 1, 7, 8), datetime(2030, 1, 7, 9)),
        (datetime(2030, 1, 7, 11), datetime(2030, 1, 7, 12)),
        (datetime(2030, 1, 7, 8, 30), datetime(2030, 1, 7, 9, 30)),
    ]

    assert ScheduleCapacityAllocationPolicy.merge_intervals(intervals) == [
        (datetime(2030, 1, 7, 8), datetime(2030, 1, 7, 10)),
        (datetime(2030, 1, 7, 11), datetime(2030, 1, 7, 12)),
    ]


@pytest.mark.unit
def test_allocate_from_slots_skips_occupancy_and_spans_shift_gap_without_mutation():
    slots = [
        {
            "start": datetime(2030, 1, 7, 8),
            "end": datetime(2030, 1, 7, 10),
            "shift_id": 1,
        },
        {
            "start": datetime(2030, 1, 7, 10, 30),
            "end": datetime(2030, 1, 7, 12),
            "shift_id": 2,
        },
    ]
    occupancy = [
        (datetime(2030, 1, 7, 8, 30), datetime(2030, 1, 7, 9)),
    ]
    original_slots = [dict(slot) for slot in slots]
    original_occupancy = list(occupancy)

    segments = ScheduleCapacityAllocationPolicy.allocate_from_slots(
        slots,
        datetime(2030, 1, 7, 8),
        150,
        occupancy,
        _format,
    )

    assert segments == [
        {
            "start_at": "2030-01-07 08:00",
            "end_at": "2030-01-07 08:30",
            "occupied_minutes": 30,
            "shift_id": 1,
        },
        {
            "start_at": "2030-01-07 09:00",
            "end_at": "2030-01-07 10:00",
            "occupied_minutes": 60,
            "shift_id": 1,
        },
        {
            "start_at": "2030-01-07 10:30",
            "end_at": "2030-01-07 11:30",
            "occupied_minutes": 60,
            "shift_id": 2,
        },
    ]
    assert sum(item["occupied_minutes"] for item in segments) == 150
    assert slots == original_slots
    assert occupancy == original_occupancy


@pytest.mark.unit
def test_allocate_from_slots_rejects_insufficient_capacity():
    slots = [
        {
            "start": datetime(2030, 1, 7, 8),
            "end": datetime(2030, 1, 7, 9),
            "shift_id": 1,
        }
    ]

    with pytest.raises(ValueError, match="工作日历在可搜索范围内没有足够产能"):
        ScheduleCapacityAllocationPolicy.allocate_from_slots(
            slots,
            datetime(2030, 1, 7, 8),
            61,
            [],
            _format,
        )


@pytest.mark.unit
def test_duration_minutes_includes_setup_unit_time_and_difficulty():
    assert ScheduleCapacityAllocationPolicy.duration_minutes(
        2,
        {
            "setup_minutes": 10,
            "standard_minutes_per_unit": 60,
            "difficulty_factor": 1.5,
        },
    ) == 190


@pytest.mark.unit
def test_earliest_completion_uses_resource_id_as_stable_tie_breaker():
    later = datetime(2030, 1, 7, 10)
    earlier = datetime(2030, 1, 7, 9)
    candidates = [
        (earlier, 8, "node-8"),
        (earlier, 3, "node-3"),
        (later, 1, "node-1"),
    ]

    assert ScheduleCapacityAllocationPolicy.choose_earliest_completion(
        candidates
    ) == (earlier, 3, "node-3")


def _candidate_allocator(node, earliest, duration, additions):
    slots = [
        {
            "start": datetime(2030, 1, 7, 8),
            "end": datetime(2030, 1, 7, 18),
            "shift_id": 1,
        }
    ]
    return ScheduleCapacityAllocationPolicy.allocate_from_slots(
        slots,
        earliest,
        duration,
        additions,
        _format,
    )


@pytest.mark.unit
def test_split_allocator_distributes_quantity_and_returns_occupancy_facts():
    result = ScheduleCapacityAllocationPolicy.allocate_split_on_nodes(
        nodes=[
            {"id": 1, "capacity_mode": "exclusive", "capabilities": []},
            {"id": 2, "capacity_mode": "exclusive", "capabilities": []},
        ],
        earliest=datetime(2030, 1, 7, 8),
        quantity=8,
        standard={
            "setup_minutes": 5,
            "standard_minutes_per_unit": 10,
            "difficulty_factor": 1,
        },
        allocation_key_prefix="order:process",
        candidate_allocator=_candidate_allocator,
    )

    assert [item["quantity"] for item in result["allocations"]] == [4, 2, 1, 1]
    assert sum(item["quantity"] for item in result["allocations"]) == 8
    assert sum(item["quantity"] for item in result["segments"]) == 8
    assert sorted(result["occupancy_additions"]) == [1, 2]
    assert len(result["occupancy_additions"][1]) == 1
    assert len(result["occupancy_additions"][2]) == 3
    assert result["allocations"][0]["batch_key"] == "order:process:node-1:batch-1"


@pytest.mark.unit
def test_split_allocator_keeps_serial_items_on_one_node():
    result = ScheduleCapacityAllocationPolicy.allocate_split_on_nodes(
        nodes=[
            {"id": 1, "capacity_mode": "exclusive", "capabilities": []},
            {"id": 2, "capacity_mode": "exclusive", "capabilities": []},
        ],
        earliest=datetime(2030, 1, 7, 8),
        quantity=3,
        standard={
            "setup_minutes": 0,
            "standard_minutes_per_unit": 10,
            "difficulty_factor": 1,
        },
        serial_ids=["S1", "S2", "S3"],
        allocation_key_prefix="serial:process",
        candidate_allocator=_candidate_allocator,
    )

    assert {item["production_node_id"] for item in result["allocations"]} == {1}
    assert [item["serial_id"] for item in result["allocations"]] == ["S1", "S2", "S3"]
    assert sum(item["quantity"] for item in result["allocations"]) == 3
    assert sum(item["quantity"] for item in result["segments"]) == 3


@pytest.mark.unit
def test_split_allocator_applies_batch_limit_and_changeover_once():
    result = ScheduleCapacityAllocationPolicy.allocate_split_on_nodes(
        nodes=[
            {
                "id": 1,
                "capacity_mode": "batch",
                "capabilities": [
                    {
                        "status": "active",
                        "max_batch_quantity": 3,
                        "batch_minutes": 60,
                        "changeover_minutes": 15,
                    }
                ],
            }
        ],
        earliest=datetime(2030, 1, 7, 8),
        quantity=5,
        standard={
            "setup_minutes": 0,
            "standard_minutes_per_unit": 10,
            "difficulty_factor": 1,
        },
        allocation_key_prefix="batch:process",
        candidate_allocator=_candidate_allocator,
    )

    assert [item["quantity"] for item in result["allocations"]] == [3, 2]
    assert result["allocations"][0]["changeover_minutes"] == 15
    assert result["allocations"][1]["changeover_minutes"] == 0
