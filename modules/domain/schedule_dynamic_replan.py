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
    def build_input_snapshot(cls, *, order, operations, downtime, occupancy, reason, as_of):
        baselines = [cls.operation_baseline(item) for item in operations]
        snapshot = {
            "order_id": int(order["id"]),
            "order_quantity": cls._non_negative_int(order.get("quantity")),
            "order_completed": cls._non_negative_int(order.get("completed")),
            "as_of": as_of or "",
            "reason": reason or "",
            "operations": baselines,
            "downtime": [
                {
                    "id": int(item["id"]),
                    "process_line_id": int(item["process_line_id"]),
                    "start_at": str(item["start_at"]),
                    "end_at": str(item["end_at"]),
                    "reason": item.get("reason", "") or "",
                }
                for item in downtime
            ],
            "occupancy": [
                {
                    "process_line_id": int(item["process_line_id"]),
                    "start_at": str(item["start_at"]),
                    "end_at": str(item["end_at"]),
                    "schedule_id": int(item.get("schedule_id") or 0),
                }
                for item in occupancy
            ],
        }
        encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return snapshot, hashlib.sha256(encoded.encode("utf-8")).hexdigest()

