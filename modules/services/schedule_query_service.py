"""Read models for scheduling; kept out of planning and transaction orchestration."""

import json
from collections import Counter

from modules.services import BaseService
from modules.domain.schedule_deadline_risk import ScheduleDeadlineRiskPolicy
from modules.repositories.schedule_evidence_repository import ScheduleEvidenceRepository
from modules.repositories.schedule_planning_repository import SchedulePlanningRepository
from modules.repositories.schedule_revision_repository import ScheduleRevisionRepository
from modules.services.schedule_planning_strategy import SchedulePlanningStrategy


class ScheduleQueryService:
    @staticmethod
    def limit(value, default=500):
        """Validate bounded query limits instead of silently truncating them."""
        if value is None:
            value = default
        try:
            value = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("limit必须是整数") from exc
        if value < 1 or value > 1000:
            raise ValueError("limit必须在1到1000之间")
        return value

    @staticmethod
    def list_lines(process_id=None, limit=500):
        limit = ScheduleQueryService.limit(limit)
        return {"lines": [dict(row) for row in SchedulePlanningRepository.list_process_lines(process_id, limit=limit)]}

    @staticmethod
    def list_calendars():
        return {"ok": True, "calendars": SchedulePlanningRepository.list_calendars()}

    @staticmethod
    def list_schedulable_orders(limit=500, now=None):
        limit = ScheduleQueryService.limit(limit)
        return {
            "ok": True,
            "orders": SchedulePlanningRepository.list_schedulable_orders(limit, now=now),
        }

    @staticmethod
    def list_order_schedule(order_id, limit=500):
        limit = ScheduleQueryService.limit(limit)
        return {"ok": True, "order_id": order_id, "operations": [dict(row) for row in SchedulePlanningRepository.find_order_operations(order_id, limit=limit)]}

    @staticmethod
    def list_order_revisions(order_id, limit=100):
        limit = ScheduleQueryService.limit(limit, default=100)
        return {
            "ok": True,
            "order_id": order_id,
            "revisions": [dict(row) for row in ScheduleRevisionRepository.list_revisions(order_id, limit=limit)],
        }

    @staticmethod
    def get_revision(revision_id, limit=1000):
        limit = ScheduleQueryService.limit(limit, default=1000)
        revision = ScheduleRevisionRepository.find_revision(revision_id)
        if revision is None:
            raise ValueError("排程版本不存在")
        conflict_assessment = SchedulePlanningStrategy.assess_revision_conflicts(
            revision_id, "detail", BaseService.db(), freeze_risk=False, persist=False
        )
        risk_assessment = ScheduleEvidenceRepository.find_revision_risk_assessment(
            revision_id
        )
        replan_summary, replan_differences = (
            ScheduleEvidenceRepository.get_replan_evidence(revision_id)
        )
        normalized_differences = []
        for row in replan_differences:
            item = dict(row)
            for field in ("before_json", "after_json"):
                try:
                    item[field.removesuffix("_json")] = json.loads(
                        item.get(field) or "{}"
                    )
                except (TypeError, json.JSONDecodeError):
                    item[field.removesuffix("_json")] = {}
            normalized_differences.append(item)
        return {
            "ok": True,
            "revision": dict(revision),
            "items": [dict(row) for row in ScheduleRevisionRepository.list_revision_items(revision_id, limit=limit)],
            "conflict_summary": conflict_assessment["summary"],
            "conflicts": conflict_assessment["conflicts"][:limit],
            "risk_assessment": dict(risk_assessment) if risk_assessment else None,
            "replan_summary": dict(replan_summary) if replan_summary else None,
            "replan_differences": normalized_differences[:limit],
        }

    @staticmethod
    def list_schedules(limit=500):
        limit = ScheduleQueryService.limit(limit)
        operations = [
            dict(row)
            for row in SchedulePlanningRepository.list_scheduled_operations(limit)
        ]
        for operation in operations:
            operation["candidate_revision"] = False
        candidate_operations = []
        for item in ScheduleRevisionRepository.list_latest_candidate_revision_items(
            limit=limit
        ):
            try:
                payload = json.loads(item["payload_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            candidate = dict(payload)
            candidate.update({
                "id": None,
                "order_id": item["order_id"],
                "order_no": item["order_no"],
                "product_name": item["product_name"],
                "process_name": item["process_name"],
                "schedule_revision_id": item["revision_id"],
                "revision_item_id": item["id"],
                "revision_item_row_version": item["row_version"],
                "revision_status": item["revision_status"],
                "revision_approval_status": item["revision_approval_status"],
                "risk_level": item["revision_risk_level"],
                "delay_minutes": item["revision_delay_minutes"],
                "risk_reason": item["revision_risk_reason"],
                "locked": bool(item["locked"]),
                "task_lock_id": item["task_lock_id"],
                "candidate_revision": True,
                "node_code": payload.get("node_code")
                or payload.get("node_code_snapshot")
                or "",
                "node_name": payload.get("node_name")
                or payload.get("node_name_snapshot")
                or "",
            })
            candidate_operations.append(candidate)
        if candidate_operations:
            candidate_keys = {
                (item.get("order_id"), item.get("order_process_id"))
                for item in candidate_operations
            }
            operations = [
                item for item in operations
                if (item.get("order_id"), item.get("order_process_id"))
                not in candidate_keys
            ] + candidate_operations
        allocations_by_schedule = {}
        for row in SchedulePlanningRepository.list_schedule_allocations(
            [operation.get("id") for operation in operations]
        ):
            allocation = dict(row)
            allocations_by_schedule.setdefault(allocation["schedule_id"], []).append(
                allocation
            )
        segments_by_schedule = {}
        for row in SchedulePlanningRepository.list_schedule_segments(
            [operation.get("id") for operation in operations]
        ):
            segment = dict(row)
            segments_by_schedule.setdefault(segment["schedule_id"], []).append(segment)
        for operation in operations:
            # V089 stores a legacy schedule-level ``locked`` flag and also
            # exposes the active revision-item lock through ``task_lock_id``.
            # SQLite rows keep the first duplicate column name from ``s.*``,
            # so normalize both sources here for old and versioned schedules.
            operation["locked"] = bool(
                operation.get("locked") or operation.get("task_lock_id")
            )
            if not operation.get("candidate_revision"):
                operation["allocations"] = allocations_by_schedule.get(
                    operation.get("id"), []
                )
                operation["segments"] = segments_by_schedule.get(
                    operation.get("id"), []
                )
        formal_conflicts = [
            dict(row) for row in ScheduleEvidenceRepository.list_schedule_conflicts()
        ]
        formal_by_schedule = {}
        for conflict in formal_conflicts:
            for key in ("first_schedule_id", "second_schedule_id"):
                schedule_id = conflict.get(key)
                if schedule_id not in (None, ""):
                    formal_by_schedule.setdefault(int(schedule_id), []).append(conflict)
        revision_conflicts = {}
        for revision_id in {
            int(operation["schedule_revision_id"])
            for operation in operations
            if operation.get("candidate_revision")
            and operation.get("schedule_revision_id") not in (None, "")
        }:
            revision_conflicts[revision_id] = [
                dict(row)
                for row in ScheduleEvidenceRepository.list_revision_conflicts(
                    revision_id
                )
            ]
        for operation in operations:
            if operation.get("candidate_revision"):
                conflicts = [
                    conflict
                    for conflict in revision_conflicts.get(
                        int(operation.get("schedule_revision_id") or 0), []
                    )
                    if operation.get("order_process_id") in {
                        conflict.get("first_order_process_id"),
                        conflict.get("second_order_process_id"),
                    }
                ]
            else:
                conflicts = formal_by_schedule.get(int(operation.get("id") or 0), [])
            operation["conflicts"] = conflicts
            operation["conflict_count"] = len(conflicts)
            operation["conflict_reason"] = (
                conflicts[0].get("reason") if conflicts else ""
            )
        return {"ok": True, "operations": operations}

    @staticmethod
    def audit_schedule_capacity(limit=1000, now=None):
        """Summarize persisted precision facts and detect line overlaps."""
        limit = ScheduleQueryService.limit(limit)
        rows = [dict(row) for row in SchedulePlanningRepository.list_scheduled_operations(limit)]
        planned = [row for row in rows if row.get("status") == "planned"]
        blocked = [row for row in rows if row.get("status") == "blocked"]
        conflicts = [dict(row) for row in ScheduleEvidenceRepository.list_schedule_conflicts()]
        conflicts_by_order = {}
        for conflict in conflicts:
            for key in ("first_order_id", "second_order_id"):
                order_id = conflict.get(key)
                if order_id not in (None, ""):
                    conflicts_by_order.setdefault(int(order_id), []).append(conflict)
        line_loads = [dict(row) for row in SchedulePlanningRepository.list_line_loads()]
        conflict_counts = Counter(row.get("process_line_id") for row in conflicts)
        for line in line_loads:
            line["conflict_count"] = conflict_counts.get(line.get("process_line_id"), 0)
        risk_orders = []
        risk_counts = Counter()
        for raw_row in ScheduleEvidenceRepository.list_schedule_risk_inputs(limit=limit):
            row = dict(raw_row)
            quantity = int(row.get("quantity") or 0)
            completed = int(row.get("completed") or 0)
            is_completed = row.get("order_status") == "completed" or (
                quantity > 0 and completed >= quantity
            )
            blocked_reasons = tuple(
                reason.strip()
                for reason in str(row.get("blocked_reasons") or "").split("；")
                if reason.strip()
            )
            risk = ScheduleDeadlineRiskPolicy.evaluate(
                deadline_text=row.get("deadline") or "",
                projected_completion_at=row.get("projected_completion_at") or "",
                plan_end=row.get("plan_end") or "",
                now=now,
                completed=is_completed,
                blocked_count=row.get("blocked_count") or 0,
                blocked_reasons=blocked_reasons,
                conflict_count=row.get("conflict_count") or 0,
                conflict_details=conflicts_by_order.get(int(row["order_id"]), ()),
            )
            risk_counts[risk["level"]] += 1
            if risk["level"] in ("high", "overdue"):
                risk_orders.append({
                    "order_id": row["order_id"],
                    "order_no": row["order_no"],
                    "risk_level": risk["level"],
                    "risk_reason": risk["reason"],
                    "delay_minutes": risk["delay_minutes"],
                    "slack_minutes": risk["slack_minutes"],
                    "deadline_at": risk["deadline_at"],
                    "projected_completion_at": risk["projected_completion_at"],
                    "primary_risk_source": risk.get("primary_source", ""),
                    "suggested_actions": risk.get("suggested_actions", []),
                })
        risk_orders.sort(
            key=lambda item: (
                0 if item["risk_level"] == "overdue" else 1,
                -int(item["delay_minutes"] or 0),
                item["order_no"] or "",
            )
        )
        delay_values = [int(item["delay_minutes"] or 0) for item in risk_orders]
        match_scope_counts = Counter(
            row.get("standard_match_scope") or "未匹配"
            for row in planned
        )
        blocked_reason_counts = Counter(
            row.get("blocked_reason") or "未说明"
            for row in blocked
        )
        return {
            "ok": True,
            "limit": limit,
            "operations": len(rows),
            "planned_operations": len(planned),
            "blocked_operations": len(blocked),
            "precision_operations": sum(1 for row in planned if row.get("planned_start_at")),
            "occupied_minutes": round(sum(float(row.get("occupied_minutes") or 0) for row in planned), 2),
            "match_scope_counts": dict(sorted(match_scope_counts.items())),
            "blocked_reason_counts": dict(sorted(blocked_reason_counts.items())),
            "risk_counts": dict(sorted(risk_counts.items())),
            "risk_orders": risk_orders[:limit],
            "risk_order_count": len(risk_orders),
            "delayed_order_count": sum(1 for item in risk_orders if item["delay_minutes"] > 0),
            "total_delay_minutes": sum(delay_values),
            "max_delay_minutes": max(delay_values, default=0),
            "line_conflicts": len(conflicts),
            "node_conflicts": len(conflicts),
            "conflicts": conflicts[:limit],
            "line_loads": line_loads,
            "calendars": SchedulePlanningRepository.list_calendars(),
            "capacity_unavailability": [
                dict(row)
                for row in SchedulePlanningRepository.list_capacity_unavailability()
            ],
            "capacity_overrides": [
                dict(row)
                for row in SchedulePlanningRepository.list_capacity_overrides()
            ],
        }
