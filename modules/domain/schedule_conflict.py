"""Pure conflict assessment with independent detectors and stable evidence."""

from collections import defaultdict

from modules.domain.schedule_conflict_detectors import CONFLICT_DETECTORS
from modules.domain.schedule_conflict_evidence import merge_conflict_evidence
from modules.domain.schedule_conflict_snapshot import build_conflict_snapshot


class ScheduleConflictPolicy:
    """Coordinate pure detectors without changing the public evidence format."""

    BLOCKING_TYPES = frozenset(
        {
            "exclusive_node_overlap",
            "downtime_overlap",
            "locked_task_conflict",
            "sequence_violation",
            "serial_duplicate",
            "non_capacity_operation_allocation",
            "invalid_capacity_interval",
        }
    )

    @classmethod
    def detect(cls, *, candidate_intervals=(), occupied_intervals=(),
               unavailable_intervals=(), operations=()):
        """Assess one immutable snapshot, then merge, deduplicate and sort."""
        snapshot = build_conflict_snapshot(
            candidate_intervals=candidate_intervals, occupied_intervals=occupied_intervals,
            unavailable_intervals=unavailable_intervals, operations=operations,
        )
        return merge_conflict_evidence(detector.detect(snapshot) for detector in CONFLICT_DETECTORS)

    @classmethod
    def summarize(cls, conflicts):
        rows = list(conflicts or ())
        blocking = [
            row for row in rows
            if row.get("severity") == "blocking"
            or row.get("conflict_type") in cls.BLOCKING_TYPES
        ]
        by_type = defaultdict(int)
        for row in rows:
            by_type[row.get("conflict_type") or "unknown"] += 1
        return {
            "conflict_count": len(rows),
            "blocking_count": len(blocking),
            "warning_count": len(rows) - len(blocking),
            "by_type": dict(sorted(by_type.items())),
            "primary_reason": blocking[0]["reason"] if blocking else (
                rows[0]["reason"] if rows else ""
            ),
        }


__all__ = ["ScheduleConflictPolicy"]
