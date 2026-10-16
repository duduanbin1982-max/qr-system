"""Pure candidate evaluation and the stable completion/node-ID decision."""

from modules.domain.production_node_scheduling import NodeSchedulingError
from modules.domain.production_time import parse_database_timestamp
from modules.domain.schedule_planning import CapacityCandidate


class CandidateNodeDecision:
    """Calendar rejection skips a candidate; malformed facts still propagate."""

    @staticmethod
    def evaluate(*, node_id, node, earliest, duration, additions, quantity,
                 capability, capacity_mode, candidate_allocator):
        try:
            segments = candidate_allocator(node, earliest, duration, additions)
        except (ValueError, NodeSchedulingError):
            return None
        # Keep indexing/parsing outside the rejection handler: callback defects
        # have never meant "try another node" at this boundary.
        return CapacityCandidate(
            completion=parse_database_timestamp(segments[-1]["end_at"]),
            node_id=node_id, segments=tuple(segments), quantity=quantity,
            capability=capability, capacity_mode=capacity_mode,
        )

    @staticmethod
    def choose(candidates, *, key=lambda item: (item[0], item[1])):
        """Also accepts legacy line-candidate tuples through the public seam."""
        return min(candidates, key=key)

    @classmethod
    def select(cls, candidates):
        return cls.choose(candidates, key=lambda item: (item.completion, item.node_id))
