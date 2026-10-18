"""Pure minute-capacity allocation primitives for production scheduling.

This module only transforms caller-supplied standards, ordered calendar slots,
occupancy intervals, and candidate completion facts. Calendar and override
facts are resolved by the service/repository adapter.
"""

from datetime import timedelta

from modules.domain.production_time import parse_database_timestamp
from modules.domain.schedule_allocation_candidates import CandidateNodeDecision
from modules.domain.schedule_allocation_quantity import QuantitySplitStrategy
from modules.domain.schedule_allocation_results import AllocationResultAccumulator
from modules.domain.schedule_allocation_serial import SerialExclusiveStrategy
from modules.domain.schedule_planning import CapacityAllocationFacts


class ScheduleCapacityAllocationPolicy:
    """Deterministic allocation over immutable, pre-resolved capacity facts."""

    EPSILON = 1e-7

    @staticmethod
    def merge_intervals(intervals):
        """Merge overlapping or touching occupancy intervals."""
        normalized = sorted(
            (start, end) for start, end in intervals
            if start and end and end > start
        )
        merged = []
        for start, end in normalized:
            if not merged or start > merged[-1][1]:
                merged.append([start, end])
            elif end > merged[-1][1]:
                merged[-1][1] = end
        return [(start, end) for start, end in merged]

    @staticmethod
    def duration_minutes(quantity, standard):
        """Calculate occupied minutes from quantity and a standard snapshot."""
        if not standard:
            return 0.0
        quantity = max(int(quantity or 0), 0)
        setup = float(standard["setup_minutes"] or 0)
        unit = float(standard["standard_minutes_per_unit"] or 0)
        factor = max(float(standard["difficulty_factor"] or 1), 0.01)
        return max(setup + quantity * unit * factor, 1.0)

    @classmethod
    def allocate_from_slots(cls, slots, earliest, duration, occupied, format_timestamp):
        """Place duration into ordered slots, skipping occupied intervals.

        A slot is a mapping with datetime values in start/end and an optional
        shift_id. Occupancy is a sequence of datetime pairs. The function
        returns new segment mappings and does not mutate any input.
        """
        earliest = parse_database_timestamp(earliest)
        slots = [
            {
                **slot,
                "start": parse_database_timestamp(slot.get("start")),
                "end": parse_database_timestamp(slot.get("end")),
            }
            for slot in slots
        ]
        occupied = [
            (parse_database_timestamp(start), parse_database_timestamp(end))
            for start, end in occupied
        ]
        remaining = float(duration)
        segments = []
        intervals = cls.merge_intervals(occupied)
        for slot in slots:
            if remaining <= cls.EPSILON:
                break
            if slot["end"] <= earliest:
                continue
            cursor = max(slot["start"], earliest)
            for busy_start, busy_end in intervals:
                if busy_end <= cursor:
                    continue
                if busy_start >= slot["end"]:
                    break
                free_end = min(busy_start, slot["end"])
                if free_end > cursor:
                    available = (free_end - cursor).total_seconds() / 60
                    take = min(remaining, available)
                    end = cursor + timedelta(minutes=take)
                    segments.append({
                        "start_at": format_timestamp(cursor),
                        "end_at": format_timestamp(end),
                        "occupied_minutes": take,
                        "shift_id": slot.get("shift_id"),
                    })
                    remaining -= take
                    cursor = end
                    if remaining <= cls.EPSILON:
                        break
                cursor = max(cursor, busy_end)
                if cursor >= slot["end"]:
                    break
            if remaining <= cls.EPSILON:
                break
            if cursor < slot["end"]:
                available = (slot["end"] - cursor).total_seconds() / 60
                take = min(remaining, available)
                end = cursor + timedelta(minutes=take)
                segments.append({
                    "start_at": format_timestamp(cursor),
                    "end_at": format_timestamp(end),
                    "occupied_minutes": take,
                    "shift_id": slot.get("shift_id"),
                })
                remaining -= take
        if remaining > cls.EPSILON:
            raise ValueError("工作日历在可搜索范围内没有足够产能")
        return segments

    @staticmethod
    def choose_earliest_completion(candidates):
        """Choose a candidate by completion time, then stable resource ID.

        Candidate tuples begin with (completion_datetime, resource_id, ...).
        This is the common tie-break rule for legacy lines and production
        nodes, and deliberately does not depend on input iteration order.
        """
        return CandidateNodeDecision.choose(candidates)

    @staticmethod
    def _parse_timestamp(value):
        return parse_database_timestamp(value)

    @classmethod
    def allocate_split_on_nodes(
        cls,
        *,
        nodes,
        earliest,
        quantity,
        standard,
        operation=None,
        order=None,
        serial_ids=None,
        allocation_key_prefix="",
        candidate_allocator,
    ):
        """Allocate whole batches or serial items over equivalent nodes.

        Node calendars and existing occupancy stay outside this policy. The
        adapter supplies candidate_allocator(node, earliest, duration, additions), which
        must only evaluate the provided facts and return candidate segments.
        The policy owns quantity splitting, setup/changeover accounting,
        earliest-completion choice, allocation facts, and conservation.
        """
        remaining_quantity = max(int(quantity or 0), 0)
        if remaining_quantity <= 0:
            return {
                "segments": [],
                "allocations": [],
                "occupancy_additions": {},
            }
        progress = AllocationResultAccumulator(nodes, allocation_key_prefix)
        try:
            serial_values = SerialExclusiveStrategy.normalize(serial_ids, remaining_quantity)
            facts = CapacityAllocationFacts(earliest, standard, operation or {}, order or {})
            if serial_values:
                decision = SerialExclusiveStrategy.select(
                    facts=facts,
                    nodes=progress.snapshot(),
                    quantity=remaining_quantity, candidate_allocator=candidate_allocator,
                    duration_minutes=cls.duration_minutes,
                )
                progress.record_serial(decision, serial_values)
                return progress.result(remaining_quantity).as_legacy_result()

            while remaining_quantity > 0:
                decision = QuantitySplitStrategy.select(
                    facts=facts, nodes=progress.snapshot(), remaining_quantity=remaining_quantity,
                    candidate_allocator=candidate_allocator, duration_minutes=cls.duration_minutes,
                )
                progress.record_quantity(decision)
                remaining_quantity -= decision.quantity
            return progress.result(quantity).as_legacy_result()
        except Exception as exc:
            progress.attach_failure_occupancy(exc)
            raise
