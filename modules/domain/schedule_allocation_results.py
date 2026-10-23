"""Per-call occupancy accumulation and immutable allocation result assembly.

Mutation is confined to this local accumulator. Strategies exchange frozen
snapshots and candidates; no state is shared between planning calls.
"""

from modules.domain.production_node_scheduling import NodeSchedulingError, ProductionNodePolicy
from modules.domain.production_time import parse_database_timestamp
from modules.domain.schedule_allocation_batch import BatchAllocationStrategy
from modules.domain.schedule_planning import CapacityAllocationResult, CapacityNodeFacts


class AllocationResultAccumulator:
    def __init__(self, nodes, allocation_key_prefix):
        # Dict order deliberately retains the first position of duplicate IDs.
        self._nodes = {node["id"]: dict(node) for node in nodes}
        if not self._nodes:
            raise NodeSchedulingError("NO_COMPATIBLE_NODE", "没有满足能力要求的生产节点", {})
        self._segments = {node_id: [] for node_id in self._nodes}
        self._quantities = dict.fromkeys(self._nodes, 0)
        self._batch_counters = {}
        self._occupancy = {}
        self._allocations = []
        self._prefix = allocation_key_prefix

    def snapshot(self):
        return tuple(
            CapacityNodeFacts(node, self._quantities[node_id], tuple(self._occupancy.get(node_id, ())))
            for node_id, node in self._nodes.items()
        )

    def _batch_key(self, node_id, batch_number):
        key = f"node-{node_id}:batch-{batch_number}"
        return f"{self._prefix}:{key}" if self._prefix else key

    def _assign_segments(self, decision):
        segments = decision.mutable_segments()
        for index, segment in enumerate(segments):
            segment["quantity"] = decision.quantity if index == 0 else 0
            self._segments[decision.node_id].append(segment)
        return segments

    def _record_occupancy(self, node_id, segments):
        self._occupancy.setdefault(node_id, []).extend(
            (parse_database_timestamp(segment["start_at"]), parse_database_timestamp(segment["end_at"]))
            for segment in segments
        )

    def _allocation(self, decision, segments, batch_number, *, quantity, serial_id, changeover):
        return {
            "production_node_id": decision.node_id,
            "quantity": quantity, "serial_id": serial_id,
            "batch_key": self._batch_key(decision.node_id, batch_number),
            "changeover_minutes": changeover,
            "segment_start_at": segments[0]["start_at"],
            "segment_end_at": segments[-1]["end_at"],
        }

    def record_serial(self, decision, serials):
        segments = self._assign_segments(decision)
        # Preserve occupancy evidence even if subsequent allocation metadata fails.
        self._record_occupancy(decision.node_id, segments)
        for serial_id in serials:
            self._allocations.append(self._allocation(
                decision, segments, 1, quantity=1, serial_id=serial_id,
                changeover=BatchAllocationStrategy.changeover_minutes(
                    decision.capability, include_setup=True,
                ),
            ))

    def record_quantity(self, decision):
        node_id = decision.node_id
        batch_number = self._batch_counters.get(node_id, 0) + 1
        self._batch_counters[node_id] = batch_number
        segments = self._assign_segments(decision)
        self._allocations.append(self._allocation(
            decision, segments, batch_number, quantity=decision.quantity, serial_id=None,
            changeover=BatchAllocationStrategy.changeover_minutes(
                decision.capability,
                include_setup=decision.capacity_mode == "batch" and self._quantities[node_id] == 0,
            ),
        ))
        self._quantities[node_id] += decision.quantity
        self._record_occupancy(node_id, segments)

    def result(self, expected_quantity):
        ProductionNodePolicy.validate_quantity_conservation(expected_quantity, self._allocations)
        return CapacityAllocationResult(
            segments=tuple(segment for group in self._segments.values() for segment in group),
            allocations=tuple(self._allocations), occupancy_additions=self._occupancy,
        )

    def attach_failure_occupancy(self, exc):
        if self._occupancy:
            try:
                exc.capacity_occupancy_additions = self._occupancy
            except (AttributeError, TypeError):
                pass
