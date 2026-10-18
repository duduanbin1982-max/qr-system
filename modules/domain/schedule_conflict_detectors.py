"""Independent pure detectors over one immutable conflict snapshot.

    Capacity: invalid intervals, exclusive overlap and non-capacity operations.
    Downtime: candidate/unavailable overlap.
    Locked tasks: exclusive overlap involving a lock.
    Serial: duplicate allocation within an internal operation, even if blocked.
    Sequence: adjacent unblocked internal operations in their original order key.
"""

from collections import defaultdict

from modules.domain.production_time import parse_database_timestamp
from modules.domain.schedule_conflict_evidence import build_conflict
from modules.domain.schedule_conflict_snapshot import interval_overlap


def _is_internal(operation):
    return str(operation.get("execution_mode") or "internal") not in {
        "outsourced", "non_scheduled",
    }


def _capacity_overlaps(snapshot, *, locked):
    intervals = snapshot.candidate_intervals + snapshot.occupied_intervals
    for index, first in enumerate(snapshot.candidate_intervals):
        for second_index, second in enumerate(intervals):
            position = snapshot.equal_candidate_positions[second_index]
            if second_index == index or (position is not None and position <= index):
                continue
            if bool(first.get("locked") or second.get("locked")) != locked:
                continue
            if first["_resource_key"] != second["_resource_key"]:
                continue
            # Two batch intervals may overlap; any exclusive participant may not.
            if all(str(item.get("capacity_mode") or "exclusive") != "exclusive"
                   for item in (first, second)):
                continue
            overlap = interval_overlap(first, second)
            if overlap is not None:
                yield first, second, overlap


def _overlap_evidence(first, second, overlap, *, locked):
    name = first.get("node_name") or second.get("node_name") or f"生产资源 {first['_resource_key'][1]}"
    return build_conflict(
        "locked_task_conflict" if locked else "exclusive_node_overlap",
        f"{name} 存在 {overlap[2]} 分钟时间重叠" + ("，且涉及已锁定任务" if locked else ""),
        first=first, second=second, overlap=overlap,
    )


class CapacityConflictDetector:
    @staticmethod
    def detect(snapshot):
        conflicts = [build_conflict(
            "invalid_capacity_interval", "内部工序缺少有效的生产节点和占用时间", first=fact,
        ) for fact in snapshot.invalid_candidate_intervals]
        conflicts.extend(_overlap_evidence(first, second, overlap, locked=False)
                         for first, second, overlap in _capacity_overlaps(snapshot, locked=False))
        for operation in snapshot.operations:
            if not _is_internal(operation) and any(operation.get(field) for field in (
                "production_node_id", "process_line_id", "segments", "allocations",
            )):
                conflicts.append(build_conflict(
                    "non_capacity_operation_allocation", "外协或非排程工序不得占用内部生产节点容量",
                    first=operation,
                ))
        return tuple(conflicts)


class LockedTaskConflictDetector:
    @staticmethod
    def detect(snapshot):
        return tuple(_overlap_evidence(first, second, overlap, locked=True)
                     for first, second, overlap in _capacity_overlaps(snapshot, locked=True))


class DowntimeConflictDetector:
    @staticmethod
    def detect(snapshot):
        conflicts = []
        for fact in snapshot.candidate_intervals:
            for unavailable in snapshot.unavailable_intervals:
                if fact["_resource_key"] != unavailable["_resource_key"]:
                    continue
                overlap = interval_overlap(fact, unavailable)
                if overlap is None:
                    continue
                conflicts.append(build_conflict(
                    "downtime_overlap",
                    f"{fact.get('node_name') or '生产节点'} 与停机/不可用时段重叠 {overlap[2]} 分钟",
                    first=fact, overlap=overlap, details={
                        "unavailable_type": unavailable.get("unavailable_type") or "downtime",
                        "unavailable_id": unavailable.get("id"),
                        "unavailable_reason": unavailable.get("reason") or "",
                    },
                ))
        return tuple(conflicts)


class SerialConflictDetector:
    @staticmethod
    def detect(snapshot):
        conflicts = []
        for operation in snapshot.operations:
            if not _is_internal(operation):
                continue
            serial_allocations = defaultdict(list)
            for allocation in operation.get("allocations") or ():
                serial_id = str(allocation.get("serial_id") or "").strip()
                if serial_id:
                    serial_allocations[serial_id].append(allocation)
            for serial_id, allocations in serial_allocations.items():
                node_ids = {item.get("production_node_id") for item in allocations
                            if item.get("production_node_id") not in (None, "")}
                if len(allocations) > 1 or len(node_ids) > 1:
                    conflicts.append(build_conflict(
                        "serial_duplicate", f"序列件 {serial_id} 在同一道工序中被重复分配",
                        first=operation, details={
                            "serial_id": serial_id, "allocation_count": len(allocations),
                            "production_node_ids": sorted(node_ids),
                        },
                    ))
        return tuple(conflicts)


class SequenceConflictDetector:
    @staticmethod
    def detect(snapshot):
        operations = sorted(
            (item for item in snapshot.operations if _is_internal(item) and item.get("status") != "blocked"),
            key=lambda item: (int(item.get("seq_order") or 0), int(item.get("order_process_id") or 0)),
        )
        conflicts = []
        for previous, current in zip(operations, operations[1:]):
            previous_end = parse_database_timestamp(previous.get("planned_end_at") or previous.get("plan_end"))
            current_start = parse_database_timestamp(current.get("planned_start_at") or current.get("plan_start"))
            if previous_end and current_start and current_start < previous_end:
                overlap = (current_start, previous_end,
                           max(int((previous_end - current_start).total_seconds() / 60), 1))
                conflicts.append(build_conflict(
                    "sequence_violation",
                    f"工序 {current.get('process_name') or current.get('process_id')} 早于前序工序完成",
                    first=previous, second=current, overlap=overlap,
                ))
        return tuple(conflicts)


CONFLICT_DETECTORS = (
    CapacityConflictDetector, LockedTaskConflictDetector, DowntimeConflictDetector,
    SerialConflictDetector, SequenceConflictDetector,
)
