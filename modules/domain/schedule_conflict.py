"""Pure conflict detection for immutable production schedule revisions.

The detector accepts normalized facts only.  It deliberately does not read the
database or feature flags so the same revision and capacity snapshot always
produce the same conflict evidence.
"""

from collections import defaultdict
from datetime import datetime
import hashlib
import json


def _parse_datetime(value):
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value).strip().replace("T", " "))
    except (TypeError, ValueError):
        return None


def _format_datetime(value):
    if value is None:
        return ""
    return value.strftime("%Y-%m-%d %H:%M:%S")


class ScheduleConflictPolicy:
    """Detect hard schedule conflicts from candidate and capacity facts."""

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

    @staticmethod
    def _resource_key(fact):
        node_id = fact.get("production_node_id")
        if node_id not in (None, ""):
            return "node", int(node_id)
        line_id = fact.get("process_line_id")
        if line_id not in (None, ""):
            return "legacy_line", int(line_id)
        return None

    @staticmethod
    def _overlap(first, second):
        start = max(first["_start"], second["_start"])
        end = min(first["_end"], second["_end"])
        if start >= end:
            return None
        return start, end, max(int((end - start).total_seconds() / 60), 1)

    @staticmethod
    def _identity(fact):
        return {
            "order_id": fact.get("order_id"),
            "order_process_id": fact.get("order_process_id"),
            "process_id": fact.get("process_id"),
            "process_name": fact.get("process_name") or "",
            "revision_item_id": fact.get("revision_item_id"),
            "schedule_id": fact.get("schedule_id"),
            "production_node_id": fact.get("production_node_id"),
            "process_line_id": fact.get("process_line_id"),
            "node_name": fact.get("node_name") or "",
        }

    @classmethod
    def _conflict(
        cls,
        conflict_type,
        reason,
        *,
        first=None,
        second=None,
        overlap=None,
        severity="blocking",
        details=None,
    ):
        first = first or {}
        second = second or {}
        payload = {
            "conflict_type": conflict_type,
            "severity": severity,
            "reason": reason,
            "first": cls._identity(first),
            "second": cls._identity(second),
            "overlap_start_at": _format_datetime(overlap[0]) if overlap else "",
            "overlap_end_at": _format_datetime(overlap[1]) if overlap else "",
            "overlap_minutes": overlap[2] if overlap else 0,
            "first_locked": bool(first.get("locked")),
            "second_locked": bool(second.get("locked")),
            "details": dict(details or {}),
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        payload["evidence_digest"] = hashlib.sha256(
            encoded.encode("utf-8")
        ).hexdigest()
        return payload

    @classmethod
    def detect(
        cls,
        *,
        candidate_intervals=(),
        occupied_intervals=(),
        unavailable_intervals=(),
        operations=(),
    ):
        """Return deterministic, de-duplicated conflict evidence."""
        conflicts = []
        candidate = []
        occupied = []

        for source, destination in (
            (candidate_intervals or (), candidate),
            (occupied_intervals or (), occupied),
        ):
            for raw in source:
                fact = dict(raw)
                start = _parse_datetime(fact.get("start_at"))
                end = _parse_datetime(fact.get("end_at"))
                resource_key = cls._resource_key(fact)
                if start is None or end is None or end <= start or resource_key is None:
                    if destination is candidate:
                        conflicts.append(
                            cls._conflict(
                                "invalid_capacity_interval",
                                "内部工序缺少有效的生产节点和占用时间",
                                first=fact,
                            )
                        )
                    continue
                fact["_start"] = start
                fact["_end"] = end
                fact["_resource_key"] = resource_key
                destination.append(fact)

        all_intervals = candidate + occupied
        for index, first in enumerate(candidate):
            for second in all_intervals:
                if first is second:
                    continue
                if second in candidate and candidate.index(second) <= index:
                    continue
                if first["_resource_key"] != second["_resource_key"]:
                    continue
                # Batch nodes may overlap by design.  Their quantity/capacity
                # constraints are validated by the allocation policy instead.
                if (
                    str(first.get("capacity_mode") or "exclusive") != "exclusive"
                    and str(second.get("capacity_mode") or "exclusive") != "exclusive"
                ):
                    continue
                overlap = cls._overlap(first, second)
                if overlap is None:
                    continue
                locked = bool(first.get("locked") or second.get("locked"))
                conflict_type = (
                    "locked_task_conflict" if locked else "exclusive_node_overlap"
                )
                resource_name = (
                    first.get("node_name")
                    or second.get("node_name")
                    or f"生产资源 {first['_resource_key'][1]}"
                )
                conflicts.append(
                    cls._conflict(
                        conflict_type,
                        (
                            f"{resource_name} 存在 {overlap[2]} 分钟时间重叠"
                            + ("，且涉及已锁定任务" if locked else "")
                        ),
                        first=first,
                        second=second,
                        overlap=overlap,
                    )
                )

        unavailable = []
        for raw in unavailable_intervals or ():
            fact = dict(raw)
            start = _parse_datetime(fact.get("start_at"))
            end = _parse_datetime(fact.get("end_at"))
            resource_key = cls._resource_key(fact)
            if start is None or end is None or end <= start or resource_key is None:
                continue
            fact["_start"] = start
            fact["_end"] = end
            fact["_resource_key"] = resource_key
            unavailable.append(fact)
        for fact in candidate:
            for unavailable_fact in unavailable:
                if fact["_resource_key"] != unavailable_fact["_resource_key"]:
                    continue
                overlap = cls._overlap(fact, unavailable_fact)
                if overlap is None:
                    continue
                conflicts.append(
                    cls._conflict(
                        "downtime_overlap",
                        (
                            f"{fact.get('node_name') or '生产节点'} 与停机/不可用时段"
                            f"重叠 {overlap[2]} 分钟"
                        ),
                        first=fact,
                        overlap=overlap,
                        details={
                            "unavailable_type": unavailable_fact.get("unavailable_type")
                            or "downtime",
                            "unavailable_id": unavailable_fact.get("id"),
                            "unavailable_reason": unavailable_fact.get("reason") or "",
                        },
                    )
                )

        normalized_operations = [dict(item) for item in (operations or ())]
        internal_operations = []
        for operation in normalized_operations:
            mode = str(operation.get("execution_mode") or "internal")
            has_capacity = bool(
                operation.get("production_node_id")
                or operation.get("process_line_id")
                or operation.get("segments")
                or operation.get("allocations")
            )
            if mode in {"outsourced", "non_scheduled"}:
                if has_capacity:
                    conflicts.append(
                        cls._conflict(
                            "non_capacity_operation_allocation",
                            "外协或非排程工序不得占用内部生产节点容量",
                            first=operation,
                        )
                    )
                continue
            if operation.get("status") != "blocked":
                internal_operations.append(operation)

            serial_allocations = defaultdict(list)
            for allocation in operation.get("allocations") or ():
                serial_id = str(allocation.get("serial_id") or "").strip()
                if serial_id:
                    serial_allocations[serial_id].append(dict(allocation))
            for serial_id, allocations in serial_allocations.items():
                node_ids = {
                    item.get("production_node_id") for item in allocations
                    if item.get("production_node_id") not in (None, "")
                }
                if len(allocations) > 1 or len(node_ids) > 1:
                    conflicts.append(
                        cls._conflict(
                            "serial_duplicate",
                            f"序列件 {serial_id} 在同一道工序中被重复分配",
                            first=operation,
                            details={
                                "serial_id": serial_id,
                                "allocation_count": len(allocations),
                                "production_node_ids": sorted(node_ids),
                            },
                        )
                    )

        internal_operations.sort(
            key=lambda item: (
                int(item.get("seq_order") or 0),
                int(item.get("order_process_id") or 0),
            )
        )
        for previous, current in zip(
            internal_operations, internal_operations[1:]
        ):
            previous_end = _parse_datetime(
                previous.get("planned_end_at") or previous.get("plan_end")
            )
            current_start = _parse_datetime(
                current.get("planned_start_at") or current.get("plan_start")
            )
            if previous_end and current_start and current_start < previous_end:
                overlap = (
                    current_start,
                    previous_end,
                    max(int((previous_end - current_start).total_seconds() / 60), 1),
                )
                conflicts.append(
                    cls._conflict(
                        "sequence_violation",
                        (
                            f"工序 {current.get('process_name') or current.get('process_id')} "
                            "早于前序工序完成"
                        ),
                        first=previous,
                        second=current,
                        overlap=overlap,
                    )
                )

        unique = {}
        for conflict in conflicts:
            unique.setdefault(conflict["evidence_digest"], conflict)
        return sorted(
            unique.values(),
            key=lambda item: (
                item["conflict_type"],
                item["overlap_start_at"],
                item["first"].get("order_process_id") or 0,
                item["second"].get("order_process_id") or 0,
                item["evidence_digest"],
            ),
        )

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
