"""Pure policies for deriving a dynamic schedule from production facts.

The policy deliberately knows nothing about SQLite or Flask.  It turns the
current production facts into a deterministic, auditable replan input:
completed output is subtracted, open rework is added back, and downtime is
kept as a separate immutable source fact.
"""

import hashlib
import json


class ScheduleDynamicReplanPolicy:
    """Build deterministic operation baselines and input digests."""

    @staticmethod
    def _non_negative_int(value):
        try:
            return max(int(value or 0), 0)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def operation_baseline(cls, operation):
        quantity = cls._non_negative_int(operation.get("order_quantity"))
        completed = cls._non_negative_int(operation.get("completed_quantity"))
        rework = cls._non_negative_int(operation.get("rework_quantity"))
        remaining = max(quantity - completed, 0) + rework
        return {
            "order_process_id": int(operation["order_process_id"]),
            "process_id": int(operation["process_id"]),
            "seq_order": int(operation.get("seq_order") or 0),
            "order_quantity": quantity,
            "completed_quantity": completed,
            "rework_quantity": rework,
            "remaining_quantity": remaining,
            "status": "completed" if remaining == 0 else "pending",
        }

    @classmethod
    def build_input_snapshot(cls, *, order, operations, downtime, occupancy, reason, as_of,
                             locked_tasks=None):
        baselines = [cls.operation_baseline(item) for item in operations]
        snapshot = {
            "order_id": int(order["id"]),
            "order_quantity": cls._non_negative_int(order.get("quantity")),
            "order_completed": cls._non_negative_int(order.get("completed")),
            "as_of": as_of or "",
            "reason": reason or "",
            "operations": baselines,
            "downtime": [cls._resource_fact(item, include_reason=True) for item in downtime],
            "occupancy": [cls._resource_fact(item, include_schedule=True) for item in occupancy],
            "locked_tasks": [
                {
                    "revision_item_id": int(item["revision_item_id"]),
                    "order_process_id": int(item["order_process_id"]),
                    "production_node_id": int(item["production_node_id"]),
                    "planned_start_at": str(item.get("planned_start_at") or ""),
                    "planned_end_at": str(item.get("planned_end_at") or ""),
                }
                for item in (locked_tasks or ())
            ],
        }
        encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return snapshot, hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _resource_fact(item, *, include_reason=False, include_schedule=False):
        fact = {
            "start_at": str(item["start_at"]),
            "end_at": str(item["end_at"]),
        }
        if item.get("production_node_id") not in (None, ""):
            fact["production_node_id"] = int(item["production_node_id"])
        elif item.get("process_line_id") not in (None, ""):
            fact["process_line_id"] = int(item["process_line_id"])
        if item.get("id") not in (None, ""):
            fact["id"] = int(item["id"])
        if include_reason:
            fact["reason"] = item.get("reason", "") or ""
        if include_schedule:
            fact["schedule_id"] = int(item.get("schedule_id") or 0)
        return fact
