"""Pure ordinary-quantity proposals, evaluated against immutable node progress."""

import math

from modules.domain.production_node_scheduling import NodeSchedulingError, ProductionNodePolicy
from modules.domain.schedule_allocation_candidates import CandidateNodeDecision
from modules.domain.schedule_allocation_batch import BatchAllocationStrategy
from modules.domain.schedule_planning import copy_planning_runtime_value


class QuantitySplitStrategy:
    """Split remaining quantity with the historical ceil(remaining/nodes) rule."""

    @staticmethod
    def chunk(remaining_quantity, node_count):
        return max(1, int(math.ceil(remaining_quantity / node_count)))

    @staticmethod
    def exclusive_duration(quantity, standard, include_setup, duration_minutes):
        effective = standard if include_setup else {**dict(standard), "setup_minutes": 0}
        return duration_minutes(quantity, effective)

    @classmethod
    def select(cls, *, facts, nodes, remaining_quantity, candidate_allocator, duration_minutes):
        candidates = []
        base_chunk = cls.chunk(remaining_quantity, len(nodes))
        for progress in nodes:
            node = copy_planning_runtime_value(progress.node)
            include_setup = progress.allocated_quantity == 0
            capability = ProductionNodePolicy.matching_capability(
                capabilities=node.get("capabilities", []),
                operation=facts.operation, order=facts.order,
            ) or {}
            capacity_mode = node.get("capacity_mode", "exclusive")
            chunk = base_chunk
            if capacity_mode == "batch":
                demand = BatchAllocationStrategy.demand(
                    chunk, capability, include_setup=include_setup,
                )
                chunk, duration = demand.quantity, demand.duration
            else:
                duration = cls.exclusive_duration(
                    chunk, facts.standard, include_setup, duration_minutes,
                )
            candidate = CandidateNodeDecision.evaluate(
                node_id=node["id"], node=node, earliest=facts.earliest, duration=duration,
                additions=list(progress.occupancy), quantity=chunk,
                capability=capability, capacity_mode=capacity_mode,
                candidate_allocator=candidate_allocator,
            )
            if candidate is not None:
                candidates.append(candidate)
        if not candidates:
            raise NodeSchedulingError(
                "NODE_CALENDAR_UNAVAILABLE", "工作日历在可搜索范围内没有足够产能", {},
            )
        return CandidateNodeDecision.select(candidates)
