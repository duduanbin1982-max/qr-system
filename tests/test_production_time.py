from datetime import datetime
import sqlite3

import pytest

from modules.domain.production_time import (
    api_time_payload,
    format_api_timestamp,
    format_database_timestamp,
    parse_api_timestamp,
    parse_database_timestamp,
    parse_production_date,
    same_instant,
)
from modules.domain.schedule_conflict import ScheduleConflictPolicy
from modules.domain.schedule_deadline_risk import ScheduleDeadlineRiskPolicy
from modules.services.schedule_capacity_service import ScheduleCapacityService
from modules.services.schedule_replan_service import ScheduleReplanService


def test_shanghai_midnight_and_utc_inputs_normalize_to_one_production_instant():
    shanghai = parse_api_timestamp("2026-10-10T00:30:00+08:00")
    utc = parse_api_timestamp("2026-10-09T16:30:00Z")

    assert shanghai == utc
    assert shanghai.strftime("%Y-%m-%d %H:%M") == "2026-10-10 00:30"
    assert format_database_timestamp(utc) == "2026-10-10 00:30"
    assert format_api_timestamp("2026-10-10 00:30") == "2026-10-10T00:30+08:00"
    assert same_instant("2026-10-10T00:30:00+08:00", "2026-10-09T16:30:00Z")


def test_api_timestamp_requires_explicit_offset_but_legacy_database_value_remains_compatible():
    with pytest.raises(ValueError, match="offset"):
        parse_api_timestamp("2026-10-10 08:00")

    stored = parse_database_timestamp("2026-10-10 08:00")
    assert stored.utcoffset().total_seconds() == 8 * 3600
    assert format_database_timestamp(stored) == "2026-10-10 08:00"


def test_api_payload_adds_offsets_without_changing_date_only_fields():
    payload = api_time_payload({
        "planned_start_at": "2026-10-10 08:00:00",
        "plan_start": "2026-10-10",
        "segments": [{"end_at": "2026-10-10 09:30"}],
    })
    assert payload == {
        "planned_start_at": "2026-10-10T08:00+08:00",
        "plan_start": "2026-10-10",
        "segments": [{"end_at": "2026-10-10T09:30+08:00"}],
    }


def test_same_instant_iso_forms_produce_identical_replan_and_capacity_inputs():
    first = ScheduleReplanService._replan_start("2026-10-10T00:30:00+08:00")
    second = ScheduleReplanService._replan_start("2026-10-09T16:30:00Z")
    assert first == second
    assert ScheduleCapacityService._format_timestamp(first) == "2026-10-10 00:30"
    assert ScheduleCapacityService._format_timestamp(second) == "2026-10-10 00:30"


def test_cross_day_weekend_slots_stay_on_shanghai_calendar():
    calendar = {"id": 1, "weekly_workdays": "1,2,3,4,5"}
    shifts = [{
        "id": 1,
        "shift_code": "DAY",
        "shift_name": "白班",
        "start_minute": 8 * 60,
        "end_minute": 17 * 60,
    }]
    start = parse_production_date("2026-10-10")  # Saturday
    with sqlite3.connect(":memory:") as db:
        slots = list(ScheduleCapacityService._calendar_slots(
            db, calendar, shifts, start, max_days=4,
        ))
    assert slots
    assert slots[0]["start"].strftime("%Y-%m-%d %H:%M %z") == "2026-10-12 08:00 +0800"


def test_cross_day_allocation_skips_weekend_and_preserves_540_minute_capacity():
    calendar = {"id": 1, "weekly_workdays": "1,2,3,4,5"}
    shifts = [{
        "id": 1,
        "shift_code": "DAY",
        "shift_name": "白班",
        "start_minute": 8 * 60,
        "end_minute": 18 * 60,
    }]
    start = parse_api_timestamp("2026-10-09T08:00:00+08:00")  # Friday
    with sqlite3.connect(":memory:") as db:
        slots = ScheduleCapacityService._calendar_slots(
            db, calendar, shifts, start, daily_minutes=540, max_days=7,
        )
        segments = ScheduleCapacityService._allocate_from_slots(
            slots, start, 600, [],
        )
    assert segments == [
        {
            "start_at": "2026-10-09 08:00",
            "end_at": "2026-10-09 17:00",
            "occupied_minutes": 540.0,
            "shift_id": 1,
        },
        {
            "start_at": "2026-10-12 08:00",
            "end_at": "2026-10-12 09:00",
            "occupied_minutes": 60.0,
            "shift_id": 1,
        },
    ]


def test_equivalent_iso_instants_produce_identical_capacity_allocation():
    slots = [{
        "start": parse_api_timestamp("2026-10-10T08:00:00+08:00"),
        "end": parse_api_timestamp("2026-10-10T10:00:00+08:00"),
        "shift_id": 1,
    }]
    shanghai = ScheduleCapacityService._allocate_from_slots(
        slots, parse_api_timestamp("2026-10-10T08:30:00+08:00"), 30, [],
    )
    utc = ScheduleCapacityService._allocate_from_slots(
        slots, parse_api_timestamp("2026-10-10T00:30:00Z"), 30, [],
    )
    assert shanghai == utc == [{
        "start_at": "2026-10-10 08:30",
        "end_at": "2026-10-10 09:00",
        "occupied_minutes": 30.0,
        "shift_id": 1,
    }]


def test_downtime_overlap_is_identical_for_utc_and_shanghai_iso_inputs():
    candidate = [{
        "order_id": 1,
        "order_process_id": 11,
        "process_id": 7,
        "production_node_id": 41,
        "node_name": "焊接-01",
        "start_at": "2026-10-10T08:00:00+08:00",
        "end_at": "2026-10-10T09:00:00+08:00",
    }]
    shanghai = [{
        "production_node_id": 41,
        "start_at": "2026-10-10T08:30:00+08:00",
        "end_at": "2026-10-10T08:45:00+08:00",
    }]
    utc = [{
        "production_node_id": 41,
        "start_at": "2026-10-10T00:30:00Z",
        "end_at": "2026-10-10T00:45:00Z",
    }]

    first = ScheduleConflictPolicy.detect(
        candidate_intervals=candidate, unavailable_intervals=shanghai,
    )
    second = ScheduleConflictPolicy.detect(
        candidate_intervals=candidate, unavailable_intervals=utc,
    )
    assert first == second
    assert first[0]["overlap_minutes"] == 15


def test_deadline_risk_is_identical_for_equivalent_projected_instants():
    now = datetime.fromisoformat("2026-10-10T10:00:00+08:00")
    shanghai = ScheduleDeadlineRiskPolicy.evaluate(
        deadline_text="2026-10-10",
        projected_completion_at="2026-10-11T02:30:00+08:00",
        now=now,
    )
    utc = ScheduleDeadlineRiskPolicy.evaluate(
        deadline_text="2026-10-10",
        projected_completion_at="2026-10-10T18:30:00Z",
        now=now,
    )
    assert shanghai == utc
    assert shanghai["delay_minutes"] == 150
