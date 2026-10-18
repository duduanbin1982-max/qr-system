"""Pure conflict and deadline-risk stages over immutable planning facts."""

from modules.domain.schedule_conflict import ScheduleConflictPolicy
from modules.domain.schedule_deadline_risk import ScheduleDeadlineRiskPolicy


class SchedulePlanningAssessment:
    @staticmethod
    def candidate_capacity_intervals(operations):
        intervals = []
        for operation in operations:
            if operation.get("status") == "blocked":
                continue
            if operation.get("execution_mode", "internal") in {
                "outsourced", "non_scheduled",
            }:
                continue
            segments = operation.get("segments") or []
            if not segments:
                segments = [{
                    "production_node_id": operation.get("production_node_id"),
                    "process_line_id": operation.get("process_line_id"),
                    "start_at": operation.get("planned_start_at"),
                    "end_at": operation.get("planned_end_at"),
                }]
            for segment in segments:
                intervals.append({
                    "order_id": operation.get("order_id"),
                    "order_process_id": operation.get("order_process_id"),
                    "process_id": operation.get("process_id"),
                    "process_name": operation.get("process_name") or "",
                    "revision_item_id": operation.get("revision_item_id"),
                    "schedule_id": operation.get("id"),
                    "production_node_id": segment.get("production_node_id") or operation.get("production_node_id"),
                    "process_line_id": segment.get("process_line_id") or operation.get("process_line_id"),
                    "node_name": operation.get("node_name") or operation.get("node_name_snapshot") or "",
                    "capacity_mode": operation.get("capacity_mode") or operation.get("capacity_mode_snapshot") or "exclusive",
                    "start_at": segment.get("start_at") or segment.get("segment_start_at") or operation.get("planned_start_at"),
                    "end_at": segment.get("end_at") or segment.get("segment_end_at") or operation.get("planned_end_at"),
                    "locked": bool(operation.get("locked")),
                })
        return intervals

    @staticmethod
    def assess(facts):
        order = facts.order
        operations = facts.operations
        conflicts = ScheduleConflictPolicy.detect(
            candidate_intervals=facts.candidate_intervals,
            occupied_intervals=facts.occupied_intervals,
            unavailable_intervals=facts.unavailable_intervals,
            operations=operations,
        )
        summary = ScheduleConflictPolicy.summarize(conflicts)
        return {"summary": summary, "conflicts": conflicts}

    @staticmethod
    def deadline_risk(facts, conflicts, summary):
        order = facts.order
        operations = facts.operations
        planned = [
            operation for operation in operations
            if operation.get("status") != "blocked"
        ]
        projected_values = [
            str(operation.get("planned_end_at") or "").strip()
            for operation in planned
            if str(operation.get("planned_end_at") or "").strip()
        ]
        projected_completion = max(projected_values, default="")
        blocked = [
            operation for operation in operations
            if operation.get("status") == "blocked"
        ]
        blocked_reasons = tuple(
            str(
                operation.get("blocked_reason")
                or operation.get("reason")
                or "前置条件不满足"
            ).strip()
            for operation in blocked
        )
        bottleneck = max(
            planned,
            key=lambda operation: float(operation.get("occupied_minutes") or 0),
            default={},
        )
        quantity = int(order.get("quantity") or 0)
        completed = int(order.get("completed") or 0)
        is_completed = order.get("order_status") == "completed" or (
            quantity > 0 and completed >= quantity
        )
        risk = ScheduleDeadlineRiskPolicy.evaluate(
            deadline_text=order.get("deadline") or "",
            projected_completion_at=projected_completion,
            plan_end=order.get("plan_end") or "",
            now=facts.now,
            completed=is_completed,
            blocked_count=len(blocked),
            blocked_reasons=blocked_reasons,
            conflict_count=summary["blocking_count"],
            conflict_details=conflicts,
            bottleneck_process=bottleneck.get("process_name") or "",
            bottleneck_node=(
                bottleneck.get("node_name")
                or bottleneck.get("node_name_snapshot")
                or ""
            ),
        )
        return risk, len(planned)
