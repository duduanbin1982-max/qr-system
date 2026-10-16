"""Whole-group, single-node serial allocation; serials are never split."""

from modules.domain.production_node_scheduling import NodeSchedulingError, ProductionNodePolicy
from modules.domain.schedule_allocation_candidates import CandidateNodeDecision
from modules.domain.schedule_allocation_batch import BatchAllocationStrategy
from modules.domain.schedule_planning import copy_planning_runtime_value


class SerialExclusiveStrategy:
    @staticmethod
    def normalize(serial_ids, quantity):
        serials = tuple(str(value).strip() for value in (serial_ids or ()) if str(value).strip())
        if serials and (len(set(serials)) != len(serials) or len(serials) != quantity):
            raise NodeSchedulingError(
                "SERIAL_ITEM_SPLIT_FORBIDDEN", "序列件输入与排程数量不一致",
                {"requested_quantity": quantity, "serial_count": len(serials)},
            )
        return serials

    @staticmethod
    def select(*, facts, nodes, quantity, candidate_allocator, duration_minutes):
        candidates = []
        for progress in nodes:
            node = copy_planning_runtime_value(progress.node)
            capability = ProductionNodePolicy.matching_capability(
                capabilities=node.get("capabilities", []),
                operation=facts.operation, order=facts.order,
            ) or {}
            if node.get("capacity_mode") == "batch":
                demand = BatchAllocationStrategy.demand(
                    quantity, capability, include_setup=True, whole_group=True,
                )
                if demand is None:
                    continue
                duration = demand.duration
            else:
                duration = duration_minutes(quantity, facts.standard)
            candidate = CandidateNodeDecision.evaluate(
                node_id=node["id"], node=node, earliest=facts.earliest, duration=duration,
                additions=list(progress.occupancy), quantity=quantity,
                capability=capability, capacity_mode=node.get("capacity_mode", "exclusive"),
                candidate_allocator=candidate_allocator,
            )
            if candidate is not None:
                candidates.append(candidate)
        if not candidates:
            raise NodeSchedulingError(
                "SERIAL_ITEM_SPLIT_FORBIDDEN", "序列件没有可独占的生产节点", {},
            )
        return CandidateNodeDecision.select(candidates)
