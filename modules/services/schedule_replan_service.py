"""Dynamic replan orchestration for production scheduling.

The service keeps production facts, lock recovery, planning, risk comparison,
and evidence persistence in one transaction while delegating capacity
primitives to ScheduleCapacityService.
"""

import hashlib
import json
from datetime import datetime, timedelta

from modules import config
from modules.domain.production_node_scheduling import NodeSchedulingError
from modules.domain.schedule_dynamic_replan import ScheduleDynamicReplanPolicy
from modules.repositories.production_node_repository import ProductionNodeRepository
from modules.repositories.schedule_capacity_repository import ScheduleCapacityRepository


class ScheduleReplanService:
    @staticmethod
    def _replan_start(value):
        if not value:
            return datetime.now().replace(second=0, microsecond=0)
        text = str(value).strip().replace("T", " ")
        try:
            if len(text) == 10:
                return datetime.strptime(text, "%Y-%m-%d")
            parsed = datetime.fromisoformat(text)
            # SQLite stores local production timestamps without offsets.  Keep
            # the supplied wall-clock value when a client sends an ISO offset
            # so aware/naive datetime comparisons cannot mix silently.
            return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
        except ValueError as exc:
            raise ValueError("重排开始时间必须使用 YYYY-MM-DD 或 YYYY-MM-DD HH:MM 格式") from exc

    @staticmethod
    def _add_downtime_to_occupancy(occupancy, downtime, resource_key="process_line_id", capacity_service=None):
        if capacity_service is None:
            raise ValueError("动态重排必须由容量服务提供时间解析器")
        for event in downtime:
            event = dict(event)
            start = capacity_service._parse_timestamp(event.get("start_at"))
            end = capacity_service._parse_timestamp(event.get("end_at"))
            resource_id = event.get(resource_key)
            if resource_id is None or not start or not end or end <= start:
                continue
            occupancy.setdefault(int(resource_id), []).append((start, end))

    @staticmethod
    def _latest_locks_by_operation(active_locks):
        """Collapse copied locks to the newest immutable revision per operation."""
        result = {}
        for row in active_locks:
            lock = dict(row)
            operation_id = int(lock["order_process_id"])
            result.setdefault(operation_id, lock)
        return result

    @staticmethod
    def _locked_task_segments(lock, payload):
        """Normalize immutable revision segments back to scheduler payload shape."""
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
                "production_node_id": (
                    segment.get("production_node_id") or lock.get("production_node_id")
                ),
                "process_line_id": (
                    segment.get("process_line_id") or lock.get("process_line_id")
                ),
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

    @staticmethod
    def _locked_task_allocations(payload):
        result = []
        for allocation in payload.get("allocations") or ():
            result.append({
                "production_node_id": allocation.get("production_node_id"),
                "quantity": int(allocation.get("quantity") or 0),
                "serial_id": allocation.get("serial_id"),
                "batch_key": allocation.get("batch_key") or "",
                "changeover_minutes": float(allocation.get("changeover_minutes") or 0),
                "segment_start_at": (
                    allocation.get("segment_start_at")
                    or allocation.get("allocation_start_at")
                    or ""
                ),
                "segment_end_at": (
                    allocation.get("segment_end_at")
                    or allocation.get("allocation_end_at")
                    or ""
                ),
            })
        return result

    @staticmethod
    def _locked_task_conflict(lock, downtime, cursor, db, capacity_service):
        """Return an immutable conflict fact without moving the locked task."""
        start = capacity_service._parse_timestamp(lock.get("planned_start_at"))
        end = capacity_service._parse_timestamp(lock.get("planned_end_at"))
        node_id = lock.get("production_node_id")
        if not start or not end or end <= start:
            return {
                "reason": "锁定任务缺少有效的计划时间",
                "conflict_type": "invalid_locked_interval",
            }
        if cursor and start < cursor:
            return {
                "reason": "锁定任务早于前序工序完成时间",
                "conflict_type": "predecessor_overlap",
            }
        for event in downtime:
            event = dict(event)
            if event.get("production_node_id") != node_id:
                continue
            event_start = capacity_service._parse_timestamp(event.get("start_at"))
            event_end = capacity_service._parse_timestamp(event.get("end_at"))
            if event_start and event_end and start < event_end and event_start < end:
                return {
                    "reason": "锁定任务与生产节点停机时段冲突",
                    "conflict_type": "downtime",
                    "downtime_event_id": event.get("id"),
                }
        for override in ProductionNodeRepository.list_node_calendar_overrides(
            node_id, db=db
        ):
            override = dict(override)
            if override.get("override_type") == "overtime":
                continue
            override_start = capacity_service._parse_timestamp(
                override.get("start_at")
            )
            override_end = capacity_service._parse_timestamp(
                override.get("end_at")
            )
            if (
                override_start and override_end
                and start < override_end and override_start < end
            ):
                return {
                    "reason": "锁定任务与生产节点不可用时段冲突",
                    "conflict_type": override.get("override_type") or "unavailable",
                    "calendar_override_id": override.get("id"),
                }
        return None

    @staticmethod
    def _copy_active_lock_to_schedule(lock, schedule_id, revision_id, db):
        item = ScheduleCapacityRepository.find_revision_item_by_source_schedule(
            revision_id, schedule_id, db=db
        )
        if item is None:
            raise ValueError("新排程版本缺少锁定任务快照")
        ScheduleCapacityRepository.create_task_lock(
            item["id"], lock["production_node_id"], lock["locked_by"],
            lock.get("reason") or "动态重排保留锁定任务", db
        )
        return dict(item)

    @staticmethod
    def _prepare_request(start_at, schedule_run_key, reason, capacity_service):
        """Validate and normalize the dynamic replan request."""
        start = ScheduleReplanService._replan_start(start_at)
        standard_as_of = start.strftime("%Y-%m-%d")
        reason = str(reason or "").strip()
        if len(reason) > 512:
            raise ValueError("重排原因不能超过 512 个字符")
        run_key = str(schedule_run_key or "").strip()
        if not run_key:
            raise ValueError("排程幂等键不能为空")
        return {
            "start": start,
            "standard_as_of": standard_as_of,
            "reason": reason,
            "run_key": run_key,
        }

    @staticmethod
    def _load_replan_facts(order_id, txn, use_node_engine):
        """Load immutable production facts used by one replan attempt."""
        active_lock_rows = ScheduleCapacityRepository.list_active_order_task_locks(
            order_id, db=txn
        )
        if active_lock_rows and not use_node_engine:
            raise NodeSchedulingError(
                "LOCKED_TASK_CONFLICT",
                "Legacy 排程引擎不能保留生产节点锁定任务",
                {
                    "order_id": order_id,
                    "revision_item_ids": [
                        row["revision_item_id"] for row in active_lock_rows
                    ],
                },
            )
        active_locks = ScheduleReplanService._latest_locks_by_operation(
            active_lock_rows
        )
        # Resolve legacy orders to immutable route/process bindings before any
        # revision fact is written.
        if not ScheduleCapacityRepository.ensure_order_version_bindings(order_id, txn):
            raise ValueError("订单不存在")
        context = ScheduleCapacityRepository.dynamic_replan_order_context(
            order_id, db=txn, use_nodes=use_node_engine
        )
        if not context:
            raise ValueError("订单不存在")
        return {
            "context": context,
            "order": context["order"],
            "active_locks": active_locks,
            "order_serial_ids": ScheduleCapacityRepository.list_order_serial_ids(
                order_id, db=txn
            ),
        }

    @staticmethod
    def _replay_existing_run(order_id, run_key, prior_run, txn):
        """Return the immutable result for a previously completed/failed run."""
        if not prior_run:
            return None
        if prior_run["order_id"] != order_id:
            raise ValueError("排程幂等键已被其他订单使用")
        revision = ScheduleCapacityRepository.find_revision_by_run(
            prior_run["id"], db=txn
        )
        replay_operations = ScheduleCapacityRepository.run_result(prior_run)
        evidence_summary = None
        evidence_differences = []
        if revision:
            stored_summary, stored_differences = (
                ScheduleCapacityRepository.get_replan_evidence(
                    revision["id"], db=txn
                )
            )
            evidence_summary = dict(stored_summary) if stored_summary else None
            evidence_differences = [dict(item) for item in stored_differences]
        return {
            "ok": prior_run["status"] == "completed",
            "order_id": order_id,
            "schedule_run_key": run_key,
            "idempotent_replay": True,
            "status": prior_run["status"],
            "error": prior_run["error_message"] or "",
            "input_digest": (
                prior_run["input_digest"]
                if "input_digest" in prior_run.keys()
                else ""
            ),
            "schedule_revision_id": revision["id"] if revision else None,
            "revision_status": revision["status"] if revision else None,
            "operations": replay_operations,
            "conflicts": [
                {
                    key: item.get(key)
                    for key in (
                        "code",
                        "revision_item_id",
                        "source_revision_item_id",
                        "production_node_id",
                        "requires_manual_unlock",
                        "reason",
                        "conflict_type",
                        "downtime_event_id",
                        "calendar_override_id",
                    )
                    if item.get(key) is not None
                }
                for item in replay_operations
                if item.get("code") == "LOCKED_TASK_CONFLICT"
            ],
            "replan_summary": evidence_summary,
            "differences": evidence_differences,
        }

    @staticmethod
    def _create_replan_ledger(
        order_id,
        request,
        facts,
        run_key,
        actor_id,
        txn,
        capacity_service,
    ):
        """Create the run/revision ledger before entering the savepoint."""
        context = facts["context"]
        order = facts["order"]
        active_locks = facts["active_locks"]
        snapshot, input_digest = ScheduleDynamicReplanPolicy.build_input_snapshot(
            order=order,
            operations=context["operations"],
            downtime=context["downtime"],
            occupancy=context["occupancy"],
            reason=request["reason"],
            as_of=capacity_service._format_timestamp(request["start"]),
            locked_tasks=list(active_locks.values()),
            work_reports=context["work_reports"],
            scrap_records=context["scrap_records"],
            rework_records=context["rework_records"],
            current_revision=context["current_revision"],
            current_revision_items=context["current_revision_items"],
            replan_triggers=context["replan_triggers"],
        )
        run_id = ScheduleCapacityRepository.create_run(
            order_id,
            run_key,
            request["start"].strftime("%Y-%m-%d"),
            txn,
            run_type="dynamic_replan",
            trigger_source="production_facts",
            input_digest=input_digest,
            replan_reason=request["reason"],
        )
        revision_id = ScheduleCapacityRepository.create_revision(
            order_id,
            run_id,
            run_key,
            txn,
            created_by=actor_id,
            replan_reason=request["reason"],
            replan_source_digest=input_digest,
            replanned_at=capacity_service._format_timestamp(request["start"]),
        )
        return {
            "snapshot": snapshot,
            "input_digest": input_digest,
            "run_id": run_id,
            "revision_id": revision_id,
        }

    @staticmethod
    def _load_replan_occupancy(
        order_id, context, active_locks, use_node_engine, txn, capacity_service
    ):
        """Reset the projection and load occupancy/downtime/lock constraints."""
        ScheduleCapacityRepository.clear_order_schedules(order_id, txn)
        occupancy = {}
        occupancy_rows = (
            ProductionNodeRepository.list_node_occupancy(order_id, db=txn)
            if use_node_engine
            else ScheduleCapacityRepository.list_line_occupancy(order_id, txn)
        )
        occupancy_key = "production_node_id" if use_node_engine else "process_line_id"
        for row in occupancy_rows:
            begin = capacity_service._parse_timestamp(row["start_at"])
            end = capacity_service._parse_timestamp(row["end_at"])
            resource_id = row[occupancy_key]
            if resource_id is not None and begin and end and end > begin:
                occupancy.setdefault(int(resource_id), []).append((begin, end))
        ScheduleReplanService._add_downtime_to_occupancy(
            occupancy,
            context["downtime"],
            resource_key=occupancy_key,
            capacity_service=capacity_service,
        )
        if use_node_engine:
            for lock in active_locks.values():
                lock_start = capacity_service._parse_timestamp(
                    lock.get("planned_start_at")
                )
                lock_end = capacity_service._parse_timestamp(
                    lock.get("planned_end_at")
                )
                node_id = lock.get("production_node_id")
                if (
                    node_id is not None
                    and lock_start
                    and lock_end
                    and lock_end > lock_start
                ):
                    occupancy.setdefault(int(node_id), []).append(
                        (lock_start, lock_end)
                    )
        return occupancy

    @staticmethod
    def _restore_locked_task(
        *,
        operation,
        common,
        locked_task,
        context,
        cursor,
        revision_id,
        txn,
        capacity_service,
    ):
        """Restore a locked task without moving its immutable interval."""
        try:
            locked_payload = json.loads(locked_task.get("payload_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            locked_payload = {}
        segments = ScheduleReplanService._locked_task_segments(
            locked_task, locked_payload
        )
        allocations = ScheduleReplanService._locked_task_allocations(
            locked_payload
        )
        locked_start = capacity_service._parse_timestamp(
            locked_task.get("planned_start_at")
        )
        locked_end = capacity_service._parse_timestamp(
            locked_task.get("planned_end_at")
        )
        conflict = ScheduleReplanService._locked_task_conflict(
            locked_task,
            context["downtime"],
            cursor,
            txn,
            capacity_service,
        )
        payload = {
            **locked_payload,
            **common,
            "process_line_id": locked_task.get("process_line_id"),
            "production_node_id": locked_task.get("production_node_id"),
            "planned_start_at": locked_task.get("planned_start_at") or "",
            "planned_end_at": locked_task.get("planned_end_at") or "",
            "plan_start": (
                locked_start.strftime("%Y-%m-%d")
                if locked_start
                else cursor.strftime("%Y-%m-%d")
            ),
            "plan_end": (
                locked_end.strftime("%Y-%m-%d")
                if locked_end
                else cursor.strftime("%Y-%m-%d")
            ),
            "occupied_minutes": float(locked_task.get("occupied_minutes") or 0),
            "planned_minutes": float(
                locked_payload.get("planned_minutes")
                or locked_task.get("occupied_minutes")
                or 0
            ),
            "segments": segments,
            "allocations": allocations,
            "status": "blocked" if conflict else "planned",
            "blocked_reason": conflict["reason"] if conflict else "",
            "blocked_code": "LOCKED_TASK_CONFLICT" if conflict else "",
        }
        payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(
            payload, txn
        )
        new_item = ScheduleReplanService._copy_active_lock_to_schedule(
            locked_task, payload["id"], revision_id, txn
        )
        locked_result = {
            **payload,
            "line_name": payload.get("line_name_snapshot") or None,
            "process_name": operation.get("process_name_snapshot")
            or operation.get("process_name")
            or "",
            "locked": True,
            "revision_item_id": new_item["id"],
            "source_revision_item_id": locked_task["revision_item_id"],
            "requires_manual_unlock": bool(conflict),
            "reason": (
                conflict["reason"]
                if conflict
                else "锁定任务保留原生产节点和计划时间"
            ),
        }
        if conflict:
            locked_result.update({
                "code": "LOCKED_TASK_CONFLICT",
                "production_node_id": locked_task.get("production_node_id"),
                **conflict,
            })
        return locked_result, conflict, locked_end

    @staticmethod
    def _plan_replan_operations(
        *,
        order_id,
        order,
        context,
        active_locks,
        order_serial_ids,
        start,
        standard_as_of,
        run_key,
        run_id,
        revision_id,
        input_digest,
        use_node_engine,
        occupancy,
        txn,
        capacity_service,
    ):
        """Plan unfinished operations and restore locked operations."""
        prior_by_op = {
            int(row["order_process_id"]): row
            for row in context["prior_schedules"]
        }
        result = []
        conflicts = []
        blocked = False
        cursor = start
        for operation in context["operations"]:
            baseline = ScheduleDynamicReplanPolicy.operation_baseline(operation)
            process_snapshot = operation.get("process_name_snapshot") or operation.get("process_name") or ""
            route_snapshot = operation.get("route_name_snapshot") or order.get("route_name_snapshot") or ""
            common = {
                "order_id": order_id,
                "order_process_id": operation["order_process_id"],
                "process_id": operation["process_id"],
                "seq_order": operation["seq_order"],
                "quantity": baseline["remaining_quantity"],
                "route_version_id": operation.get("route_version_id") or order.get("route_version_id"),
                "process_version_id": operation.get("process_version_id"),
                "process_name_snapshot": process_snapshot,
                "route_name_snapshot": route_snapshot,
                "schedule_run_key": run_key,
                "schedule_run_id": run_id,
                "schedule_revision_id": revision_id,
                "completed_quantity_snapshot": baseline["completed_quantity"],
                "rework_quantity_snapshot": baseline["rework_quantity"],
                "remaining_quantity_snapshot": baseline["remaining_quantity"],
                "source_fact_digest": input_digest,
            }
            if baseline["remaining_quantity"] <= 0:
                previous = prior_by_op.get(int(operation["order_process_id"]), {})
                payload = {
                    **common, "process_line_id": None, "standard_id": None,
                    "standard_version": previous.get("standard_version"),
                    "standard_minutes_per_unit": previous.get("standard_minutes_per_unit") or 0,
                    "setup_minutes": previous.get("setup_minutes") or 0,
                    "difficulty_factor": previous.get("difficulty_factor") or 1,
                    "planned_minutes": 0, "occupied_minutes": 0,
                    "plan_start": (previous.get("plan_start") or cursor.strftime("%Y-%m-%d")),
                    "plan_end": (previous.get("plan_end") or cursor.strftime("%Y-%m-%d")),
                    "planned_start_at": previous.get("planned_start_at") or "",
                    "planned_end_at": previous.get("planned_end_at") or "",
                    "status": "completed", "blocked_reason": "",
                    "line_name_snapshot": "", "segments": [],
                }
                payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                result.append({**payload, "line_name": None, "process_name": process_snapshot,
                               "reason": "已完成，无需重排"})
                continue
            locked_task = active_locks.get(int(operation["order_process_id"]))
            if use_node_engine and locked_task:
                locked_result, lock_conflict, locked_end = (
                    ScheduleReplanService._restore_locked_task(
                        operation=operation,
                        common=common,
                        locked_task=locked_task,
                        context=context,
                        cursor=cursor,
                        revision_id=revision_id,
                        txn=txn,
                        capacity_service=capacity_service,
                    )
                )
                if lock_conflict:
                    blocked = True
                    conflicts.append({
                        "code": "LOCKED_TASK_CONFLICT",
                        "revision_item_id": locked_result["revision_item_id"],
                        "source_revision_item_id": locked_result[
                            "source_revision_item_id"
                        ],
                        "production_node_id": locked_result.get(
                            "production_node_id"
                        ),
                        "requires_manual_unlock": True,
                        **lock_conflict,
                    })
                if locked_end:
                    cursor = max(cursor, locked_end)
                result.append(locked_result)
                continue
            if blocked:
                # Preserve the dependency block while recording that
                # this operation was not independently evaluated.
                payload = {
                    **common, "process_line_id": None, "production_node_id": None, "standard_id": None, "standard_version": None,
                    "standard_minutes_per_unit": 0, "setup_minutes": 0, "difficulty_factor": 1,
                    "planned_minutes": 0, "occupied_minutes": 0,
                    "plan_start": cursor.strftime("%Y-%m-%d"), "plan_end": cursor.strftime("%Y-%m-%d"),
                    "planned_start_at": "", "planned_end_at": "", "status": "blocked",
                    "blocked_reason": "前序工序无法重排", "blocked_code": "PREVIOUS_OPERATION_BLOCKED",
                    "line_name_snapshot": "", "segments": [],
                }
                payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                result.append({**payload, "line_name": None, "process_name": process_snapshot,
                               "reason": payload["blocked_reason"]})
                continue

            execution_policy = ScheduleCapacityRepository.find_execution_policy(
                common.get("route_version_id"), common.get("process_version_id"), txn,
            )
            if execution_policy and execution_policy["execution_mode"] in {
                "outsourced", "non_scheduled",
            }:
                lead_minutes = max(float(execution_policy["external_lead_minutes"] or 0), 0)
                begin = cursor
                end = begin + timedelta(minutes=lead_minutes)
                payload = {
                    **common,
                    "process_line_id": None,
                    "production_node_id": None,
                    "execution_mode": execution_policy["execution_mode"],
                    "standard_id": None,
                    "standard_version": None,
                    "standard_minutes_per_unit": 0,
                    "setup_minutes": 0,
                    "difficulty_factor": 1,
                    "planned_minutes": lead_minutes,
                    "occupied_minutes": 0,
                    "plan_start": begin.strftime("%Y-%m-%d"),
                    "plan_end": end.strftime("%Y-%m-%d"),
                    "planned_start_at": capacity_service._format_timestamp(begin),
                    "planned_end_at": capacity_service._format_timestamp(end),
                    "status": "planned",
                    "blocked_reason": "",
                    "blocked_code": "",
                    "standard_match_scope": "execution_policy",
                    "capacity_snapshot_json": json.dumps({
                        "execution_mode": execution_policy["execution_mode"],
                        "external_lead_minutes": lead_minutes,
                        "route_version_id": common.get("route_version_id"),
                        "process_version_id": common.get("process_version_id"),
                    }, ensure_ascii=False, sort_keys=True),
                    "segments": [],
                    "line_name_snapshot": "",
                }
                payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                cursor = end
                result.append({**payload, "line_name": None, "process_name": process_snapshot,
                               "reason": "外协/非排程工序，不占用内部产能"})
                continue

            standard = capacity_service._find_standard(
                txn, order.get("route_id"), operation.get("route_version_id") or order.get("route_version_id"),
                operation["process_id"], operation.get("process_version_id"), order.get("product_id"),
                order.get("product_code"), standard_as_of,
            )
            if not standard:
                blocked = True
                block_reason = "未配置标准工时"
                payload = {
                    **common, "process_line_id": None, "production_node_id": None, "standard_id": None, "standard_version": None,
                    "standard_minutes_per_unit": 0, "setup_minutes": 0, "difficulty_factor": 1,
                    "planned_minutes": 0, "occupied_minutes": 0,
                    "plan_start": cursor.strftime("%Y-%m-%d"), "plan_end": cursor.strftime("%Y-%m-%d"),
                    "planned_start_at": "", "planned_end_at": "", "status": "blocked",
                    "blocked_reason": block_reason, "blocked_code": "MISSING_WORK_TIME_STANDARD",
                    "line_name_snapshot": "", "segments": [],
                }
                payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                result.append({**payload, "line_name": None, "process_name": process_snapshot,
                               "reason": block_reason})
                continue
            if use_node_engine:
                resources = ProductionNodeRepository.list_compatible_nodes(
                    operation, order, at_time=cursor, db=txn,
                )
                no_resource_code = "NO_COMPATIBLE_NODE"
                no_resource_reason = "没有满足能力要求的生产节点"
            else:
                resources = [line for line in ScheduleCapacityRepository.list_process_lines(
                    operation["process_id"], db=txn
                ) if line["status"] == "active"]
                no_resource_code = "NO_COMPATIBLE_NODE"
                no_resource_reason = "工序未配置可用产线"
            if not resources:
                blocked = True
                block_reason = no_resource_reason
                payload = {
                    **common, "process_line_id": None, "production_node_id": None, "standard_id": standard["id"],
                    "standard_version": standard["version"],
                    "standard_minutes_per_unit": standard["standard_minutes_per_unit"],
                    "setup_minutes": standard["setup_minutes"], "difficulty_factor": standard["difficulty_factor"],
                    "planned_minutes": 0, "occupied_minutes": 0,
                    "plan_start": cursor.strftime("%Y-%m-%d"), "plan_end": cursor.strftime("%Y-%m-%d"),
                    "planned_start_at": "", "planned_end_at": "", "status": "blocked",
                    "blocked_reason": block_reason, "blocked_code": no_resource_code,
                    "line_name_snapshot": "", "segments": [],
                }
                payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                result.append({**payload, "line_name": None, "process_name": process_snapshot,
                               "reason": block_reason})
                continue
            try:
                serial_ids = (
                    order_serial_ids
                    if order_serial_ids and len(order_serial_ids) == baseline["remaining_quantity"]
                    and baseline["remaining_quantity"] == int(order["quantity"] or 0)
                    else None
                )
                if use_node_engine:
                    segments, allocations = capacity_service._allocate_split_on_nodes(
                        txn, resources, cursor, baseline["remaining_quantity"], standard, occupancy,
                        operation=operation, order=order,
                        serial_ids=serial_ids,
                        allocation_key_prefix=f"{order_id}:{operation['order_process_id']}",
                        return_allocations=True,
                    )
                else:
                    segments = capacity_service._allocate_split_on_lines(
                        txn, resources, cursor, baseline["remaining_quantity"], standard, occupancy,
                    )
                    allocations = []
            except NodeSchedulingError as exc:
                blocked = True
                block_reason = exc.message
                payload = {
                    **common, "process_line_id": None, "production_node_id": None, "standard_id": standard["id"],
                    "standard_version": standard["version"],
                    "standard_minutes_per_unit": standard["standard_minutes_per_unit"],
                    "setup_minutes": standard["setup_minutes"], "difficulty_factor": standard["difficulty_factor"],
                    "planned_minutes": 0, "occupied_minutes": 0,
                    "plan_start": cursor.strftime("%Y-%m-%d"), "plan_end": cursor.strftime("%Y-%m-%d"),
                    "planned_start_at": "", "planned_end_at": "", "status": "blocked",
                    "blocked_reason": block_reason, "blocked_code": exc.code,
                    "line_name_snapshot": "", "segments": [],
                }
                payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                result.append({**payload, "line_name": None, "process_name": process_snapshot,
                               "reason": block_reason})
                continue
            except ValueError as exc:
                blocked = True
                block_reason = str(exc) or "工作日历没有足够产能"
                payload = {
                    **common, "process_line_id": None, "production_node_id": None, "standard_id": standard["id"],
                    "standard_version": standard["version"],
                    "standard_minutes_per_unit": standard["standard_minutes_per_unit"],
                    "setup_minutes": standard["setup_minutes"], "difficulty_factor": standard["difficulty_factor"],
                    "planned_minutes": 0, "occupied_minutes": 0,
                    "plan_start": cursor.strftime("%Y-%m-%d"), "plan_end": cursor.strftime("%Y-%m-%d"),
                    "planned_start_at": "", "planned_end_at": "", "status": "blocked",
                    "blocked_reason": block_reason,
                    "blocked_code": "NODE_CALENDAR_UNAVAILABLE" if use_node_engine else "NODE_CALENDAR_UNAVAILABLE",
                    "line_name_snapshot": "", "segments": [],
                }
                payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                result.append({**payload, "line_name": None, "process_name": process_snapshot,
                               "reason": block_reason})
                continue
            if not segments:
                blocked = True
                block_reason = "生产节点未生成可用排程分段"
                payload = {
                    **common,
                    "process_line_id": None,
                    "production_node_id": None,
                    "standard_id": standard["id"],
                    "standard_version": standard["version"],
                    "standard_minutes_per_unit": standard["standard_minutes_per_unit"],
                    "setup_minutes": standard["setup_minutes"],
                    "difficulty_factor": standard["difficulty_factor"],
                    "planned_minutes": 0,
                    "occupied_minutes": 0,
                    "plan_start": cursor.strftime("%Y-%m-%d"),
                    "plan_end": cursor.strftime("%Y-%m-%d"),
                    "planned_start_at": "",
                    "planned_end_at": "",
                    "status": "blocked",
                    "blocked_reason": block_reason,
                    "blocked_code": "NODE_CALENDAR_UNAVAILABLE",
                    "line_name_snapshot": "",
                    "segments": [],
                    "allocations": [],
                }
                payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(
                    payload, txn
                )
                result.append({
                    **payload,
                    "line_name": None,
                    "process_name": process_snapshot,
                    "reason": block_reason,
                })
                continue
            begin = min(capacity_service._parse_timestamp(item["start_at"]) for item in segments)
            end = max(capacity_service._parse_timestamp(item["end_at"]) for item in segments)
            resource_key = "production_node_id" if use_node_engine else "process_line_id"
            resource_ids = sorted({item[resource_key] for item in segments})
            resource_by_id = {resource["id"]: dict(resource) for resource in resources}
            primary_resource = max(
                resource_ids,
                key=lambda resource_id: (
                    sum(float(item["occupied_minutes"]) for item in segments if item[resource_key] == resource_id),
                    -resource_id,
                ),
            )
            snapshots = []
            for resource_id in resource_ids:
                resource = resource_by_id[resource_id]
                calendar = ScheduleCapacityRepository.get_calendar(resource["calendar_id"], db=txn) or ScheduleCapacityRepository.get_calendar(db=txn)
                shifts = ScheduleCapacityRepository.list_calendar_shifts(calendar["id"], db=txn) if calendar else []
                item = capacity_service._calendar_snapshot(calendar, shifts)
                item.update({
                    resource_key: resource_id,
                    "process_line_id": resource.get("legacy_process_line_id", resource_id),
                    "line_code": resource.get("line_code", resource.get("node_code", "")),
                    "line_name": resource.get("line_name", resource.get("node_name", "")),
                    "daily_minutes": float(resource.get("daily_minutes") or resource.get("capacity_minutes") or capacity_service.DEFAULT_DAILY_MINUTES),
                    "quantity": sum(int(segment.get("quantity") or 0) for segment in segments if segment[resource_key] == resource_id),
                })
                if use_node_engine:
                    item.update({
                        "production_node_id": resource_id,
                        "node_code": resource.get("node_code", ""),
                        "node_name": resource.get("node_name", ""),
                        "capacity_mode": resource.get("capacity_mode", "exclusive"),
                        "capabilities": resource.get("capabilities", []),
                    })
                snapshots.append(item)
            primary_snapshot = next(item for item in snapshots if item[resource_key] == primary_resource)
            duration = sum(float(item["occupied_minutes"]) for item in segments)
            payload = {
                **common,
                "process_line_id": resource_by_id[primary_resource].get("legacy_process_line_id", primary_resource) if use_node_engine else primary_resource,
                "production_node_id": primary_resource if use_node_engine else None,
                "node_code_snapshot": resource_by_id[primary_resource].get("node_code", "") if use_node_engine else "",
                "node_name_snapshot": resource_by_id[primary_resource].get("node_name", "") if use_node_engine else "",
                "capacity_mode_snapshot": resource_by_id[primary_resource].get("capacity_mode", "") if use_node_engine else "",
                "node_calendar_snapshot_json": json.dumps(primary_snapshot, ensure_ascii=False, sort_keys=True) if use_node_engine else "{}",
                "node_capability_snapshot_json": json.dumps(resource_by_id[primary_resource].get("capabilities", []), ensure_ascii=False, sort_keys=True) if use_node_engine else "[]",
                "standard_id": standard["id"],
                "standard_version": standard["version"],
                "standard_minutes_per_unit": standard["standard_minutes_per_unit"],
                "setup_minutes": standard["setup_minutes"], "difficulty_factor": standard["difficulty_factor"],
                "planned_minutes": duration, "occupied_minutes": duration, "status": "planned",
                "standard_match_scope": standard["match_scope"],
                "planned_start_at": capacity_service._format_timestamp(begin),
                "planned_end_at": capacity_service._format_timestamp(end),
                "capacity_snapshot_json": json.dumps({**primary_snapshot, "line_count": len(snapshots), "lines": snapshots,
                                                       "node_count": len(snapshots) if use_node_engine else 0,
                                                       "nodes": snapshots if use_node_engine else []}, ensure_ascii=False, sort_keys=True),
                "shift_snapshot_json": json.dumps([shift for item in snapshots for shift in item["shifts"]], ensure_ascii=False, sort_keys=True),
                "calendar_id": primary_snapshot["calendar_id"], "line_name_snapshot": primary_snapshot["line_name"],
                "segments": segments, "allocations": allocations,
                "plan_start": begin.strftime("%Y-%m-%d"), "plan_end": end.strftime("%Y-%m-%d"),
            }
            payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
            cursor = end
            result.append({**payload, "line_name": primary_snapshot["line_name"], "line_count": len(snapshots),
                           "lines": snapshots, "process_name": process_snapshot})


        return result, conflicts, blocked

    @staticmethod
    def _finalize_replan(
        *,
        order_id,
        order,
        context,
        result,
        conflicts,
        blocked,
        run_id,
        revision_id,
        run_key,
        input_digest,
        snapshot,
        reason,
        txn,
        capacity_service,
    ):
        """Persist immutable differences, risk changes, evidence, and run status."""
        planned = [
            item
            for item in result
            if item.get("status") == "planned"
            and (item.get("process_line_id") or item.get("production_node_id"))
        ]
        if planned and not order.get("current_schedule_revision_id"):
            ScheduleCapacityRepository.update_order_summary(
                order_id,
                min(item["plan_start"] for item in planned),
                max(item["plan_end"] for item in planned),
                txn,
            )
        result_json = json.dumps(
            result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        ScheduleCapacityRepository.set_revision_digest(
            revision_id, hashlib.sha256(result_json.encode("utf-8")).hexdigest(), txn
        )
        ScheduleCapacityRepository.finalize_revision_content_digest(
            revision_id, db=txn
        )
        conflict_assessment = capacity_service._assess_revision_conflicts(
            revision_id, "replan", txn, freeze_risk=True
        )
        after_items = [
            dict(item)
            for item in ScheduleCapacityRepository.list_revision_items(
                revision_id, db=txn
            )
        ]
        differences = ScheduleDynamicReplanPolicy.build_differences(
            context["current_revision_items"], after_items
        )
        before_risk = context["current_revision"] or {}
        after_risk = conflict_assessment["risk"] or {}
        changed = [
            item for item in differences if item["change_type"] != "unchanged"
        ]
        replan_summary = {
            "prior_revision_id": order.get("current_schedule_revision_id"),
            "revision_id": revision_id,
            "trigger_count": len(context["replan_triggers"]),
            "changed_operation_count": len(changed),
            "node_change_count": sum(item["node_changed"] for item in changed),
            "delayed_operation_count": sum(
                1 for item in changed if item["end_delta_minutes"] > 0
            ),
            "advanced_operation_count": sum(
                1 for item in changed if item["end_delta_minutes"] < 0
            ),
            "before_risk_level": before_risk.get("risk_level") or "none",
            "after_risk_level": after_risk.get("risk_level") or "none",
            "before_delay_minutes": int(before_risk.get("delay_minutes") or 0),
            "after_delay_minutes": int(after_risk.get("delay_minutes") or 0),
            "risk_change": ScheduleDynamicReplanPolicy.risk_change(
                before_risk, after_risk
            ),
            "blocked": bool(blocked),
            "trigger_reasons": list(
                dict.fromkeys(
                    item.get("reason") or "生产事实发生变化"
                    for item in context["replan_triggers"][:20]
                )
            ),
        }
        ScheduleCapacityRepository.save_replan_evidence(
            revision_id,
            order.get("current_schedule_revision_id"),
            order_id,
            differences,
            replan_summary,
            db=txn,
        )
        ScheduleCapacityRepository.complete_run(run_id, "completed", result, db=txn)
        return {
            "ok": True,
            "order_id": order_id,
            "schedule_run_key": run_key,
            "idempotent_replay": False,
            "status": "completed",
            "input_digest": input_digest,
            "schedule_revision_id": revision_id,
            "revision_status": "draft",
            "replan_reason": reason,
            "input_snapshot": snapshot,
            "operations": result,
            "conflicts": conflicts,
            "revision_conflicts": conflict_assessment["conflicts"],
            "risk": conflict_assessment["risk"],
            "replan_summary": replan_summary,
            "differences": differences,
        }

    @staticmethod
    def _fail_replan(*, run_id, revision_id, error, txn):
        """Keep a failed run auditable while cancelling the new revision."""
        txn.execute("ROLLBACK TO SAVEPOINT dynamic_schedule_replan")
        txn.execute("RELEASE SAVEPOINT dynamic_schedule_replan")
        ScheduleCapacityRepository.cancel_revision(revision_id, txn)
        ScheduleCapacityRepository.complete_run(
            run_id, "failed", [], str(error), db=txn
        )

    @staticmethod
    def dynamic_replan_order(
        order_id,
        start_at=None,
        schedule_run_key="",
        reason="",
        db=None,
        actor_id=None,
        capacity_service=None,
    ):
        """Replan through one transaction with explicit use-case phases."""
        if capacity_service is None:
            raise ValueError("动态重排必须通过 ScheduleCapacityService 入口调用")
        request = ScheduleReplanService._prepare_request(
            start_at, schedule_run_key, reason, capacity_service
        )
        failure = None
        response = None
        with capacity_service._transaction(db) as txn:
            use_node_engine = bool(
                getattr(config, "PRODUCTION_NODE_ENGINE_ENABLED", False)
            )
            facts = ScheduleReplanService._load_replan_facts(
                order_id, txn, use_node_engine
            )
            prior_run = ScheduleCapacityRepository.find_run(
                request["run_key"], txn
            )
            replay = ScheduleReplanService._replay_existing_run(
                order_id, request["run_key"], prior_run, txn
            )
            if replay is not None:
                return replay
            ledger = ScheduleReplanService._create_replan_ledger(
                order_id,
                request,
                facts,
                request["run_key"],
                actor_id,
                txn,
                capacity_service,
            )
            try:
                txn.execute("SAVEPOINT dynamic_schedule_replan")
                occupancy = ScheduleReplanService._load_replan_occupancy(
                    order_id,
                    facts["context"],
                    facts["active_locks"],
                    use_node_engine,
                    txn,
                    capacity_service,
                )
                result, conflicts, blocked = (
                    ScheduleReplanService._plan_replan_operations(
                        order_id=order_id,
                        order=facts["order"],
                        context=facts["context"],
                        active_locks=facts["active_locks"],
                        order_serial_ids=facts["order_serial_ids"],
                        start=request["start"],
                        standard_as_of=request["standard_as_of"],
                        run_key=request["run_key"],
                        run_id=ledger["run_id"],
                        revision_id=ledger["revision_id"],
                        input_digest=ledger["input_digest"],
                        use_node_engine=use_node_engine,
                        occupancy=occupancy,
                        txn=txn,
                        capacity_service=capacity_service,
                    )
                )
                response = ScheduleReplanService._finalize_replan(
                    order_id=order_id,
                    order=facts["order"],
                    context=facts["context"],
                    result=result,
                    conflicts=conflicts,
                    blocked=blocked,
                    run_id=ledger["run_id"],
                    revision_id=ledger["revision_id"],
                    run_key=request["run_key"],
                    input_digest=ledger["input_digest"],
                    snapshot=ledger["snapshot"],
                    reason=request["reason"],
                    txn=txn,
                    capacity_service=capacity_service,
                )
                txn.execute("RELEASE SAVEPOINT dynamic_schedule_replan")
            except Exception as exc:
                ScheduleReplanService._fail_replan(
                    run_id=ledger["run_id"],
                    revision_id=ledger["revision_id"],
                    error=exc,
                    txn=txn,
                )
                failure = str(exc)
        if failure:
            raise ValueError(failure)
        return response
