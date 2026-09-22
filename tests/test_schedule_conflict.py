from modules.domain.schedule_conflict import ScheduleConflictPolicy


def _fact(order_process_id, node_id=7, start="2026-09-22 08:00", end="2026-09-22 09:00", **extra):
    return {
        "order_id": extra.pop("order_id", order_process_id),
        "order_process_id": order_process_id,
        "process_id": extra.pop("process_id", order_process_id),
        "process_name": extra.pop("process_name", "焊接"),
        "production_node_id": node_id,
        "node_name": extra.pop("node_name", f"焊接节点{node_id}"),
        "start_at": start,
        "end_at": end,
        **extra,
    }


def test_node_conflict_is_deterministic_and_reports_overlap_minutes():
    first = _fact(1)
    second = _fact(2, start="2026-09-22 08:30", end="2026-09-22 09:20")
    result = ScheduleConflictPolicy.detect(candidate_intervals=[first, second])

    assert len(result) == 1
    assert result[0]["conflict_type"] == "exclusive_node_overlap"
    assert result[0]["overlap_minutes"] == 30
    assert result[0]["first"]["production_node_id"] == 7
    assert result == ScheduleConflictPolicy.detect(candidate_intervals=[first, second])


def test_downtime_and_non_capacity_allocation_are_blocking():
    operation = _fact(
        1,
        start="2026-09-22 10:00",
        end="2026-09-22 11:00",
        execution_mode="internal",
    )
    outsourced = {
        **operation,
        "order_process_id": 2,
        "execution_mode": "outsourced",
        "order_id": 2,
    }
    result = ScheduleConflictPolicy.detect(
        candidate_intervals=[operation],
        unavailable_intervals=[
            {
                "production_node_id": 7,
                "start_at": "2026-09-22 10:30",
                "end_at": "2026-09-22 10:45",
                "reason": "设备检修",
            }
        ],
        operations=[outsourced],
    )
    assert {item["conflict_type"] for item in result} == {
        "downtime_overlap",
        "non_capacity_operation_allocation",
    }


def test_serial_duplicate_and_sequence_violation_are_explained():
    first = _fact(1, start="2026-09-22 08:00", end="2026-09-22 09:00")
    second = _fact(
        2,
        start="2026-09-22 08:30",
        end="2026-09-22 09:30",
        seq_order=2,
        allocations=[
            {"serial_id": "260922-001", "production_node_id": 7},
            {"serial_id": "260922-001", "production_node_id": 8},
        ],
    )
    first["seq_order"] = 1
    first["planned_start_at"] = first["start_at"]
    first["planned_end_at"] = first["end_at"]
    second["planned_start_at"] = second["start_at"]
    second["planned_end_at"] = second["end_at"]
    result = ScheduleConflictPolicy.detect(
        candidate_intervals=[first, second],
        operations=[first, second],
    )
    types = {item["conflict_type"] for item in result}
    assert "serial_duplicate" in types
    assert "sequence_violation" in types
