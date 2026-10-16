"""Fixed-batch limits and preparation/changeover accounting, without I/O."""

from modules.domain.production_node_scheduling import ProductionNodePolicy
from modules.domain.schedule_planning import CapacityDemand


class BatchAllocationStrategy:
    @staticmethod
    def demand(quantity, capability, *, include_setup, whole_group=False):
        # Configuration validation precedes the whole-group capacity rejection.
        batch_size, _, _ = ProductionNodePolicy._batch_configuration(capability)
        if whole_group and quantity > batch_size:
            return None
        chunk = quantity if whole_group else min(quantity, batch_size)
        return CapacityDemand(chunk, ProductionNodePolicy.batch_duration_minutes(
            chunk, capability, changeover_required=include_setup,
        ))

    @staticmethod
    def changeover_minutes(capability, *, include_setup):
        return float(capability.get("changeover_minutes") or 0) if include_setup else 0
