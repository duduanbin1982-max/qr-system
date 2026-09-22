"""Pure policies for deriving a dynamic schedule from production facts.

The policy deliberately knows nothing about SQLite or Flask.  It turns the
current production facts into a deterministic, auditable replan input:
completed output is subtracted, open rework is added back, and downtime is
kept as a separate immutable source fact.
"""

import hashlib
import json
from datetime import datetime


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
        completed = max(
            cls._non_negative_int(operation.get("completed_quantity")),
            cls._non_negative_int(operation.get("approved_report_quantity")),
        )
        rework = cls._non_negative_int(operation.get("rework_quantity"))
        scrapped = cls._non_negative_int(operation.get("scrapped_quantity"))
        remaining = max(quantity - completed, 0) + rework
        return {
            "order_process_id": int(operation["order_process_id"]),
            "process_id": int(operation["process_id"]),
            "seq_order": int(operation.get("seq_order") or 0),
            "order_quantity": quantity,
            "completed_quantity": completed,
            "scrapped_quantity": scrapped,
            "rework_quantity": rework,
            "remaining_quantity": remaining,
            "status": "completed" if remaining == 0 else "pending",
        }

    @classmethod
    def build_input_snapshot(cls, *, order, operations, downtime, occupancy, reason, as_of,
                             locked_tasks=None, work_reports=None, scrap_records=None,
                             rework_records=None, current_revision=None,
                             current_revision_items=None, replan_triggers=None):
        baselines = [cls.operation_baseline(item) for item in operations]
        snapshot = {
            "order_id": int(order["id"]),
            "order_quantity": cls._non_negative_int(order.get("quantity")),
            "order_completed": cls._non_negative_int(order.get("completed")),
            "as_of": as_of or "",
            "reason": reason or "",
            "operations": baselines,
            "work_reports": [cls._execution_fact(item) for item in (work_reports or ())],
            "scrap_records": [cls._execution_fact(item) for item in (scrap_records or ())],
            "rework_records": [cls._execution_fact(item) for item in (rework_records or ())],
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
            "current_revision": cls._revision_fact(current_revision),
            "current_revision_items": [
                cls._revision_item_fact(item) for item in (current_revision_items or ())
            ],
            "replan_triggers": [
                cls._trigger_fact(item) for item in (replan_triggers or ())
            ],
        }
        encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return snapshot, hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @classmethod
    def _execution_fact(cls, item):
        fact = {
            "id": cls._non_negative_int(item.get("id")),
            "order_process_id": cls._non_negative_int(item.get("order_process_id")),
            "process_id": cls._non_negative_int(item.get("process_id")),
            "quantity": cls._non_negative_int(item.get("quantity")),
            "status": str(item.get("status") or ""),
            "created_at": str(item.get("created_at") or ""),
        }
        for key in (
            "type", "serial_no", "actual_completed_at", "completed_at",
            "result", "source_ncr_id",
        ):
            value = item.get(key)
            if value not in (None, ""):
                fact[key] = value
        return fact

    @staticmethod
    def _revision_fact(item):
        if not item:
            return {}
        return {
            "id": int(item.get("id") or 0),
            "revision_no": int(item.get("revision_no") or 0),
            "status": str(item.get("status") or ""),
            "approval_status": str(item.get("approval_status") or ""),
            "risk_level": str(item.get("risk_level") or "none"),
            "delay_minutes": int(item.get("delay_minutes") or 0),
            "content_digest": str(item.get("content_digest") or ""),
        }

    @classmethod
    def _revision_item_fact(cls, item):
        normalized = cls._normalized_item(item)
        return {
            key: normalized[key]
            for key in (
                "order_process_id", "process_id", "production_node_id",
                "quantity", "status", "planned_start_at", "planned_end_at",
                "occupied_minutes", "completed_quantity_snapshot",
                "rework_quantity_snapshot", "remaining_quantity_snapshot",
            )
        }

    @classmethod
    def _trigger_fact(cls, item):
        return {
            "id": cls._non_negative_int(item.get("id")),
            "trigger_type": str(item.get("trigger_type") or ""),
            "source_type": str(item.get("source_type") or ""),
            "source_id": item.get("source_id"),
            "reason": str(item.get("reason") or ""),
            "fact_digest": str(item.get("fact_digest") or ""),
            "created_at": str(item.get("created_at") or ""),
        }

    @staticmethod
    def _parse_payload(item):
        payload = item.get("payload_json") if item else None
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, str) and payload:
            try:
                decoded = json.loads(payload)
            except json.JSONDecodeError:
                return {}
            return decoded if isinstance(decoded, dict) else {}
        return {}

    @classmethod
    def _normalized_item(cls, item):
        source = dict(item or {})
        payload = cls._parse_payload(source)

        def value(key, default=None):
            direct = source.get(key)
            if direct not in (None, ""):
                return direct
            return payload.get(key, default)

        return {
            "order_process_id": cls._non_negative_int(value("order_process_id")),
            "process_id": cls._non_negative_int(value("process_id")),
            "production_node_id": value("production_node_id"),
            "quantity": cls._non_negative_int(value("quantity")),
            "status": str(value("status", "") or ""),
            "planned_start_at": str(value("planned_start_at", "") or ""),
            "planned_end_at": str(value("planned_end_at", "") or ""),
            "occupied_minutes": float(value("occupied_minutes", 0) or 0),
            "completed_quantity_snapshot": cls._non_negative_int(
                value("completed_quantity_snapshot")
            ),
            "rework_quantity_snapshot": cls._non_negative_int(
                value("rework_quantity_snapshot")
            ),
            "remaining_quantity_snapshot": cls._non_negative_int(
                value("remaining_quantity_snapshot", value("quantity", 0))
            ),
        }

    @staticmethod
    def _minute_delta(before, after):
        if not before or not after:
            return 0
        try:
            before_dt = datetime.fromisoformat(str(before).replace("T", " "))
            after_dt = datetime.fromisoformat(str(after).replace("T", " "))
        except (TypeError, ValueError):
            return 0
        return int(round((after_dt - before_dt).total_seconds() / 60))

    @classmethod
    def build_differences(cls, before_items, after_items):
        before_by_operation = {
            cls._normalized_item(item)["order_process_id"]: cls._normalized_item(item)
            for item in (before_items or ())
        }
        after_by_operation = {
            cls._normalized_item(item)["order_process_id"]: cls._normalized_item(item)
            for item in (after_items or ())
        }
        differences = []
        for operation_id in sorted(set(before_by_operation) | set(after_by_operation)):
            before = before_by_operation.get(operation_id, {})
            after = after_by_operation.get(operation_id, {})
            categories = []
            if not before:
                categories.append("added")
            elif not after:
                categories.append("removed")
            else:
                if before.get("status") != after.get("status"):
                    categories.append(
                        "completed" if after.get("status") == "completed" else "blocked"
                        if after.get("status") == "blocked" else "multiple"
                    )
                if before.get("quantity") != after.get("quantity"):
                    categories.append("quantity")
                if before.get("production_node_id") != after.get("production_node_id"):
                    categories.append("node")
                if (
                    before.get("planned_start_at") != after.get("planned_start_at")
                    or before.get("planned_end_at") != after.get("planned_end_at")
                ):
                    categories.append("time")
                if before.get("occupied_minutes") != after.get("occupied_minutes"):
                    categories.append("capacity")
            distinct = list(dict.fromkeys(categories))
            change_type = distinct[0] if len(distinct) == 1 else "multiple" if distinct else "unchanged"
            evidence = {
                "order_process_id": operation_id,
                "before": before,
                "after": after,
                "change_type": change_type,
            }
            encoded = json.dumps(
                evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            differences.append({
                "order_process_id": operation_id,
                "process_id": int(after.get("process_id") or before.get("process_id") or 0),
                "change_type": change_type,
                "node_changed": int(
                    before.get("production_node_id") != after.get("production_node_id")
                ),
                "quantity_delta": int(after.get("quantity") or 0) - int(before.get("quantity") or 0),
                "occupied_minutes_delta": round(
                    float(after.get("occupied_minutes") or 0)
                    - float(before.get("occupied_minutes") or 0), 3
                ),
                "start_delta_minutes": cls._minute_delta(
                    before.get("planned_start_at"), after.get("planned_start_at")
                ),
                "end_delta_minutes": cls._minute_delta(
                    before.get("planned_end_at"), after.get("planned_end_at")
                ),
                "before": before,
                "after": after,
                "evidence_digest": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
            })
        return differences

    @staticmethod
    def risk_change(before_risk, after_risk):
        order = {"none": 0, "low": 1, "medium": 2, "high": 3, "overdue": 4}
        before_level = str((before_risk or {}).get("risk_level") or "none")
        after_level = str((after_risk or {}).get("risk_level") or "none")
        before_delay = int((before_risk or {}).get("delay_minutes") or 0)
        after_delay = int((after_risk or {}).get("delay_minutes") or 0)
        before_key = (order.get(before_level, 0), before_delay)
        after_key = (order.get(after_level, 0), after_delay)
        if after_key < before_key:
            return "improved"
        if after_key > before_key:
            return "worsened"
        return "unchanged"

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
