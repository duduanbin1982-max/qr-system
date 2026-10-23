"""Shared, persistence-independent planning stages for schedule generation.

The service layer resolves database facts into immutable DTOs.  This module
owns the deterministic work-time, candidate, capacity, blocked and lock
decisions for both initial generation and dynamic re-planning.  It deliberately
does not import Flask, repositories, services, or database modules.
"""

from __future__ import annotations

import json
import heapq
import math
from datetime import timedelta
from typing import Any, Mapping, Sequence

from modules.domain.production_node_scheduling import (
    NodeSchedulingError,
    ProductionNodePolicy,
)
from modules.domain.production_time import (
    format_database_timestamp,
    parse_database_timestamp,
    production_midnight,
)
from modules.domain.schedule_capacity_allocation import ScheduleCapacityAllocationPolicy
from modules.domain.schedule_standard_matching import ScheduleStandardMatchingPolicy
from modules.domain.schedule_planning import (
    PlanningDecision,
    PlanningFactsSnapshot,
    PlanningOperationFacts,
    PlanningOperationResult,
    PlanningResourceFacts,
    build_blocked_payload,
    build_completed_payload,
    build_external_payload,
    build_operation_context,
    decide_operation_planning,
    thaw_planning_value,
)


class SchedulePurePlanner:
    """Plan operations from one immutable snapshot and pre-resolved facts."""

    DEFAULT_DAILY_MINUTES = 540

    @staticmethod
    def _parse(value):
        return parse_database_timestamp(value)

    @staticmethod
    def _format(value):
        return format_database_timestamp(value)

    @staticmethod
    def _calendar_slots(
        resource: PlanningResourceFacts,
        earliest,
        daily_minutes=None,
        max_days=3660,
    ):
        calendar = resource.calendar
        shifts = resource.shifts
        weekly = {
            int(item.strip())
            for item in str(calendar.get("weekly_workdays") or "").split(",")
            if item.strip().isdigit()
        }
        shift_map = {int(shift["id"]): shift for shift in shifts}
        exceptions = {
            str(item.get("work_date")): item for item in resource.exceptions
        }
        for day_offset in range(max_days):
            work_date = earliest.date() + timedelta(days=day_offset)
            date_text = work_date.strftime("%Y-%m-%d")
            exception = exceptions.get(date_text)
            if exception is not None:
                if not int(exception.get("is_working_day") or 0):
                    continue
                selected_ids = [
                    int(item.strip())
                    for item in str(exception.get("shift_ids") or "").split(",")
                    if item.strip().isdigit()
                ]
                selected = [shift_map[item] for item in selected_ids if item in shift_map]
                selected = selected or list(shifts)
            elif (work_date.weekday() + 1) not in weekly:
                continue
            else:
                selected = list(shifts)
            daily_remaining = float(daily_minutes) if daily_minutes else None
            midnight = production_midnight(work_date)
            for shift in selected:
                if daily_remaining is not None and daily_remaining <= 0:
                    break
                begin = midnight + timedelta(minutes=int(shift["start_minute"]))
                end = midnight + timedelta(minutes=int(shift["end_minute"]))
                if daily_remaining is not None:
                    available = (end - begin).total_seconds() / 60
                    end = begin + timedelta(minutes=min(available, daily_remaining))
                    daily_remaining -= (end - begin).total_seconds() / 60
                if end <= begin:
                    continue
                yield {
                    "shift_id": shift["id"],
                    "shift_code": shift.get("shift_code", ""),
                    "shift_name": shift.get("shift_name", ""),
                    "start": begin,
                    "end": end,
                }

    @staticmethod
    def _calendar_snapshot(resource: PlanningResourceFacts) -> dict[str, Any]:
        calendar = resource.calendar
        return {
            "calendar_id": calendar.get("id"),
            "calendar_code": calendar.get("calendar_code", ""),
            "calendar_name": calendar.get("calendar_name", ""),
            "timezone": calendar.get("timezone", "Asia/Shanghai"),
            "weekly_workdays": calendar.get("weekly_workdays", ""),
            "shifts": [
                {
                    "id": shift.get("id"),
                    "code": shift.get("shift_code", ""),
                    "name": shift.get("shift_name", ""),
                    "start_minute": shift.get("start_minute"),
                    "end_minute": shift.get("end_minute"),
                }
                for shift in resource.shifts
            ],
        }

    @classmethod
    def _allocate_from_slots(cls, slots, earliest, duration, occupied):
        return ScheduleCapacityAllocationPolicy.allocate_from_slots(
            slots, earliest, duration, occupied, cls._format
        )

    @classmethod
    def _allocate_resource(cls, resource, earliest, duration, occupied):
        resource_row = dict(resource.resource)
        is_node = resource_row.get("production_node_id") is not None
        if is_node:
            if not resource.calendar or not resource.shifts:
                raise NodeSchedulingError(
                    "NODE_CALENDAR_UNAVAILABLE", "生产节点日历没有可用时间",
                    {"production_node_id": resource_row["id"]},
                )
            daily_minutes = sum(
                max(int(shift.get("end_minute") or 0) - int(shift.get("start_minute") or 0), 0)
                for shift in resource.shifts
            )
        else:
            daily_minutes = float(
                resource_row.get("daily_minutes")
                or resource_row.get("capacity_minutes")
                or cls.DEFAULT_DAILY_MINUTES
            )
        busy = list(occupied)
        overtime = []
        if is_node:
            for override in resource.overrides:
                start = cls._parse(override.get("start_at"))
                end = cls._parse(override.get("end_at"))
                if not start or not end or end <= start:
                    continue
                if override.get("override_type") == "overtime":
                    overtime.append({
                        "shift_id": None,
                        "shift_code": "OVERTIME",
                        "shift_name": "加班",
                        "start": start,
                        "end": end,
                    })
                else:
                    busy.append((start, end))
        slots = heapq.merge(
            cls._calendar_slots(resource, earliest, daily_minutes=daily_minutes),
            sorted(overtime, key=lambda item: (item["start"], item["end"])),
            key=lambda item: (item["start"], item["end"]),
        )

        def merged_slots():
            current = None
            for slot in slots:
                if current is None:
                    current = dict(slot)
                    continue
                if slot["start"] < current["end"]:
                    if slot["end"] > current["end"]:
                        tail = dict(slot)
                        tail["start"] = current["end"]
                        yield current
                        current = tail
                    continue
                yield current
                current = dict(slot)
            if current is not None:
                yield current

        segments = cls._allocate_from_slots(merged_slots(), earliest, duration, busy)
        if is_node:
            for segment in segments:
                segment["production_node_id"] = resource_row["id"]
                segment["process_line_id"] = resource_row.get("legacy_process_line_id")
        else:
            for segment in segments:
                segment["process_line_id"] = resource_row["id"]
        return segments

    @classmethod
    def _allocate_lines(cls, resources, earliest, quantity, standard, occupancy):
        remaining = max(int(quantity or 0), 0)
        if remaining <= 0:
            return []
        state = {
            int(resource.resource["id"]): {
                "resource": resource,
                "segments": [],
                "quantity": 0,
            }
            for resource in resources
            if resource.calendar and resource.shifts
        }
        if not state:
            raise ValueError("未配置有效工作日历或班次")
        while remaining > 0:
            available = []
            chunk = max(1, int(math.ceil(remaining / len(state))))
            for resource_id, item in state.items():
                include_setup = item["quantity"] == 0
                effective_standard = (
                    standard
                    if include_setup
                    else {**dict(standard), "setup_minutes": 0}
                )
                duration = ScheduleCapacityAllocationPolicy.duration_minutes(
                    chunk, effective_standard
                )
                try:
                    candidate = cls._allocate_resource(
                        item["resource"], earliest, duration,
                        occupancy.get(resource_id, []),
                    )
                except ValueError:
                    continue
                end = cls._parse(candidate[-1]["end_at"])
                available.append((end, resource_id, candidate, chunk))
            if not available:
                raise ValueError("工作日历在可搜索范围内没有足够产能")
            _, resource_id, segments, allocated = (
                ScheduleCapacityAllocationPolicy.choose_earliest_completion(available)
            )
            for index, segment in enumerate(segments):
                segment["quantity"] = allocated if index == 0 else 0
            state[resource_id]["segments"].extend(segments)
            state[resource_id]["quantity"] += allocated
            occupancy.setdefault(resource_id, []).extend(
                (cls._parse(item["start_at"]), cls._parse(item["end_at"]))
                for item in segments
            )
            remaining -= allocated
        return [segment for item in state.values() for segment in item["segments"]]

    @classmethod
    def _allocate_nodes(
        cls,
        resources,
        earliest,
        quantity,
        standard,
        occupancy,
        operation,
        order,
        serial_ids,
        allocation_key_prefix,
    ):
        def candidate_allocator(resource, requested_earliest, duration, additions):
            resource_id = int(resource.resource["id"])
            return cls._allocate_resource(
                resource,
                requested_earliest,
                duration,
                [*occupancy.get(resource_id, []), *additions],
            )

        try:
            result = ScheduleCapacityAllocationPolicy.allocate_split_on_nodes(
                nodes=[dict(resource.resource) for resource in resources],
                earliest=earliest,
                quantity=quantity,
                standard=standard,
                operation=operation,
                order=order,
                serial_ids=serial_ids,
                allocation_key_prefix=allocation_key_prefix,
                candidate_allocator=lambda node, requested_earliest, duration, additions: (
                    candidate_allocator(
                        next(
                            item
                            for item in resources
                            if int(item.resource["id"]) == int(node["id"])
                        ),
                        requested_earliest,
                        duration,
                        additions,
                    )
                ),
            )
        except (ValueError, NodeSchedulingError) as exc:
            for resource_id, intervals in getattr(
                exc, "capacity_occupancy_additions", {}
            ).items():
                occupancy.setdefault(resource_id, []).extend(intervals)
            raise
        for resource_id, intervals in result["occupancy_additions"].items():
            occupancy.setdefault(resource_id, []).extend(intervals)
        return result["segments"], result["allocations"]

    @staticmethod
    def _locked_task_segments(lock, payload):
        result = []
        for segment in payload.get("segments") or ():
            start_at = segment.get("start_at") or segment.get("segment_start_at")
            end_at = segment.get("end_at") or segment.get("segment_end_at")
            if not start_at or not end_at:
                continue
            result.append({
                "start_at": start_at,
                "end_at": end_at,
                "occupied_minutes": float(segment.get("occupied_minutes") or 0),
                "shift_id": segment.get("shift_id"),
                "quantity": int(segment.get("quantity") or 0),
                "production_node_id": segment.get("production_node_id") or lock.get("production_node_id"),
                "process_line_id": segment.get("process_line_id") or lock.get("process_line_id"),
            })
        if result:
            return result
        start = lock.get("planned_start_at")
        end = lock.get("planned_end_at")
        if not start or not end:
            return []
        return [{
            "start_at": start,
            "end_at": end,
            "occupied_minutes": float(lock.get("occupied_minutes") or 0),
            "shift_id": None,
            "quantity": int(lock.get("quantity") or 0),
            "production_node_id": lock.get("production_node_id"),
            "process_line_id": lock.get("process_line_id"),
        }]

    locked_task_segments = _locked_task_segments

    @staticmethod
    def _locked_task_allocations(payload):
        return [
            {
                "production_node_id": allocation.get("production_node_id"),
                "quantity": int(allocation.get("quantity") or 0),
                "serial_id": allocation.get("serial_id"),
                "batch_key": allocation.get("batch_key") or "",
                "changeover_minutes": float(allocation.get("changeover_minutes") or 0),
                "segment_start_at": allocation.get("segment_start_at") or allocation.get("allocation_start_at") or "",
                "segment_end_at": allocation.get("segment_end_at") or allocation.get("allocation_end_at") or "",
            }
            for allocation in payload.get("allocations") or ()
        ]

    locked_task_allocations = _locked_task_allocations

    @classmethod
    def _locked_conflict(cls, lock, downtime, overrides, cursor):
        start = cls._parse(lock.get("planned_start_at"))
        end = cls._parse(lock.get("planned_end_at"))
        node_id = lock.get("production_node_id")
        if not start or not end or end <= start:
            return {"reason": "锁定任务缺少有效的计划时间", "conflict_type": "invalid_locked_interval"}
        if cursor and start < cursor:
            return {"reason": "锁定任务早于前序工序完成时间", "conflict_type": "predecessor_overlap"}
        for event in downtime:
            if event.get("production_node_id") != node_id:
                continue
            event_start = cls._parse(event.get("start_at"))
            event_end = cls._parse(event.get("end_at"))
            if event_start and event_end and start < event_end and event_start < end:
                return {
                    "reason": "锁定任务与生产节点停机时段冲突",
                    "conflict_type": "downtime",
                    "downtime_event_id": event.get("id"),
                }
        for override in overrides:
            if override.get("override_type") == "overtime":
                continue
            override_start = cls._parse(override.get("start_at"))
            override_end = cls._parse(override.get("end_at"))
            if override_start and override_end and start < override_end and override_start < end:
                return {
                    "reason": "锁定任务与生产节点不可用时段冲突",
                    "conflict_type": override.get("override_type") or "unavailable",
                    "calendar_override_id": override.get("id"),
                }
        return None

    locked_conflict = _locked_conflict

    @classmethod
    def _restore_locked(cls, facts, context, cursor, use_node_engine):
        lock = dict(facts.locked_task)
        try:
            payload = json.loads(lock.get("payload_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            payload = {}
        segments = cls._locked_task_segments(lock, payload)
        allocations = cls._locked_task_allocations(payload)
        start = cls._parse(lock.get("planned_start_at"))
        end = cls._parse(lock.get("planned_end_at"))
        conflict = cls._locked_conflict(lock, facts.downtime, facts.locked_overrides, cursor)
        result = {
            **payload,
            **dict(context.common),
            "process_line_id": lock.get("process_line_id"),
            "production_node_id": lock.get("production_node_id"),
            "planned_start_at": lock.get("planned_start_at") or "",
            "planned_end_at": lock.get("planned_end_at") or "",
            "plan_start": start.strftime("%Y-%m-%d") if start else cursor.strftime("%Y-%m-%d"),
            "plan_end": end.strftime("%Y-%m-%d") if end else cursor.strftime("%Y-%m-%d"),
            "occupied_minutes": float(lock.get("occupied_minutes") or 0),
            "planned_minutes": float(payload.get("planned_minutes") or lock.get("occupied_minutes") or 0),
            "segments": segments,
            "allocations": allocations,
            "status": "blocked" if conflict else "planned",
            "blocked_reason": conflict["reason"] if conflict else "",
            "blocked_code": "LOCKED_TASK_CONFLICT" if conflict else "",
            "line_name": payload.get("line_name_snapshot") or None,
            "process_name": facts.operation.get("process_name_snapshot") or facts.operation.get("process_name") or "",
            "locked": True,
            "revision_item_id": None,
            "source_revision_item_id": lock.get("revision_item_id"),
            "requires_manual_unlock": bool(conflict),
            "reason": conflict["reason"] if conflict else "锁定任务保留原生产节点和计划时间",
        }
        if conflict:
            result.update({
                "code": "LOCKED_TASK_CONFLICT",
                "production_node_id": lock.get("production_node_id"),
                **conflict,
            })
        return result, conflict, end

    restore_locked_task = _restore_locked

    @classmethod
    def _planned_payload(
        cls, context, resources, segments, allocations, standard, use_node_engine,
    ):
        resource_key = "production_node_id" if use_node_engine else "process_line_id"
        resource_by_id = {int(item.resource["id"]): item for item in resources}
        resource_ids = sorted({int(item[resource_key]) for item in segments})
        primary_id = max(
            resource_ids,
            key=lambda resource_id: (
                sum(float(item.get("occupied_minutes") or 0) for item in segments if int(item[resource_key]) == resource_id),
                -resource_id,
            ),
        )
        snapshots = []
        for resource_id in resource_ids:
            item = resource_by_id[resource_id]
            row = thaw_planning_value(item.resource)
            calendar_snapshot = cls._calendar_snapshot(item)
            calendar_snapshot.update({
                resource_key: resource_id,
                "process_line_id": row.get("legacy_process_line_id", resource_id),
                "line_code": row.get("line_code", row.get("node_code", "")),
                "line_name": row.get("line_name", row.get("node_name", "")),
                "daily_minutes": float(row.get("daily_minutes") or row.get("capacity_minutes") or cls.DEFAULT_DAILY_MINUTES),
                "quantity": sum(int(segment.get("quantity") or 0) for segment in segments if int(segment[resource_key]) == resource_id),
            })
            if use_node_engine:
                calendar_snapshot.update({
                    "production_node_id": resource_id,
                    "node_code": row.get("node_code", ""),
                    "node_name": row.get("node_name", ""),
                    "capacity_mode": row.get("capacity_mode", "exclusive"),
                    "capabilities": row.get("capabilities", []),
                })
            snapshots.append(calendar_snapshot)
        primary = next(item for item in snapshots if int(item[resource_key]) == primary_id)
        primary_row = thaw_planning_value(resource_by_id[primary_id].resource)
        begin = min(cls._parse(item["start_at"]) for item in segments)
        end = max(cls._parse(item["end_at"]) for item in segments)
        total_duration = sum(float(item.get("occupied_minutes") or 0) for item in segments)
        return {
            **dict(context.common),
            "process_line_id": primary_row.get("legacy_process_line_id", primary_id) if use_node_engine else primary_id,
            "production_node_id": primary_id if use_node_engine else None,
            "node_code_snapshot": primary_row.get("node_code", "") if use_node_engine else "",
            "node_name_snapshot": primary_row.get("node_name", "") if use_node_engine else "",
            "capacity_mode_snapshot": primary_row.get("capacity_mode", "") if use_node_engine else "",
            "node_calendar_snapshot_json": json.dumps(primary, ensure_ascii=False, sort_keys=True) if use_node_engine else "{}",
            "node_capability_snapshot_json": json.dumps(primary_row.get("capabilities", []), ensure_ascii=False, sort_keys=True) if use_node_engine else "[]",
            "standard_id": standard["id"],
            "standard_version": standard["version"],
            "standard_minutes_per_unit": standard["standard_minutes_per_unit"],
            "setup_minutes": standard["setup_minutes"],
            "difficulty_factor": standard["difficulty_factor"],
            "planned_minutes": total_duration,
            "occupied_minutes": total_duration,
            "status": "planned",
            "standard_match_scope": standard["match_scope"],
            "planned_start_at": cls._format(begin),
            "planned_end_at": cls._format(end),
            "capacity_snapshot_json": json.dumps({
                **primary,
                "line_count": len(snapshots),
                "lines": snapshots,
                "node_count": len(snapshots) if use_node_engine else 0,
                "nodes": snapshots if use_node_engine else [],
            }, ensure_ascii=False, sort_keys=True),
            "shift_snapshot_json": json.dumps(
                [shift for item in snapshots for shift in item["shifts"]],
                ensure_ascii=False,
                sort_keys=True,
            ),
            "calendar_id": primary["calendar_id"],
            "line_name_snapshot": primary["line_name"],
            "segments": segments,
            "allocations": allocations,
            "plan_start": begin.strftime("%Y-%m-%d"),
            "plan_end": end.strftime("%Y-%m-%d"),
            "line_name": primary["line_name"],
            "line_count": len(snapshots),
            "lines": snapshots,
            "node_count": len(snapshots) if use_node_engine else 0,
            "nodes": snapshots if use_node_engine else [],
        }

    @staticmethod
    def _describe(payload, process_name):
        return {**payload, "line_name": payload.get("line_name"), "process_name": process_name, "reason": payload.get("reason", "")}

    @staticmethod
    def _completed_operation(item, context, mode):
        cursor = context.cursor
        previous = dict(item.previous)
        payload = build_completed_payload(
            context,
            standard_version=previous.get("standard_version"),
            standard_minutes_per_unit=previous.get("standard_minutes_per_unit") or 0,
            setup_minutes=previous.get("setup_minutes") or 0,
            difficulty_factor=previous.get("difficulty_factor") or 1,
            plan_start=previous.get("plan_start") or cursor.strftime("%Y-%m-%d"),
            plan_end=previous.get("plan_end") or cursor.strftime("%Y-%m-%d"),
            planned_start_at=(previous.get("planned_start_at") or "") if mode == "replan" else "",
            planned_end_at=(previous.get("planned_end_at") or "") if mode == "replan" else "",
            reason="已完成，无需重排" if mode == "replan" else "已完成，无剩余排程量",
            include_allocations=True,
        )
        return payload

    @classmethod
    def _select_standard_and_resources(cls, facts, item, context):
        order = dict(facts.order)
        operation = dict(item.operation)
        cursor = context.cursor
        standard = ScheduleStandardMatchingPolicy.select(
            item.standard_candidates,
            route_id=order.get("route_id"),
            route_version_id=operation.get("route_version_id") or order.get("route_version_id"),
            process_id=operation["process_id"],
            process_version_id=operation.get("process_version_id"),
            product_id=order.get("product_id"), product_code=order.get("product_code"),
            as_of_date=facts.standard_as_of,
        ) if item.standard_candidates else dict(item.standard or {})
        decision = decide_operation_planning(
            context, standard=standard, standard_resolved=True
        )
        if decision.disposition == "blocked":
            blocked = True
            payload = build_blocked_payload(
                context,
                cursor_date=cursor.strftime("%Y-%m-%d"),
                code=decision.blocked_code,
                reason=decision.blocked_reason,
            )
            return payload, None, None
        resources = tuple(resource for resource in item.resources if not facts.use_node_engine or ProductionNodePolicy.matches_capabilities(
            node=resource.resource, capabilities=resource.resource.get("capabilities", ()),
            operation=operation, order=order,
        ))
        decision = decide_operation_planning(
            context,
            standard=standard,
            standard_resolved=True,
            candidates=tuple(dict(resource.resource) for resource in resources),
            candidate_blocked_code="NO_COMPATIBLE_NODE",
            candidate_blocked_reason="没有满足能力要求的生产节点" if facts.use_node_engine else "工序未配置可用产线",
        )
        if decision.disposition == "blocked":
            blocked = True
            payload = build_blocked_payload(
                context,
                cursor_date=cursor.strftime("%Y-%m-%d"),
                code=decision.blocked_code,
                reason=decision.blocked_reason,
                standard=standard,
            )
            return payload, None, None
        return None, standard, resources

    @classmethod
    def _allocate_operation(cls, facts, item, context, standard, resources, occupancy):
        order = dict(facts.order)
        operation = dict(item.operation)
        cursor = context.cursor
        serial_ids = (
            facts.order_serial_ids
            if facts.order_serial_ids
            and len(facts.order_serial_ids) == item.remaining_quantity
            and item.remaining_quantity == int(order.get("quantity") or 0)
            else None
        )
        try:
            if facts.use_node_engine:
                segments, allocations = cls._allocate_nodes(
                    resources,
                    cursor,
                    item.remaining_quantity,
                    standard,
                    occupancy,
                    operation,
                    order,
                    serial_ids,
                    f"{order.get('id')}:{operation['order_process_id']}",
                )
            else:
                segments = cls._allocate_lines(
                    resources, cursor, item.remaining_quantity, standard, occupancy
                )
                allocations = []
        except NodeSchedulingError as exc:
            blocked = True
            payload = build_blocked_payload(
                context,
                cursor_date=cursor.strftime("%Y-%m-%d"),
                code=exc.code,
                reason=exc.message,
                standard=standard,
            )
            return payload
        except ValueError as exc:
            blocked = True
            payload = build_blocked_payload(
                context,
                cursor_date=cursor.strftime("%Y-%m-%d"),
                code="NODE_CALENDAR_UNAVAILABLE",
                reason=str(exc) or "未配置有效工作日历或班次",
                standard=standard,
            )
            return payload
        if not segments:
            blocked = True
            payload = build_blocked_payload(
                context,
                cursor_date=cursor.strftime("%Y-%m-%d"),
                code="NODE_CALENDAR_UNAVAILABLE",
                reason="生产节点未生成可用排程分段",
                standard=standard,
            )
            return payload
        payload = cls._planned_payload(
            context, resources, segments, allocations, standard, facts.use_node_engine
        )
        return payload

    @classmethod
    def _plan_operation(cls, facts, item, occupancy, cursor, blocked, *, run_key, run_id, revision_id, mode, source_fact_digest):
        order = dict(facts.order)
        conflicts = []
        operation = dict(item.operation)
        process_name = operation.get("process_name_snapshot") or operation.get("process_name") or ""
        context = build_operation_context(
            order=order,
            operation=operation,
            remaining_quantity=item.remaining_quantity,
            completed_quantity=item.completed_quantity,
            rework_quantity=item.rework_quantity,
            cursor=cursor,
            run_key=run_key,
            run_id=run_id,
            revision_id=revision_id,
            source_fact_digest=source_fact_digest,
        )
        if context.remaining_quantity <= 0:
            payload = cls._completed_operation(item, context, mode)
            return PlanningOperationResult(cls._describe(payload, process_name), (), blocked, cursor)
        lock = dict(item.locked_task)
        if facts.use_node_engine and lock:
            locked_result, lock_conflict, locked_end = cls._restore_locked(
                item, context, cursor, facts.use_node_engine
            )
            if lock_conflict:
                blocked = True
                conflicts.append({
                    "code": "LOCKED_TASK_CONFLICT",
                    "order_process_id": operation["order_process_id"],
                    "revision_item_id": locked_result.get("revision_item_id"),
                    "source_revision_item_id": locked_result.get("source_revision_item_id"),
                    "production_node_id": locked_result.get("production_node_id"),
                    "requires_manual_unlock": True,
                    **lock_conflict,
                })
            if locked_end:
                cursor = max(cursor, locked_end)
            return PlanningOperationResult(locked_result, tuple(conflicts), blocked, cursor)
        decision = decide_operation_planning(
            context,
            upstream_blocked=blocked,
            upstream_blocked_code="PREVIOUS_OPERATION_BLOCKED" if mode == "replan" else "UPSTREAM_BLOCKED",
            upstream_blocked_reason="前序工序无法重排" if mode == "replan" else "前序工序无法排程",
        )
        if decision.disposition == "blocked":
            payload = build_blocked_payload(
                context,
                cursor_date=cursor.strftime("%Y-%m-%d"),
                code=decision.blocked_code,
                reason=decision.blocked_reason,
            )
            return PlanningOperationResult(cls._describe(payload, process_name), (), blocked, cursor)
        decision = decide_operation_planning(
            context, execution_policy=item.execution_policy
        )
        if decision.disposition == "external":
            begin = cursor
            end = begin + timedelta(minutes=decision.external_lead_minutes)
            payload = build_external_payload(
                context,
                execution_mode=decision.execution_mode,
                lead_minutes=decision.external_lead_minutes,
                begin_at=cls._format(begin),
                end_at=cls._format(end),
                begin_date=begin.strftime("%Y-%m-%d"),
                end_date=end.strftime("%Y-%m-%d"),
            )
            cursor = end
            return PlanningOperationResult(cls._describe(payload, process_name), (), blocked, cursor)
        failure, standard, resources = cls._select_standard_and_resources(facts, item, context)
        if failure is not None:
            return PlanningOperationResult(cls._describe(failure, process_name), (), True, cursor)
        payload = cls._allocate_operation(facts, item, context, standard, resources, occupancy)
        if payload.get("status") == "blocked":
            return PlanningOperationResult(cls._describe(payload, process_name), (), True, cursor)
        return PlanningOperationResult({**payload, "process_name": process_name}, (), blocked, cls._parse(payload["planned_end_at"]))

    @classmethod
    def plan(
        cls,
        facts: PlanningFactsSnapshot,
        operation_facts: Sequence[PlanningOperationFacts],
        *,
        run_key: str,
        run_id: Any,
        revision_id: Any,
        mode: str = "generation",
        source_fact_digest: str = "",
    ) -> PlanningDecision:
        occupancy = {
            int(resource_id): list(intervals)
            for resource_id, intervals in facts.occupancy.items()
        }
        result = []
        conflicts = []
        blocked = False
        cursor = facts.cursor
        for item in operation_facts:
            step = cls._plan_operation(
                facts, item, occupancy, cursor, blocked, run_key=run_key, run_id=run_id,
                revision_id=revision_id, mode=mode, source_fact_digest=source_fact_digest,
            )
            result.append(thaw_planning_value(step.operation))
            conflicts.extend(thaw_planning_value(step.conflicts))
            blocked, cursor = step.blocked, step.cursor
        return PlanningDecision(
            operations=tuple(result),
            conflicts=tuple(conflicts),
            blocked=blocked,
            final_cursor=cursor,
        )


    calendar_slots = _calendar_slots
    calendar_snapshot = _calendar_snapshot
    allocate_from_slots = _allocate_from_slots
    allocate_resource = _allocate_resource
    allocate_lines = _allocate_lines
    allocate_nodes = _allocate_nodes


__all__ = ["SchedulePurePlanner"]
