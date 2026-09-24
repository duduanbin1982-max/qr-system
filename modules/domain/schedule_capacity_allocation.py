"""Pure minute-capacity allocation primitives for production scheduling.

This module only transforms caller-supplied standards, ordered calendar slots,
occupancy intervals, and candidate completion facts. Calendar and override
facts are resolved by the service/repository adapter.
"""

from datetime import datetime, timedelta
import math

from modules.domain.production_node_scheduling import (
    NodeSchedulingError,
    ProductionNodePolicy,
)


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
        return min(candidates, key=lambda item: (item[0], item[1]))

    @staticmethod
    def _parse_timestamp(value):
        if isinstance(value, datetime):
            return value
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("T", " "))
        except (TypeError, ValueError):
            return None

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
        adapter supplies candidate_allocator(node, duration, additions), which
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
        state = {
            node["id"]: {
                "node": dict(node),
                "segments": [],
                "quantity": 0,
            }
            for node in nodes
        }
        if not state:
            raise NodeSchedulingError(
                "NO_COMPATIBLE_NODE", "没有满足能力要求的生产节点", {}
            )
        occupancy_additions = {}

        def allocate(node_id, node, duration):
            prior_additions = occupancy_additions.get(node_id, [])
            candidate = candidate_allocator(node, earliest, duration, prior_additions)
            return candidate

        def record_occupancy(node_id, segments):
            occupancy_additions.setdefault(node_id, []).extend(
                (
                    cls._parse_timestamp(segment["start_at"]),
                    cls._parse_timestamp(segment["end_at"]),
                )
                for segment in segments
            )

        def result(allocations):
            segments = [
                segment
                for item in state.values()
                for segment in item["segments"]
            ]
            return {
                "segments": segments,
                "allocations": allocations,
                "occupancy_additions": occupancy_additions,
            }

        try:
            serial_values = [
                str(value).strip()
                for value in (serial_ids or ())
                if str(value).strip()
            ]
            if serial_values:
                if (
                    len(set(serial_values)) != len(serial_values)
                    or len(serial_values) != remaining_quantity
                ):
                    raise NodeSchedulingError(
                        "SERIAL_ITEM_SPLIT_FORBIDDEN",
                        "序列件输入与排程数量不一致",
                        {
                            "requested_quantity": remaining_quantity,
                            "serial_count": len(serial_values),
                        },
                    )
                candidates = []
                for node_id, item in state.items():
                    capability = ProductionNodePolicy.matching_capability(
                        capabilities=item["node"].get("capabilities", []),
                        operation=operation or {},
                        order=order or {},
                    ) or {}
                    if item["node"].get("capacity_mode") == "batch":
                        batch_size, _, _ = ProductionNodePolicy._batch_configuration(
                            capability
                        )
                        if remaining_quantity > batch_size:
                            continue
                        duration = ProductionNodePolicy.batch_duration_minutes(
                            remaining_quantity,
                            capability,
                            changeover_required=True,
                        )
                    else:
                        duration = cls.duration_minutes(remaining_quantity, standard)
                    try:
                        candidate = allocate(node_id, item["node"], duration)
                    except (ValueError, NodeSchedulingError):
                        continue
                    candidates.append(
                        (
                            cls._parse_timestamp(candidate[-1]["end_at"]),
                            node_id,
                            candidate,
                            capability,
                        )
                    )
                if not candidates:
                    raise NodeSchedulingError(
                        "SERIAL_ITEM_SPLIT_FORBIDDEN",
                        "序列件没有可独占的生产节点",
                        {},
                    )
                _, node_id, candidate, capability = cls.choose_earliest_completion(
                    candidates
                )
                for index, segment in enumerate(candidate):
                    segment["quantity"] = remaining_quantity if index == 0 else 0
                    state[node_id]["segments"].append(segment)
                record_occupancy(node_id, candidate)
                first = candidate[0]
                batch_key = (
                    f"{allocation_key_prefix}:node-{node_id}:batch-1"
                    if allocation_key_prefix
                    else f"node-{node_id}:batch-1"
                )
                allocations = [
                    {
                        "production_node_id": node_id,
                        "quantity": 1,
                        "serial_id": serial_id,
                        "batch_key": batch_key,
                        "changeover_minutes": float(
                            capability.get("changeover_minutes") or 0
                        ),
                        "segment_start_at": first["start_at"],
                        "segment_end_at": candidate[-1]["end_at"],
                    }
                    for serial_id in serial_values
                ]
                ProductionNodePolicy.validate_quantity_conservation(
                    remaining_quantity, allocations
                )
                return result(allocations)

            allocations = []
            batch_counters = {}
            while remaining_quantity > 0:
                available = []
                base_chunk = max(1, int(math.ceil(remaining_quantity / len(state))))
                for node_id, item in state.items():
                    include_setup = item["quantity"] == 0
                    capability = ProductionNodePolicy.matching_capability(
                        capabilities=item["node"].get("capabilities", []),
                        operation=operation or {},
                        order=order or {},
                    ) or {}
                    capacity_mode = item["node"].get("capacity_mode", "exclusive")
                    chunk = base_chunk
                    if capacity_mode == "batch":
                        batch_size, _, _ = ProductionNodePolicy._batch_configuration(
                            capability
                        )
                        chunk = min(chunk, batch_size)
                        duration = ProductionNodePolicy.batch_duration_minutes(
                            chunk,
                            capability,
                            changeover_required=include_setup,
                        )
                    else:
                        effective_standard = (
                            standard
                            if include_setup
                            else {**dict(standard), "setup_minutes": 0}
                        )
                        duration = cls.duration_minutes(chunk, effective_standard)
                    try:
                        candidate = allocate(node_id, item["node"], duration)
                    except (ValueError, NodeSchedulingError):
                        continue
                    available.append(
                        (
                            cls._parse_timestamp(candidate[-1]["end_at"]),
                            node_id,
                            candidate,
                            chunk,
                            capability,
                            capacity_mode,
                        )
                    )
                if not available:
                    raise NodeSchedulingError(
                        "NODE_CALENDAR_UNAVAILABLE",
                        "工作日历在可搜索范围内没有足够产能",
                        {},
                    )
                _, node_id, candidate, allocated, capability, capacity_mode = (
                    cls.choose_earliest_completion(available)
                )
                item = state[node_id]
                batch_number = batch_counters.get(node_id, 0) + 1
                batch_counters[node_id] = batch_number
                batch_key = (
                    f"{allocation_key_prefix}:node-{node_id}:batch-{batch_number}"
                    if allocation_key_prefix
                    else f"node-{node_id}:batch-{batch_number}"
                )
                for index, segment in enumerate(candidate):
                    segment["quantity"] = allocated if index == 0 else 0
                    item["segments"].append(segment)
                first = candidate[0]
                allocations.append(
                    {
                        "production_node_id": node_id,
                        "quantity": allocated,
                        "serial_id": None,
                        "batch_key": batch_key,
                        "changeover_minutes": (
                            float(capability.get("changeover_minutes") or 0)
                            if capacity_mode == "batch" and item["quantity"] == 0
                            else 0
                        ),
                        "segment_start_at": first["start_at"],
                        "segment_end_at": candidate[-1]["end_at"],
                    }
                )
                item["quantity"] += allocated
                record_occupancy(node_id, candidate)
                remaining_quantity -= allocated
            ProductionNodePolicy.validate_quantity_conservation(
                quantity, allocations
            )
            return result(allocations)
        except Exception as exc:
            if occupancy_additions:
                try:
                    exc.capacity_occupancy_additions = occupancy_additions
                except (AttributeError, TypeError):
                    pass
            raise
