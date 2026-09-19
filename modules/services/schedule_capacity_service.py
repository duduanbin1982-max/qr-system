"""工序级、多产线、工时驱动的排程策略。"""

import hashlib
import heapq
import json
import math
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta

from modules.services import BaseService
from modules import config
from modules.domain.schedule_deadline_risk import ScheduleDeadlineRiskPolicy
from modules.domain.schedule_dynamic_replan import ScheduleDynamicReplanPolicy
from modules.domain.production_node_scheduling import NodeSchedulingError, ProductionNodePolicy
from modules.repositories.schedule_capacity_repository import ScheduleCapacityRepository
from modules.repositories.production_node_repository import ProductionNodeRepository
from modules.services.production_node_service import ProductionNodeService


class ScheduleCapacityService:
    DEFAULT_DAILY_MINUTES = 540

    @staticmethod
    def _limit(value, default=500):
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
        limit = ScheduleCapacityService._limit(limit)
        return {"lines": [dict(row) for row in ScheduleCapacityRepository.list_process_lines(process_id, limit=limit)]}

    @staticmethod
    def list_calendars():
        return {"ok": True, "calendars": ScheduleCapacityRepository.list_calendars()}

    @staticmethod
    def list_schedulable_orders(limit=500, now=None):
        limit = ScheduleCapacityService._limit(limit)
        return {
            "ok": True,
            "orders": ScheduleCapacityRepository.list_schedulable_orders(limit, now=now),
        }

    @staticmethod
    def auto_plan_orders(
        start_date=None, auto_plan_key="", limit=100, actor_id=None, db=None,
    ):
        """Generate schedules for the immutable priority queue as one ledgered run.

        The queue snapshot is hashed before any schedule is generated.  Reusing
        a key with the same input replays the stored result; reusing it with a
        different queue or start date is rejected so an audit record can never
        be silently overwritten.
        """
        run_key = str(auto_plan_key or "").strip()
        if not run_key:
            raise ValueError("自动排程幂等键不能为空")
        bounded_limit = ScheduleCapacityService._limit(limit, default=100)
        if start_date in (None, ""):
            effective_start = datetime.now().strftime("%Y-%m-%d")
        else:
            effective_start = ScheduleCapacityService._date(start_date, "计划开始日期").strftime("%Y-%m-%d")

        response = None
        failure = None
        with ScheduleCapacityService._transaction(db) as txn:
            planning_now = datetime.now()
            queue = ScheduleCapacityRepository.list_schedulable_orders(
                bounded_limit, db=txn, now=planning_now,
            )
            input_snapshot = {
                "start_date": effective_start,
                "limit": bounded_limit,
                "orders": [
                    {
                        "order_id": int(order["id"]),
                        "effective_priority_level": int(order.get("effective_priority_level") or 3),
                        "effective_is_expedited": int(order.get("effective_is_expedited") or 0),
                        "priority_version": int(order.get("priority_version") or 1),
                        "schedule_policy": order.get("schedule_policy") or "auto",
                    }
                    for order in queue
                ],
            }
            input_json = json.dumps(
                input_snapshot, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            )
            input_digest = hashlib.sha256(input_json.encode("utf-8")).hexdigest()
            prior_run = ScheduleCapacityRepository.find_auto_plan_run(run_key, db=txn)
            if prior_run:
                if prior_run["input_digest"] != input_digest:
                    raise ValueError("自动排程幂等键已被不同输入使用")
                stored = ScheduleCapacityRepository.auto_plan_result(prior_run)
                return {
                    **stored,
                    "ok": prior_run["status"] == "completed",
                    "auto_plan_key": run_key,
                    "status": prior_run["status"],
                    "idempotent_replay": True,
                    "input_digest": input_digest,
                    "error": prior_run["error_message"] or "",
                }

            run_id = ScheduleCapacityRepository.create_auto_plan_run(
                run_key, effective_start, input_digest, input_json,
                created_by=actor_id, db=txn,
            )
            results = []
            errors = []
            for order in queue:
                order_id = int(order["id"])
                order_run_key = f"{run_key}:{order_id}"
                try:
                    generated = ScheduleCapacityService.generate_order_schedule(
                        order_id,
                        start_date=effective_start,
                        schedule_run_key=order_run_key,
                        actor_id=actor_id,
                        db=txn,
                    )
                    results.append({
                        "order_id": order_id,
                        "order_no": order.get("order_no") or "",
                        "status": generated.get("status", "completed"),
                        "ok": bool(generated.get("ok")),
                        "schedule_run_key": generated.get("schedule_run_key", order_run_key),
                        "schedule_revision_id": generated.get("schedule_revision_id"),
                        "revision_status": generated.get("revision_status"),
                        "operations": generated.get("operations", []),
                    })
                except Exception as exc:
                    message = str(exc) or "自动排程失败"
                    errors.append({"order_id": order_id, "order_no": order.get("order_no") or "", "error": message})
                    results.append({
                        "order_id": order_id,
                        "order_no": order.get("order_no") or "",
                        "status": "failed",
                        "ok": False,
                        "schedule_run_key": order_run_key,
                        "error": message,
                        "operations": [],
                    })

            overall_status = "failed" if errors else "completed"
            result = {
                "ok": not errors,
                "auto_plan_key": run_key,
                "status": overall_status,
                "idempotent_replay": False,
                "input_digest": input_digest,
                "queue_count": len(queue),
                "failed_count": len(errors),
                "orders": results,
            }
            error_message = "; ".join(item["error"] for item in errors)
            ScheduleCapacityRepository.complete_auto_plan_run(
                run_id, overall_status, result, error_message=error_message, db=txn,
            )
            response = result
        if failure:
            raise ValueError(failure)
        return response

    @staticmethod
    def _date(value, label):
        try:
            return datetime.strptime((value or "").strip(), "%Y-%m-%d")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label}必须使用 YYYY-MM-DD 格式") from exc

    @staticmethod
    def _duration_minutes(quantity, standard):
        if not standard:
            return 0.0
        quantity = max(int(quantity or 0), 0)
        setup = float(standard["setup_minutes"] or 0)
        unit = float(standard["standard_minutes_per_unit"] or 0)
        factor = max(float(standard["difficulty_factor"] or 1), 0.01)
        return max(setup + quantity * unit * factor, 1.0)

    @staticmethod
    def _find_standard(
        db, route_id, route_version_id, process_id, process_version_id,
        product_id, product_code, as_of_date,
    ):
        return ScheduleCapacityRepository.find_active_standard(
            route_id, route_version_id, process_id, process_version_id,
            product_id, product_code, as_of_date, db,
        )

    @staticmethod
    @contextmanager
    def _transaction(db=None):
        """Use the request UoW in production or an explicit clone connection in preflight."""
        if db is None:
            with BaseService.transaction() as txn:
                yield txn
            return
        started = False
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
            started = True
        try:
            yield db
            if started:
                db.commit()
        except Exception:
            if started:
                db.rollback()
            raise

    @staticmethod
    def _parse_timestamp(value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("T", " "))
        except ValueError:
            return None

    @staticmethod
    def _format_timestamp(value):
        """Serialize timestamps without losing fractional-minute precision."""
        if value is None:
            return ""
        if getattr(value, "second", 0) or getattr(value, "microsecond", 0):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return value.strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def _merge_intervals(intervals):
        """Merge overlapping/touching occupancy intervals before allocation."""
        normalized = sorted(
            (start, end) for start, end in intervals if start and end and end > start
        )
        merged = []
        for start, end in normalized:
            if not merged or start > merged[-1][1]:
                merged.append([start, end])
            elif end > merged[-1][1]:
                merged[-1][1] = end
        return [(start, end) for start, end in merged]

    @staticmethod
    def _calendar_snapshot(calendar, shifts):
        return {
            "calendar_id": calendar["id"],
            "calendar_code": calendar["calendar_code"],
            "calendar_name": calendar["calendar_name"],
            "timezone": calendar["timezone"],
            "weekly_workdays": calendar["weekly_workdays"],
            "shifts": [
                {
                    "id": shift["id"],
                    "code": shift["shift_code"],
                    "name": shift["shift_name"],
                    "start_minute": shift["start_minute"],
                    "end_minute": shift["end_minute"],
                }
                for shift in shifts
            ],
        }

    @staticmethod
    def _calendar_slots(db, calendar, shifts, start_date, daily_minutes=None, max_days=3660):
        weekly = {
            int(item.strip())
            for item in str(calendar["weekly_workdays"] or "").split(",")
            if item.strip().isdigit()
        }
        shift_map = {shift["id"]: shift for shift in shifts}
        for day_offset in range(max_days):
            work_date = start_date.date() + timedelta(days=day_offset)
            date_text = work_date.strftime("%Y-%m-%d")
            exception = ScheduleCapacityRepository.get_calendar_exception(
                calendar["id"], date_text, db=db
            )
            if exception is not None:
                if not int(exception["is_working_day"]):
                    continue
                selected_ids = [
                    int(item.strip()) for item in str(exception["shift_ids"] or "").split(",")
                    if item.strip().isdigit()
                ]
                selected = [shift_map[item] for item in selected_ids if item in shift_map]
                selected = selected or list(shifts)
            elif (work_date.weekday() + 1) not in weekly:
                continue
            else:
                selected = list(shifts)
            daily_remaining = float(daily_minutes) if daily_minutes else None
            for shift in selected:
                if daily_remaining is not None and daily_remaining <= 0:
                    break
                midnight = datetime.combine(work_date, datetime.min.time())
                begin = midnight + timedelta(minutes=int(shift["start_minute"]))
                end = midnight + timedelta(minutes=int(shift["end_minute"]))
                if daily_remaining is not None:
                    shift_minutes = (end - begin).total_seconds() / 60
                    end = begin + timedelta(minutes=min(shift_minutes, daily_remaining))
                    daily_remaining -= (end - begin).total_seconds() / 60
                if end <= begin:
                    continue
                yield {
                    "shift_id": shift["id"],
                    "shift_code": shift["shift_code"],
                    "shift_name": shift["shift_name"],
                    "start": begin,
                    "end": end,
                }

    @staticmethod
    def _allocate_on_line(db, calendar, shifts, daily_minutes, earliest, duration, occupied):
        """Allocate one operation across free portions of one line's shifts."""
        slots = ScheduleCapacityService._calendar_slots(
            db, calendar, shifts, earliest, daily_minutes=daily_minutes
        )
        return ScheduleCapacityService._allocate_from_slots(
            slots, earliest, duration, occupied
        )

    @staticmethod
    def _allocate_from_slots(slots, earliest, duration, occupied):
        """Allocate minutes from an ordered stream of available capacity slots."""
        remaining = float(duration)
        segments = []
        epsilon = 1e-7
        intervals = ScheduleCapacityService._merge_intervals(occupied)
        for slot in slots:
            if remaining <= epsilon:
                break
            if slot["end"] <= earliest:
                continue
            cursor = max(slot["start"], earliest)
            for busy_start, busy_end in intervals:
                if busy_end <= cursor:
                    continue
                if busy_start >= slot["end"]:
                    break
                free_end = min(busy_start, slot["end"])
                if free_end > cursor:
                    available = (free_end - cursor).total_seconds() / 60
                    take = min(remaining, available)
                    end = cursor + timedelta(minutes=take)
                    segments.append({
                        "start_at": ScheduleCapacityService._format_timestamp(cursor),
                        "end_at": ScheduleCapacityService._format_timestamp(end),
                        "occupied_minutes": take,
                        "shift_id": slot["shift_id"],
                    })
                    remaining -= take
                    cursor = end
                    if remaining <= epsilon:
                        break
                cursor = max(cursor, busy_end)
                if cursor >= slot["end"]:
                    break
            if remaining <= epsilon:
                break
            if cursor < slot["end"]:
                available = (slot["end"] - cursor).total_seconds() / 60
                take = min(remaining, available)
                end = cursor + timedelta(minutes=take)
                segments.append({
                    "start_at": ScheduleCapacityService._format_timestamp(cursor),
                    "end_at": ScheduleCapacityService._format_timestamp(end),
                    "occupied_minutes": take,
                    "shift_id": slot["shift_id"],
                })
                remaining -= take
        if remaining > epsilon:
            raise ValueError("工作日历在可搜索范围内没有足够产能")
        return segments

    @staticmethod
    def _allocate_split_on_lines(
        db, lines, earliest, quantity, standard, occupancy,
    ):
        """Allocate one operation's quantity across parallel process lines.

        Each line receives whole units and its own setup time.  Allocation is
        greedy by projected completion time, while every call still uses the
        calendar-aware minute allocator, so a single operation can span shifts
        and dates on several lines without overlap.
        """
        remaining_quantity = max(int(quantity or 0), 0)
        if remaining_quantity <= 0:
            return []
        line_state = {
            line["id"]: {
                "line": line,
                "calendar": ScheduleCapacityRepository.get_calendar(line["calendar_id"], db=db)
                    or ScheduleCapacityRepository.get_calendar(db=db),
                "shifts": [],
                "segments": [],
                "quantity": 0,
            }
            for line in lines
        }
        for state in line_state.values():
            if state["calendar"]:
                state["shifts"] = ScheduleCapacityRepository.list_calendar_shifts(
                    state["calendar"]["id"], db=db
                )
        line_state = {
            line_id: state for line_id, state in line_state.items()
            if state["calendar"] and state["shifts"]
        }
        if not line_state:
            raise ValueError("未配置有效工作日历或班次")

        epsilon = 1e-7
        while remaining_quantity > 0:
            available = []
            chunk = max(1, int(math.ceil(remaining_quantity / len(line_state))))
            for line_id, state in line_state.items():
                include_setup = state["quantity"] == 0
                duration = ScheduleCapacityService._duration_minutes(
                    chunk, standard if include_setup else {**dict(standard), "setup_minutes": 0}
                )
                try:
                    candidate_segments = ScheduleCapacityService._allocate_on_line(
                        db, state["calendar"], state["shifts"],
                        float(state["line"]["daily_minutes"] or ScheduleCapacityService.DEFAULT_DAILY_MINUTES),
                        earliest, duration, occupancy.get(line_id, []),
                    )
                except ValueError:
                    continue
                end = ScheduleCapacityService._parse_timestamp(candidate_segments[-1]["end_at"])
                available.append((end, line_id, candidate_segments, chunk, duration))
            if not available:
                raise ValueError("工作日历在可搜索范围内没有足够产能")
            _, line_id, candidate_segments, allocated_quantity, duration = min(
                available, key=lambda item: (item[0], item[1])
            )
            for index, segment in enumerate(candidate_segments):
                segment["process_line_id"] = line_id
                # Quantity is recorded once per allocation batch; continuation
                # segments across later shifts carry zero to avoid double count.
                segment["quantity"] = allocated_quantity if index == 0 else 0
                state = line_state[line_id]
                state["segments"].append(segment)
            state = line_state[line_id]
            state["quantity"] += allocated_quantity
            ScheduleCapacityService._add_segments_to_occupancy(
                occupancy, line_id, candidate_segments
            )
            remaining_quantity -= allocated_quantity

        result = []
        for state in line_state.values():
            if not state["segments"]:
                continue
            for segment in state["segments"]:
                result.append(segment)
        return result

    @staticmethod
    def _add_segments_to_occupancy(occupancy, line_id, segments):
        bucket = occupancy.setdefault(line_id, [])
        for segment in segments:
            bucket.append((
                ScheduleCapacityService._parse_timestamp(segment["start_at"]),
                ScheduleCapacityService._parse_timestamp(segment["end_at"]),
            ))

    @staticmethod
    def _add_segments_to_node_occupancy(occupancy, production_node_id, segments):
        """Add node-native intervals while keeping the old line helper intact."""
        bucket = occupancy.setdefault(production_node_id, [])
        for segment in segments:
            bucket.append((
                ScheduleCapacityService._parse_timestamp(segment["start_at"]),
                ScheduleCapacityService._parse_timestamp(segment["end_at"]),
            ))

    @staticmethod
    def _allocate_on_node(db, node, earliest, duration, occupancy):
        """Allocate one operation on one physical node."""
        calendar = ScheduleCapacityRepository.get_calendar(node.get("calendar_id"), db=db)
        shifts = (
            ScheduleCapacityRepository.list_calendar_shifts(calendar["id"], db=db)
            if calendar else []
        )
        if not calendar or not shifts:
            raise NodeSchedulingError(
                "NODE_CALENDAR_UNAVAILABLE", "生产节点日历没有可用时间",
                {"production_node_id": node.get("id")},
            )
        daily_minutes = sum(
            max(int(shift["end_minute"]) - int(shift["start_minute"]), 0)
            for shift in shifts
        )
        # Subtractive overrides are modeled as busy intervals. Overtime is a
        # real additive capacity slot and must never be treated as downtime.
        busy = list(occupancy.get(node["id"], []))
        overtime_slots = []
        for override in ProductionNodeRepository.list_node_calendar_overrides(
            node["id"], db=db
        ):
            override = dict(override)
            start = ScheduleCapacityService._parse_timestamp(override.get("start_at"))
            end = ScheduleCapacityService._parse_timestamp(override.get("end_at"))
            if start and end and end > start:
                if override.get("override_type") == "overtime":
                    overtime_slots.append({
                        "shift_id": None,
                        "shift_code": "OVERTIME",
                        "shift_name": "加班",
                        "start": start,
                        "end": end,
                    })
                else:
                    busy.append((start, end))
        base_slots = ScheduleCapacityService._calendar_slots(
            db, calendar, shifts, earliest, daily_minutes=daily_minutes
        )
        combined = heapq.merge(
            base_slots,
            sorted(overtime_slots, key=lambda item: (item["start"], item["end"])),
            key=lambda item: (item["start"], item["end"]),
        )

        def merged_slots():
            current = None
            for slot in combined:
                if current is None:
                    current = dict(slot)
                    continue
                if slot["start"] < current["end"]:
                    if slot["end"] > current["end"]:
                        # The overlap is already represented by ``current``.
                        # Keep only the extending tail with the incoming slot's
                        # metadata so overtime outside a normal shift remains
                        # identifiable as overtime instead of inheriting the
                        # preceding shift id.
                        tail = dict(slot)
                        tail["start"] = current["end"]
                        yield current
                        current = tail
                    continue
                yield current
                current = dict(slot)
            if current is not None:
                yield current

        segments = ScheduleCapacityService._allocate_from_slots(
            merged_slots(), earliest, duration, busy
        )
        for segment in segments:
            segment["production_node_id"] = node["id"]
            segment["process_line_id"] = node.get("legacy_process_line_id")
        return segments

    @staticmethod
    def _allocate_split_on_nodes(
        db, nodes, earliest, quantity, standard, occupancy, *,
        operation=None, order=None, serial_ids=None, allocation_key_prefix="",
        return_allocations=False,
    ):
        """Allocate whole batches and keep serial work on one node."""
        remaining_quantity = max(int(quantity or 0), 0)
        if remaining_quantity <= 0:
            return ([], []) if return_allocations else []
        state = {node["id"]: {"node": node, "segments": [], "quantity": 0} for node in nodes}
        if not state:
            raise NodeSchedulingError("NO_COMPATIBLE_NODE", "没有满足能力要求的生产节点", {})

        serial_values = [str(value).strip() for value in (serial_ids or ()) if str(value).strip()]
        if serial_values:
            if len(set(serial_values)) != len(serial_values) or len(serial_values) != remaining_quantity:
                raise NodeSchedulingError(
                    "SERIAL_ITEM_SPLIT_FORBIDDEN", "序列件输入与排程数量不一致", {
                        "requested_quantity": remaining_quantity, "serial_count": len(serial_values),
                    },
                )
            candidates = []
            for node_id, item in state.items():
                capability = ProductionNodePolicy.matching_capability(
                    capabilities=item["node"].get("capabilities", []),
                    operation=operation or {}, order=order or {},
                ) or {}
                if item["node"].get("capacity_mode") == "batch":
                    batch_size, _, _ = ProductionNodePolicy._batch_configuration(capability)
                    if remaining_quantity > batch_size:
                        continue
                    duration = ProductionNodePolicy.batch_duration_minutes(
                        remaining_quantity, capability, changeover_required=True,
                    )
                else:
                    duration = ScheduleCapacityService._duration_minutes(remaining_quantity, standard)
                try:
                    candidate = ScheduleCapacityService._allocate_on_node(
                        db, item["node"], earliest, duration, occupancy,
                    )
                except (ValueError, NodeSchedulingError):
                    continue
                candidates.append((ScheduleCapacityService._parse_timestamp(candidate[-1]["end_at"]), node_id, candidate, capability))
            if not candidates:
                raise NodeSchedulingError("SERIAL_ITEM_SPLIT_FORBIDDEN", "序列件没有可独占的生产节点", {})
            _, node_id, candidate, capability = min(candidates, key=lambda item: (item[0], item[1]))
            for index, segment in enumerate(candidate):
                segment["quantity"] = remaining_quantity if index == 0 else 0
                state[node_id]["segments"].append(segment)
            ScheduleCapacityService._add_segments_to_node_occupancy(occupancy, node_id, candidate)
            first = candidate[0]
            batch_key = f"{allocation_key_prefix}:node-{node_id}:batch-1" if allocation_key_prefix else f"node-{node_id}:batch-1"
            allocations = [
                {
                    "production_node_id": node_id, "quantity": 1, "serial_id": serial_id,
                    "batch_key": batch_key,
                    "changeover_minutes": float(capability.get("changeover_minutes") or 0),
                    "segment_start_at": first["start_at"], "segment_end_at": candidate[-1]["end_at"],
                }
                for serial_id in serial_values
            ]
            ProductionNodePolicy.validate_quantity_conservation(remaining_quantity, allocations)
            segments = [segment for item in state.values() for segment in item["segments"]]
            return (segments, allocations) if return_allocations else segments

        allocations = []
        batch_counters = {}
        while remaining_quantity > 0:
            available = []
            base_chunk = max(1, int(math.ceil(remaining_quantity / len(state))))
            for node_id, item in state.items():
                include_setup = item["quantity"] == 0
                capability = ProductionNodePolicy.matching_capability(
                    capabilities=item["node"].get("capabilities", []),
                    operation=operation or {}, order=order or {},
                ) or {}
                capacity_mode = item["node"].get("capacity_mode", "exclusive")
                chunk = base_chunk
                if capacity_mode == "batch":
                    batch_size, _, _ = ProductionNodePolicy._batch_configuration(capability)
                    chunk = min(chunk, batch_size)
                    duration = ProductionNodePolicy.batch_duration_minutes(
                        chunk, capability, changeover_required=include_setup,
                    )
                else:
                    effective_standard = standard if include_setup else {**dict(standard), "setup_minutes": 0}
                    duration = ScheduleCapacityService._duration_minutes(chunk, effective_standard)
                try:
                    candidate = ScheduleCapacityService._allocate_on_node(
                        db, item["node"], earliest, duration, occupancy,
                    )
                except (ValueError, NodeSchedulingError):
                    continue
                end = ScheduleCapacityService._parse_timestamp(candidate[-1]["end_at"])
                available.append((end, node_id, candidate, chunk, capability, capacity_mode))
            if not available:
                raise NodeSchedulingError("NODE_CALENDAR_UNAVAILABLE", "工作日历在可搜索范围内没有足够产能", {})
            _, node_id, candidate, allocated, capability, capacity_mode = min(
                available, key=lambda item: (item[0], item[1])
            )
            item = state[node_id]
            batch_number = batch_counters.get(node_id, 0) + 1
            batch_counters[node_id] = batch_number
            batch_key = f"{allocation_key_prefix}:node-{node_id}:batch-{batch_number}" if allocation_key_prefix else f"node-{node_id}:batch-{batch_number}"
            for index, segment in enumerate(candidate):
                segment["quantity"] = allocated if index == 0 else 0
                state[node_id]["segments"].append(segment)
            first = candidate[0]
            allocations.append({
                "production_node_id": node_id, "quantity": allocated, "serial_id": None,
                "batch_key": batch_key,
                "changeover_minutes": float(capability.get("changeover_minutes") or 0) if capacity_mode == "batch" and item["quantity"] == 0 else 0,
                "segment_start_at": first["start_at"], "segment_end_at": candidate[-1]["end_at"],
            })
            state[node_id]["quantity"] += allocated
            ScheduleCapacityService._add_segments_to_node_occupancy(occupancy, node_id, candidate)
            remaining_quantity -= allocated
        segments = [segment for item in state.values() for segment in item["segments"]]
        ProductionNodePolicy.validate_quantity_conservation(quantity, allocations)
        return (segments, allocations) if return_allocations else segments

    @staticmethod
    def generate_order_schedule(order_id, start_date=None, schedule_run_key="", db=None,
                                actor_id=None):
        failure = None
        response = None
        with ScheduleCapacityService._transaction(db) as txn:
            order = ScheduleCapacityRepository.ensure_order_version_bindings(order_id, txn)
            if not order:
                raise ValueError("订单不存在")
            operations = ScheduleCapacityRepository.find_order_operations(order_id, db=txn)
            if not operations:
                raise ValueError("订单没有工序，无法生成排程")
            order_serial_ids = ScheduleCapacityRepository.list_order_serial_ids(order_id, db=txn)
            cursor = ScheduleCapacityService._date(start_date or order["plan_start"], "计划开始日期")
            # A regenerated/in-progress order may retain a historical plan start.
            # Standards are effective for the planning run, not retroactively for
            # that old date; use the later of requested start and run date.
            standard_as_of = max(cursor.date(), datetime.now().date()).strftime("%Y-%m-%d")
            run_key = (schedule_run_key or datetime.now().strftime("schedule-%Y%m%d%H%M%S")).strip()
            if not run_key:
                raise ValueError("排程幂等键不能为空")
            prior_run = ScheduleCapacityRepository.find_run(run_key, txn)
            if prior_run:
                if prior_run["order_id"] != order_id:
                    raise ValueError("排程幂等键已被其他订单使用")
                replay = ScheduleCapacityRepository.run_result(prior_run)
                revision = ScheduleCapacityRepository.find_revision_by_run(prior_run["id"], db=txn)
                return {"ok": prior_run["status"] == "completed", "order_id": order_id,
                        "schedule_run_key": run_key, "idempotent_replay": True,
                        "status": prior_run["status"], "error": prior_run["error_message"] or "",
                        "schedule_revision_id": revision["id"] if revision else None,
                        "revision_status": revision["status"] if revision else None,
                        "operations": replay}

            run_id = ScheduleCapacityRepository.create_run(order_id, run_key, cursor.strftime("%Y-%m-%d"), txn)
            # The revision is created before the savepoint so a failed
            # generation can be retained as an auditable cancelled revision.
            revision_id = ScheduleCapacityRepository.create_revision(
                order_id, run_id, run_key, txn, created_by=actor_id,
            )
            try:
                # Keep the run ledger even if scheduling fails halfway through.
                txn.execute("SAVEPOINT schedule_generation")
                ScheduleCapacityRepository.clear_order_schedules(order_id, txn)
                use_node_engine = bool(getattr(config, "PRODUCTION_NODE_ENGINE_ENABLED", False))
                occupancy = {}
                occupancy_rows = (
                    ProductionNodeRepository.list_node_occupancy(order_id, db=txn)
                    if use_node_engine
                    else ScheduleCapacityRepository.list_line_occupancy(order_id, txn)
                )
                occupancy_key = "production_node_id" if use_node_engine else "process_line_id"
                for row in occupancy_rows:
                    start_at = ScheduleCapacityService._parse_timestamp(row["start_at"])
                    end_at = ScheduleCapacityService._parse_timestamp(row["end_at"])
                    resource_id = row[occupancy_key]
                    if resource_id is not None and start_at and end_at and end_at > start_at:
                        occupancy.setdefault(int(resource_id), []).append((start_at, end_at))
                result = []
                blocked = False
                for operation in operations:
                    route_version_id = operation["route_version_id"]
                    process_version_id = operation["process_version_id"]
                    process_snapshot = operation["process_name_snapshot"] or operation["process_name"] or ""
                    route_snapshot = operation["route_name_snapshot"] or order["route_name_snapshot"] or ""
                    completed = max(int(operation["completed"] or 0), 0)
                    rework = max(int(operation["rework"] or 0), 0)
                    remaining = max(int(order["quantity"] or 0) - completed, 0) + rework
                    common = {"order_id": order_id, "order_process_id": operation["order_process_id"],
                              "process_id": operation["process_id"], "seq_order": operation["seq_order"],
                              "quantity": remaining, "route_version_id": route_version_id,
                              "completed_quantity_snapshot": completed,
                              "rework_quantity_snapshot": rework,
                              "remaining_quantity_snapshot": remaining,
                              "process_version_id": process_version_id, "process_name_snapshot": process_snapshot,
                              "route_name_snapshot": route_snapshot, "schedule_run_key": run_key,
                              "schedule_run_id": run_id, "schedule_revision_id": revision_id}
                    if blocked:
                        payload = {**common, "process_line_id": None, "standard_id": None, "standard_version": None,
                                   "standard_minutes_per_unit": 0, "setup_minutes": 0, "difficulty_factor": 1,
                                   "planned_minutes": 0, "plan_start": cursor.strftime("%Y-%m-%d"),
                                   "plan_end": cursor.strftime("%Y-%m-%d"), "status": "blocked",
                                   "blocked_reason": "前序工序无法排程",
                                   "blocked_code": "UPSTREAM_BLOCKED"}
                        payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                        result.append({**payload, "line_name": None, "process_name": process_snapshot,
                                       "reason": payload["blocked_reason"]})
                        continue

                    execution_policy = ScheduleCapacityRepository.find_execution_policy(
                        route_version_id, process_version_id, txn,
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
                            "planned_start_at": ScheduleCapacityService._format_timestamp(begin),
                            "planned_end_at": ScheduleCapacityService._format_timestamp(end),
                            "status": "planned",
                            "blocked_reason": "",
                            "standard_match_scope": "execution_policy",
                            "capacity_snapshot_json": json.dumps({
                                "execution_mode": execution_policy["execution_mode"],
                                "external_lead_minutes": lead_minutes,
                                "route_version_id": route_version_id,
                                "process_version_id": process_version_id,
                            }, ensure_ascii=False, sort_keys=True),
                            "segments": [],
                            "line_name_snapshot": "",
                        }
                        payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                        cursor = end
                        result.append({**payload, "line_name": None, "process_name": process_snapshot,
                                       "reason": "外协/非排程工序，不占用内部产能"})
                        continue

                    standard = ScheduleCapacityService._find_standard(
                        txn, order["route_id"], route_version_id, operation["process_id"],
                        process_version_id, order["product_id"], order["product_code"],
                        standard_as_of,
                    )
                    if not standard:
                        blocked = True
                        payload = {**common, "process_line_id": None, "standard_id": None, "standard_version": None,
                                   "standard_minutes_per_unit": 0, "setup_minutes": 0, "difficulty_factor": 1,
                                   "planned_minutes": 0, "plan_start": cursor.strftime("%Y-%m-%d"),
                                   "plan_end": cursor.strftime("%Y-%m-%d"), "status": "blocked",
                                   "blocked_reason": "未配置标准工时",
                                   "blocked_code": "MISSING_WORK_TIME_STANDARD"}
                        payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                        result.append({**payload, "line_name": None, "process_name": process_snapshot,
                                       "reason": payload["blocked_reason"]})
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
                        payload = {**common, "process_line_id": None, "production_node_id": None,
                                   "standard_id": standard["id"],
                                   "standard_version": standard["version"],
                                   "standard_minutes_per_unit": standard["standard_minutes_per_unit"],
                                   "setup_minutes": standard["setup_minutes"], "difficulty_factor": standard["difficulty_factor"],
                                   "planned_minutes": 0, "plan_start": cursor.strftime("%Y-%m-%d"),
                                   "plan_end": cursor.strftime("%Y-%m-%d"), "status": "blocked",
                                   "blocked_reason": no_resource_reason,
                                   "blocked_code": no_resource_code}
                        payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                        result.append({**payload, "line_name": None, "process_name": process_snapshot,
                                       "reason": payload["blocked_reason"]})
                        continue

                    try:
                        serial_ids = (
                            order_serial_ids
                            if order_serial_ids and len(order_serial_ids) == remaining
                            and remaining == int(order["quantity"] or 0)
                            else None
                        )
                        if use_node_engine:
                            segments, allocations = ScheduleCapacityService._allocate_split_on_nodes(
                                txn, resources, cursor, remaining, standard, occupancy,
                                # Policy matching is mapping-based.  SQLite
                                # rows support keyed indexing but not ``get``;
                                # normalize facts at this service boundary so
                                # capability-constrained nodes work for both
                                # real database rows and test/facade mappings.
                                operation=dict(operation), order=dict(order),
                                serial_ids=serial_ids,
                                allocation_key_prefix=f"{order_id}:{operation['order_process_id']}",
                                return_allocations=True,
                            )
                        else:
                            segments = ScheduleCapacityService._allocate_split_on_lines(
                                txn, resources, cursor, remaining, standard, occupancy,
                            )
                            allocations = []
                    except NodeSchedulingError as exc:
                        blocked = True
                        payload = {**common, "process_line_id": None, "production_node_id": None,
                                   "standard_id": standard["id"],
                                   "standard_version": standard["version"],
                                   "standard_minutes_per_unit": standard["standard_minutes_per_unit"],
                                   "setup_minutes": standard["setup_minutes"], "difficulty_factor": standard["difficulty_factor"],
                                   "planned_minutes": 0, "plan_start": cursor.strftime("%Y-%m-%d"),
                                   "plan_end": cursor.strftime("%Y-%m-%d"), "status": "blocked",
                                   "blocked_reason": exc.message, "blocked_code": exc.code}
                        payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                        result.append({**payload, "line_name": None, "process_name": process_snapshot,
                                       "reason": payload["blocked_reason"]})
                        continue
                    except ValueError as exc:
                        blocked = True
                        payload = {**common, "process_line_id": None, "standard_id": standard["id"],
                                   "standard_version": standard["version"],
                                   "standard_minutes_per_unit": standard["standard_minutes_per_unit"],
                                   "setup_minutes": standard["setup_minutes"], "difficulty_factor": standard["difficulty_factor"],
                                   "planned_minutes": 0, "plan_start": cursor.strftime("%Y-%m-%d"),
                                   "plan_end": cursor.strftime("%Y-%m-%d"), "status": "blocked",
                                   "blocked_reason": str(exc) or "未配置有效工作日历或班次",
                                   "blocked_code": "NODE_CALENDAR_UNAVAILABLE" if use_node_engine else "NODE_CALENDAR_UNAVAILABLE"}
                        payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                        result.append({**payload, "line_name": None, "process_name": process_snapshot,
                                       "reason": payload["blocked_reason"]})
                        continue
                    begin = min(
                        ScheduleCapacityService._parse_timestamp(segment["start_at"])
                        for segment in segments
                    )
                    end = max(
                        ScheduleCapacityService._parse_timestamp(segment["end_at"])
                        for segment in segments
                    )
                    resource_key = "production_node_id" if use_node_engine else "process_line_id"
                    resource_ids = sorted({segment[resource_key] for segment in segments})
                    resource_by_id = {
                        resource["id"]: dict(resource) for resource in resources
                    }
                    primary_resource = max(
                        resource_ids,
                        key=lambda resource_id: (
                            sum(float(segment["occupied_minutes"]) for segment in segments
                                if segment[resource_key] == resource_id),
                            -resource_id,
                        ),
                    )
                    resource_snapshots = []
                    for resource_id in resource_ids:
                        resource = resource_by_id[resource_id]
                        calendar = ScheduleCapacityRepository.get_calendar(
                            resource["calendar_id"], db=txn
                        ) or ScheduleCapacityRepository.get_calendar(db=txn)
                        shifts = ScheduleCapacityRepository.list_calendar_shifts(
                            calendar["id"], db=txn
                        ) if calendar else []
                        snapshot = ScheduleCapacityService._calendar_snapshot(calendar, shifts)
                        snapshot.update({
                            resource_key: resource_id,
                            "process_line_id": resource.get("legacy_process_line_id", resource_id),
                            "line_code": resource.get("line_code", resource.get("node_code", "")),
                            "line_name": resource.get("line_name", resource.get("node_name", "")),
                            "daily_minutes": float(resource.get("daily_minutes") or resource.get("capacity_minutes") or ScheduleCapacityService.DEFAULT_DAILY_MINUTES),
                            "quantity": sum(
                                int(segment.get("quantity") or 0)
                                for segment in segments if segment[resource_key] == resource_id
                            ),
                        })
                        if use_node_engine:
                            snapshot.update({
                                "production_node_id": resource_id,
                                "node_code": resource.get("node_code", ""),
                                "node_name": resource.get("node_name", ""),
                                "capacity_mode": resource.get("capacity_mode", "exclusive"),
                                "capabilities": resource.get("capabilities", []),
                            })
                        resource_snapshots.append(snapshot)
                    primary_snapshot = next(item for item in resource_snapshots if item[resource_key] == primary_resource)
                    total_duration = sum(float(segment["occupied_minutes"]) for segment in segments)
                    capacity_snapshot = {
                        **primary_snapshot,
                        "line_count": len(resource_snapshots),
                        "lines": resource_snapshots,
                        "node_count": len(resource_snapshots) if use_node_engine else 0,
                        "nodes": resource_snapshots if use_node_engine else [],
                    }
                    primary_resource_row = resource_by_id[primary_resource]
                    payload = {**common,
                               "process_line_id": primary_resource_row.get("legacy_process_line_id", primary_resource) if use_node_engine else primary_resource,
                               "production_node_id": primary_resource if use_node_engine else None,
                               "node_code_snapshot": primary_resource_row.get("node_code", "") if use_node_engine else "",
                               "node_name_snapshot": primary_resource_row.get("node_name", "") if use_node_engine else "",
                               "capacity_mode_snapshot": primary_resource_row.get("capacity_mode", "") if use_node_engine else "",
                               "node_calendar_snapshot_json": json.dumps(primary_snapshot, ensure_ascii=False, sort_keys=True) if use_node_engine else "{}",
                               "node_capability_snapshot_json": json.dumps(primary_resource_row.get("capabilities", []), ensure_ascii=False, sort_keys=True) if use_node_engine else "[]",
                               "standard_id": standard["id"],
                               "standard_version": standard["version"],
                               "standard_minutes_per_unit": standard["standard_minutes_per_unit"],
                               "setup_minutes": standard["setup_minutes"], "difficulty_factor": standard["difficulty_factor"],
                               "planned_minutes": total_duration, "occupied_minutes": total_duration, "status": "planned",
                               "standard_match_scope": standard["match_scope"],
                               "planned_start_at": ScheduleCapacityService._format_timestamp(begin),
                               "planned_end_at": ScheduleCapacityService._format_timestamp(end),
                               "capacity_snapshot_json": json.dumps(capacity_snapshot, ensure_ascii=False, sort_keys=True),
                               "shift_snapshot_json": json.dumps(
                                   [shift for snapshot in resource_snapshots for shift in snapshot["shifts"]],
                                   ensure_ascii=False, sort_keys=True,
                               ),
                               "calendar_id": primary_snapshot["calendar_id"],
                               "line_name_snapshot": primary_snapshot["line_name"],
                               "segments": segments, "allocations": allocations,
                               "plan_start": begin.strftime("%Y-%m-%d"), "plan_end": end.strftime("%Y-%m-%d")}
                    payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                    cursor = end
                    result.append({**payload, "line_name": primary_snapshot["line_name"],
                                   "line_count": len(resource_snapshots), "lines": resource_snapshots,
                                   "node_count": len(resource_snapshots) if use_node_engine else 0,
                                   "nodes": resource_snapshots if use_node_engine else [],
                                   "process_name": process_snapshot})
                planned = [
                    row for row in result
                    if row.get("status") == "planned"
                    and (row.get("process_line_id") or row.get("production_node_id"))
                ]
                if planned:
                    first_start = min(row["plan_start"] for row in planned)
                    last_end = max(row["plan_end"] for row in planned)
                    ScheduleCapacityRepository.update_order_summary(order_id, first_start, last_end, txn)
                revision_payload = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                revision_digest = hashlib.sha256(revision_payload.encode("utf-8")).hexdigest()
                ScheduleCapacityRepository.set_revision_digest(
                    revision_id, revision_digest, txn
                )
                risk_input = ScheduleCapacityRepository.find_schedule_risk_input(
                    order_id, db=txn
                )
                if risk_input is not None:
                    risk_row = dict(risk_input)
                    quantity = int(risk_row.get("quantity") or 0)
                    completed = int(risk_row.get("completed") or 0)
                    is_completed = risk_row.get("order_status") == "completed" or (
                        quantity > 0 and completed >= quantity
                    )
                    blocked_reasons = tuple(
                        reason.strip()
                        for reason in str(risk_row.get("blocked_reasons") or "").split("；")
                        if reason.strip()
                    )
                    risk_snapshot = ScheduleDeadlineRiskPolicy.evaluate(
                        deadline_text=risk_row.get("deadline") or "",
                        projected_completion_at=risk_row.get("projected_completion_at") or "",
                        plan_end=risk_row.get("plan_end") or "",
                        now=datetime.now(),
                        completed=is_completed,
                        blocked_count=risk_row.get("blocked_count") or 0,
                        blocked_reasons=blocked_reasons,
                        conflict_count=risk_row.get("conflict_count") or 0,
                    )
                    ScheduleCapacityRepository.set_revision_risk_snapshot(
                        revision_id,
                        risk_snapshot,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        txn,
                    )
                if not blocked:
                    ScheduleCapacityRepository.clear_schedule_replan_flag(order_id, txn)
                ScheduleCapacityRepository.complete_run(run_id, "completed", result, db=txn)
                txn.execute("RELEASE SAVEPOINT schedule_generation")
                response = {"ok": True, "order_id": order_id, "schedule_run_key": run_key,
                            "idempotent_replay": False, "status": "completed",
                            "schedule_revision_id": revision_id, "revision_status": "draft",
                            "operations": result}
            except Exception as exc:
                txn.execute("ROLLBACK TO SAVEPOINT schedule_generation")
                txn.execute("RELEASE SAVEPOINT schedule_generation")
                ScheduleCapacityRepository.cancel_revision(revision_id, txn)
                ScheduleCapacityRepository.complete_run(run_id, "failed", [], str(exc), db=txn)
                failure = str(exc)
        if failure:
            raise ValueError(failure)
        return response

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
    def _add_downtime_to_occupancy(occupancy, downtime, resource_key="process_line_id"):
        for event in downtime:
            event = dict(event)
            start = ScheduleCapacityService._parse_timestamp(event.get("start_at"))
            end = ScheduleCapacityService._parse_timestamp(event.get("end_at"))
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
    def _locked_task_conflict(lock, downtime, cursor, db):
        """Return an immutable conflict fact without moving the locked task."""
        start = ScheduleCapacityService._parse_timestamp(lock.get("planned_start_at"))
        end = ScheduleCapacityService._parse_timestamp(lock.get("planned_end_at"))
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
            event_start = ScheduleCapacityService._parse_timestamp(event.get("start_at"))
            event_end = ScheduleCapacityService._parse_timestamp(event.get("end_at"))
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
            override_start = ScheduleCapacityService._parse_timestamp(
                override.get("start_at")
            )
            override_end = ScheduleCapacityService._parse_timestamp(
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
    def dynamic_replan_order(order_id, start_at=None, schedule_run_key="", reason="", db=None,
                             actor_id=None):
        """Replan only unfinished work from approved facts and open rework.

        The existing projection is replaced transactionally, while the old
        schedule remains available through its immutable revision.  Completed
        operations are carried into the new revision as zero-quantity facts;
        only their remaining quantity (including pending rework) is allocated
        against free line minutes and active downtime intervals.
        """
        start = ScheduleCapacityService._replan_start(start_at)
        standard_as_of = start.strftime("%Y-%m-%d")
        reason = str(reason or "").strip()
        if len(reason) > 512:
            raise ValueError("重排原因不能超过 512 个字符")
        run_key = str(schedule_run_key or "").strip()
        if not run_key:
            raise ValueError("排程幂等键不能为空")
        response = None
        failure = None
        with ScheduleCapacityService._transaction(db) as txn:
            use_node_engine = bool(
                getattr(config, "PRODUCTION_NODE_ENGINE_ENABLED", False)
            )
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
            active_locks = ScheduleCapacityService._latest_locks_by_operation(
                active_lock_rows
            )
            # Resolve legacy orders to their immutable route/process bindings
            # before any new revision fact is written.
            if not ScheduleCapacityRepository.ensure_order_version_bindings(order_id, txn):
                raise ValueError("订单不存在")
            context = ScheduleCapacityRepository.dynamic_replan_order_context(
                order_id, db=txn, use_nodes=use_node_engine
            )
            if not context:
                raise ValueError("订单不存在")
            order = context["order"]
            order_serial_ids = ScheduleCapacityRepository.list_order_serial_ids(order_id, db=txn)
            prior_run = ScheduleCapacityRepository.find_run(run_key, txn)
            if prior_run:
                if prior_run["order_id"] != order_id:
                    raise ValueError("排程幂等键已被其他订单使用")
                revision = ScheduleCapacityRepository.find_revision_by_run(prior_run["id"], db=txn)
                replay_operations = ScheduleCapacityRepository.run_result(prior_run)
                return {
                    "ok": prior_run["status"] == "completed",
                    "order_id": order_id,
                    "schedule_run_key": run_key,
                    "idempotent_replay": True,
                    "status": prior_run["status"],
                    "error": prior_run["error_message"] or "",
                    "input_digest": prior_run["input_digest"] if "input_digest" in prior_run.keys() else "",
                    "schedule_revision_id": revision["id"] if revision else None,
                    "revision_status": revision["status"] if revision else None,
                    "operations": replay_operations,
                    "conflicts": [
                        {
                            key: item.get(key)
                            for key in (
                                "code", "revision_item_id",
                                "source_revision_item_id", "production_node_id",
                                "requires_manual_unlock", "reason", "conflict_type",
                                "downtime_event_id", "calendar_override_id",
                            )
                            if item.get(key) is not None
                        }
                        for item in replay_operations
                        if item.get("code") == "LOCKED_TASK_CONFLICT"
                    ],
                }

            snapshot, input_digest = ScheduleDynamicReplanPolicy.build_input_snapshot(
                order=order, operations=context["operations"], downtime=context["downtime"],
                occupancy=context["occupancy"], reason=reason,
                as_of=ScheduleCapacityService._format_timestamp(start),
                locked_tasks=list(active_locks.values()),
            )
            run_id = ScheduleCapacityRepository.create_run(
                order_id, run_key, start.strftime("%Y-%m-%d"), txn,
                run_type="dynamic_replan", trigger_source="production_facts",
                input_digest=input_digest, replan_reason=reason,
            )
            revision_id = ScheduleCapacityRepository.create_revision(
                order_id, run_id, run_key, txn, created_by=actor_id,
                replan_reason=reason, replan_source_digest=input_digest,
                replanned_at=ScheduleCapacityService._format_timestamp(start),
            )
            try:
                txn.execute("SAVEPOINT dynamic_schedule_replan")
                ScheduleCapacityRepository.clear_order_schedules(order_id, txn)
                occupancy = {}
                occupancy_rows = (
                    ProductionNodeRepository.list_node_occupancy(order_id, db=txn)
                    if use_node_engine
                    else ScheduleCapacityRepository.list_line_occupancy(order_id, txn)
                )
                occupancy_key = "production_node_id" if use_node_engine else "process_line_id"
                for row in occupancy_rows:
                    begin = ScheduleCapacityService._parse_timestamp(row["start_at"])
                    end = ScheduleCapacityService._parse_timestamp(row["end_at"])
                    resource_id = row[occupancy_key]
                    if resource_id is not None and begin and end and end > begin:
                        occupancy.setdefault(int(resource_id), []).append((begin, end))
                ScheduleCapacityService._add_downtime_to_occupancy(
                    occupancy, context["downtime"], resource_key=occupancy_key
                )
                if use_node_engine:
                    for lock in active_locks.values():
                        lock_start = ScheduleCapacityService._parse_timestamp(
                            lock.get("planned_start_at")
                        )
                        lock_end = ScheduleCapacityService._parse_timestamp(
                            lock.get("planned_end_at")
                        )
                        node_id = lock.get("production_node_id")
                        if (
                            node_id is not None and lock_start and lock_end
                            and lock_end > lock_start
                        ):
                            occupancy.setdefault(int(node_id), []).append(
                                (lock_start, lock_end)
                            )
                prior_by_op = {int(row["order_process_id"]): row for row in context["prior_schedules"]}
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
                        try:
                            locked_payload = json.loads(
                                locked_task.get("payload_json") or "{}"
                            )
                        except (TypeError, json.JSONDecodeError):
                            locked_payload = {}
                        segments = ScheduleCapacityService._locked_task_segments(
                            locked_task, locked_payload
                        )
                        allocations = ScheduleCapacityService._locked_task_allocations(
                            locked_payload
                        )
                        locked_start = ScheduleCapacityService._parse_timestamp(
                            locked_task.get("planned_start_at")
                        )
                        locked_end = ScheduleCapacityService._parse_timestamp(
                            locked_task.get("planned_end_at")
                        )
                        conflict = ScheduleCapacityService._locked_task_conflict(
                            locked_task, context["downtime"], cursor, txn
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
                                if locked_start else cursor.strftime("%Y-%m-%d")
                            ),
                            "plan_end": (
                                locked_end.strftime("%Y-%m-%d")
                                if locked_end else cursor.strftime("%Y-%m-%d")
                            ),
                            "occupied_minutes": float(
                                locked_task.get("occupied_minutes") or 0
                            ),
                            "planned_minutes": float(
                                locked_payload.get("planned_minutes")
                                or locked_task.get("occupied_minutes") or 0
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
                        new_item = ScheduleCapacityService._copy_active_lock_to_schedule(
                            locked_task, payload["id"], revision_id, txn
                        )
                        locked_result = {
                            **payload,
                            "line_name": payload.get("line_name_snapshot") or None,
                            "process_name": process_snapshot,
                            "locked": True,
                            "revision_item_id": new_item["id"],
                            "source_revision_item_id": locked_task["revision_item_id"],
                            "requires_manual_unlock": bool(conflict),
                            "reason": (
                                conflict["reason"] if conflict
                                else "锁定任务保留原生产节点和计划时间"
                            ),
                        }
                        if conflict:
                            blocked = True
                            locked_result.update({
                                "code": "LOCKED_TASK_CONFLICT",
                                "production_node_id": locked_task.get(
                                    "production_node_id"
                                ),
                                **conflict,
                            })
                            conflicts.append({
                                "code": "LOCKED_TASK_CONFLICT",
                                "revision_item_id": new_item["id"],
                                "source_revision_item_id": locked_task[
                                    "revision_item_id"
                                ],
                                "production_node_id": locked_task.get(
                                    "production_node_id"
                                ),
                                "requires_manual_unlock": True,
                                **conflict,
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
                            "planned_start_at": ScheduleCapacityService._format_timestamp(begin),
                            "planned_end_at": ScheduleCapacityService._format_timestamp(end),
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

                    standard = ScheduleCapacityService._find_standard(
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
                            segments, allocations = ScheduleCapacityService._allocate_split_on_nodes(
                                txn, resources, cursor, baseline["remaining_quantity"], standard, occupancy,
                                operation=operation, order=order,
                                serial_ids=serial_ids,
                                allocation_key_prefix=f"{order_id}:{operation['order_process_id']}",
                                return_allocations=True,
                            )
                        else:
                            segments = ScheduleCapacityService._allocate_split_on_lines(
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
                    begin = min(ScheduleCapacityService._parse_timestamp(item["start_at"]) for item in segments)
                    end = max(ScheduleCapacityService._parse_timestamp(item["end_at"]) for item in segments)
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
                        item = ScheduleCapacityService._calendar_snapshot(calendar, shifts)
                        item.update({
                            resource_key: resource_id,
                            "process_line_id": resource.get("legacy_process_line_id", resource_id),
                            "line_code": resource.get("line_code", resource.get("node_code", "")),
                            "line_name": resource.get("line_name", resource.get("node_name", "")),
                            "daily_minutes": float(resource.get("daily_minutes") or resource.get("capacity_minutes") or ScheduleCapacityService.DEFAULT_DAILY_MINUTES),
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
                        "planned_start_at": ScheduleCapacityService._format_timestamp(begin),
                        "planned_end_at": ScheduleCapacityService._format_timestamp(end),
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

                planned = [item for item in result if item.get("status") == "planned" and (item.get("process_line_id") or item.get("production_node_id"))]
                if planned:
                    ScheduleCapacityRepository.update_order_summary(
                        order_id, min(item["plan_start"] for item in planned), max(item["plan_end"] for item in planned), txn
                    )
                result_json = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                ScheduleCapacityRepository.set_revision_digest(
                    revision_id, hashlib.sha256(result_json.encode("utf-8")).hexdigest(), txn
                )
                if not blocked:
                    ScheduleCapacityRepository.clear_schedule_replan_flag(order_id, txn)
                ScheduleCapacityRepository.complete_run(run_id, "completed", result, db=txn)
                txn.execute("RELEASE SAVEPOINT dynamic_schedule_replan")
                response = {
                    "ok": True, "order_id": order_id, "schedule_run_key": run_key,
                    "idempotent_replay": False, "status": "completed", "input_digest": input_digest,
                    "schedule_revision_id": revision_id, "revision_status": "draft",
                    "replan_reason": reason, "input_snapshot": snapshot, "operations": result,
                    "conflicts": conflicts,
                }
            except Exception as exc:
                txn.execute("ROLLBACK TO SAVEPOINT dynamic_schedule_replan")
                txn.execute("RELEASE SAVEPOINT dynamic_schedule_replan")
                ScheduleCapacityRepository.cancel_revision(revision_id, txn)
                ScheduleCapacityRepository.complete_run(run_id, "failed", [], str(exc), db=txn)
                failure = str(exc)
        if failure:
            raise ValueError(failure)
        return response

    @staticmethod
    def list_downtime_events(production_node_id=None, process_line_id=None, start_at="",
                             end_at="", limit=1000, db=None):
        limit = ScheduleCapacityService._limit(limit, default=1000)
        if production_node_id not in (None, ""):
            if isinstance(production_node_id, bool):
                raise ValueError("生产节点参数不正确")
            try:
                production_node_id = int(production_node_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("生产节点参数不正确") from exc
            if production_node_id <= 0:
                raise ValueError("生产节点参数不正确")
            # Node-native filters take precedence when both are supplied.
            process_line_id = None
        elif process_line_id not in (None, ""):
            if isinstance(process_line_id, bool):
                raise ValueError("Legacy 产线参数不正确")
            try:
                process_line_id = int(process_line_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("Legacy 产线参数不正确") from exc
            if process_line_id <= 0:
                raise ValueError("Legacy 产线参数不正确")

        with ScheduleCapacityService._transaction(db) as txn:
            rows = [dict(row) for row in ScheduleCapacityRepository.list_downtime_events(
                process_line_id=process_line_id,
                production_node_id=production_node_id,
                start_at=start_at,
                end_at=end_at,
                limit=limit,
                db=txn,
            )]
            if (
                process_line_id not in (None, "")
                and bool(getattr(config, "PRODUCTION_NODE_COMPAT_AUDIT_ENABLED", False))
            ):
                mapped_node = ProductionNodeRepository.find_node_by_legacy_line_id(
                    process_line_id, db=txn
                )
                node_rows = []
                if mapped_node:
                    node_rows = [
                        dict(row)
                        for row in ScheduleCapacityRepository.list_downtime_events(
                            production_node_id=mapped_node["id"],
                            start_at=start_at,
                            end_at=end_at,
                            limit=limit,
                            db=txn,
                        )
                    ]

                def normalized(events):
                    return [
                        {
                            "id": int(item["id"]),
                            "start_at": item["start_at"],
                            "end_at": item["end_at"],
                            "reason": item.get("reason") or "",
                            "status": item.get("status") or "",
                        }
                        for item in events
                    ]

                legacy_payload = {"events": normalized(rows)}
                node_payload = {"events": normalized(node_rows)}
                ProductionNodeRepository.record_compatibility_observation(
                    scope="downtime_legacy_filter",
                    source_id=process_line_id,
                    legacy_payload=legacy_payload,
                    node_payload=node_payload,
                    difference={
                        "legacy_filter_used": True,
                        "process_line_id": process_line_id,
                        "production_node_id": mapped_node["id"] if mapped_node else None,
                        "legacy_event_ids": [item["id"] for item in legacy_payload["events"]],
                        "node_event_ids": [item["id"] for item in node_payload["events"]],
                    },
                    db=txn,
                )
        return {"ok": True, "events": rows}

    @staticmethod
    def create_downtime_event(production_node_id, start_at, end_at, reason="", created_by=None,
                              db=None):
        start = ScheduleCapacityService._parse_timestamp(start_at)
        end = ScheduleCapacityService._parse_timestamp(end_at)
        if not start or not end or end <= start:
            raise ValueError("停机开始和结束时间必须有效且结束时间晚于开始时间")
        reason = str(reason or "").strip()
        if len(reason) > 512:
            raise ValueError("停机原因不能超过 512 个字符")
        with ScheduleCapacityService._transaction(db) as txn:
            node = ProductionNodeService.resolve_downtime_target(
                production_node_id, txn
            )
            event_id = ScheduleCapacityRepository.create_downtime_event(
                node["legacy_process_line_id"],
                ScheduleCapacityService._format_timestamp(start),
                ScheduleCapacityService._format_timestamp(end), reason, created_by,
                production_node_id=node["id"], db=txn,
            )
            row = ScheduleCapacityRepository.find_downtime_event(event_id, db=txn)
        return {"ok": True, "event": dict(row)}

    @staticmethod
    def cancel_downtime_event(event_id):
        try:
            event_id = int(event_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("停机事件 ID 不正确") from exc
        with BaseService.transaction() as txn:
            if ScheduleCapacityRepository.cancel_downtime_event(event_id, db=txn) != 1:
                raise ValueError("停机事件不存在或已取消")
        return {"ok": True, "event_id": event_id, "status": "cancelled"}

    @staticmethod
    def list_order_schedule(order_id, limit=500):
        limit = ScheduleCapacityService._limit(limit)
        return {"ok": True, "order_id": order_id, "operations": [dict(row) for row in ScheduleCapacityRepository.find_order_operations(order_id, limit=limit)]}

    @staticmethod
    def list_order_revisions(order_id, limit=100):
        limit = ScheduleCapacityService._limit(limit, default=100)
        return {
            "ok": True,
            "order_id": order_id,
            "revisions": [dict(row) for row in ScheduleCapacityRepository.list_revisions(order_id, limit=limit)],
        }

    @staticmethod
    def get_revision(revision_id, limit=1000):
        limit = ScheduleCapacityService._limit(limit, default=1000)
        revision = ScheduleCapacityRepository.find_revision(revision_id)
        if revision is None:
            raise ValueError("排程版本不存在")
        return {
            "ok": True,
            "revision": dict(revision),
            "items": [dict(row) for row in ScheduleCapacityRepository.list_revision_items(revision_id, limit=limit)],
        }

    @staticmethod
    def _workflow_input(reason, idempotency_key, actor_id):
        reason = str(reason or "").strip()
        key = str(idempotency_key or "").strip()
        try:
            actor = int(actor_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("操作人不能为空") from exc
        if actor <= 0:
            raise ValueError("操作人不能为空")
        if not reason or len(reason) > 1024:
            raise ValueError("原因必须填写且不能超过 1024 个字符")
        if len(key) < 8 or len(key) > 128:
            raise ValueError("幂等键长度必须在 8 到 128 个字符之间")
        return reason, key, actor

    @staticmethod
    def _workflow_digest(payload):
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _workflow_replay(db, key, digest):
        event = ScheduleCapacityRepository.find_workflow_event(key, db=db)
        if event is None:
            return None
        if event["input_digest"] != digest:
            raise NodeSchedulingError(
                "IDEMPOTENCY_CONFLICT",
                "幂等键已被不同输入使用",
                {"idempotency_key": key},
            )
        try:
            result = json.loads(event["after_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            result = {}
        return {
            "ok": True,
            "idempotent_replay": True,
            "event": dict(event),
            "result": result,
        }

    @staticmethod
    def _record_workflow_event(db, *, revision_id, revision_item_id, event_type,
                               actor_id, reason, before, after, digest, key):
        before_json = json.dumps(
            before or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        after_json = json.dumps(
            after or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        event = ScheduleCapacityRepository.create_workflow_event(
            revision_id=revision_id,
            revision_item_id=revision_item_id,
            event_type=event_type,
            actor_id=actor_id,
            reason=reason,
            before_json=before_json,
            after_json=after_json,
            input_digest=digest,
            idempotency_key=key,
            db=db,
        )
        return {
            "ok": True,
            "idempotent_replay": False,
            "event": dict(event),
            "result": after,
        }

    @staticmethod
    def lock_schedule_item(revision_item_id, reason, idempotency_key, actor_id, db=None):
        reason, key, actor = ScheduleCapacityService._workflow_input(
            reason, idempotency_key, actor_id
        )
        payload = {"action": "lock", "revision_item_id": int(revision_item_id),
                   "reason": reason, "actor_id": actor}
        digest = ScheduleCapacityService._workflow_digest(payload)
        with ScheduleCapacityService._transaction(db) as txn:
            replay = ScheduleCapacityService._workflow_replay(txn, key, digest)
            if replay:
                return replay
            item = ScheduleCapacityRepository.find_revision_item(revision_item_id, db=txn)
            if item is None:
                raise ValueError("排程条目不存在")
            if item["revision_status"] in ("superseded", "cancelled"):
                raise NodeSchedulingError("REVISION_STATE_CONFLICT", "当前排程版本不可锁定")
            if item["production_node_id"] is None or item["status"] != "planned":
                raise NodeSchedulingError(
                    "NO_COMPATIBLE_NODE", "只有已分配内部生产节点的排程任务可锁定"
                )
            if ScheduleCapacityRepository.find_active_task_lock(revision_item_id, db=txn):
                raise NodeSchedulingError("LOCKED_TASK_CONFLICT", "排程条目已锁定")
            lock = ScheduleCapacityRepository.create_task_lock(
                revision_item_id, item["production_node_id"], actor, reason, txn
            )
            return ScheduleCapacityService._record_workflow_event(
                txn, revision_id=item["revision_id"], revision_item_id=revision_item_id,
                event_type="lock", actor_id=actor, reason=reason, before={},
                after={"lock": dict(lock)}, digest=digest, key=key,
            )

    @staticmethod
    def unlock_schedule_item(revision_item_id, reason, idempotency_key, actor_id, db=None):
        reason, key, actor = ScheduleCapacityService._workflow_input(
            reason, idempotency_key, actor_id
        )
        payload = {"action": "unlock", "revision_item_id": int(revision_item_id),
                   "reason": reason, "actor_id": actor}
        digest = ScheduleCapacityService._workflow_digest(payload)
        with ScheduleCapacityService._transaction(db) as txn:
            replay = ScheduleCapacityService._workflow_replay(txn, key, digest)
            if replay:
                return replay
            item = ScheduleCapacityRepository.find_revision_item(revision_item_id, db=txn)
            if item is None:
                raise ValueError("排程条目不存在")
            active_lock = ScheduleCapacityRepository.find_active_task_lock(
                revision_item_id, db=txn
            )
            if active_lock is None:
                raise NodeSchedulingError("LOCKED_TASK_CONFLICT", "排程条目当前未锁定")
            ScheduleCapacityRepository.release_task_lock(
                revision_item_id, actor, reason, txn
            )
            return ScheduleCapacityService._record_workflow_event(
                txn, revision_id=item["revision_id"], revision_item_id=revision_item_id,
                event_type="unlock", actor_id=actor, reason=reason,
                before={"lock": dict(active_lock)}, after={"status": "released"},
                digest=digest, key=key,
            )

    @staticmethod
    def adjust_schedule_item(revision_item_id, production_node_id, planned_start_at,
                             reason, row_version, idempotency_key, actor_id, db=None):
        reason, key, actor = ScheduleCapacityService._workflow_input(
            reason, idempotency_key, actor_id
        )
        try:
            revision_item_id = int(revision_item_id)
            node_id = int(production_node_id)
            expected_row_version = int(row_version)
        except (TypeError, ValueError) as exc:
            raise ValueError("排程条目、生产节点和行版本必须为正整数") from exc
        start = ScheduleCapacityService._parse_timestamp(planned_start_at)
        if start is None:
            raise ValueError("计划开始时间格式不正确")
        payload = {
            "action": "adjust", "revision_item_id": revision_item_id,
            "production_node_id": node_id,
            "planned_start_at": ScheduleCapacityService._format_timestamp(start),
            "row_version": expected_row_version, "reason": reason, "actor_id": actor,
        }
        digest = ScheduleCapacityService._workflow_digest(payload)
        with ScheduleCapacityService._transaction(db) as txn:
            replay = ScheduleCapacityService._workflow_replay(txn, key, digest)
            if replay:
                return replay
            item = ScheduleCapacityRepository.find_revision_item(revision_item_id, db=txn)
            if item is None:
                raise ValueError("排程条目不存在")
            if int(item["row_version"] or 1) != expected_row_version:
                raise NodeSchedulingError(
                    "ROW_VERSION_CONFLICT", "排程条目已被其他操作修改",
                    {"expected": expected_row_version, "actual": item["row_version"]},
                )
            if item["revision_status"] not in ("draft", "published"):
                raise NodeSchedulingError("REVISION_STATE_CONFLICT", "当前排程版本不可调整")
            if item["revision_status"] == "draft" and item["approval_status"] not in ("draft", "rejected"):
                raise NodeSchedulingError("REVISION_STATE_CONFLICT", "已提交审批的排程版本不可调整")
            if ScheduleCapacityRepository.find_active_task_lock(revision_item_id, db=txn):
                raise NodeSchedulingError("LOCKED_TASK_CONFLICT", "锁定排程条目不能移动")
            node = ProductionNodeRepository.find_node(node_id, db=txn)
            if node is None or node.get("status") != "active" or node.get("process_id") != item["process_id"]:
                raise NodeSchedulingError("NO_COMPATIBLE_NODE", "生产节点与排程工序不匹配")
            source_schedule = ScheduleCapacityRepository.find_schedule(
                item["source_schedule_id"], db=txn
            )
            order = ScheduleCapacityRepository.find_order(item["order_id"], txn)
            if source_schedule is None or order is None:
                raise ValueError("排程来源事实不存在")
            operation = dict(source_schedule)
            policy_order = dict(order)
            policy_order["process_version_id"] = operation.get("process_version_id")
            standard = ScheduleCapacityRepository.find_standard(
                operation.get("standard_id"), db=txn
            )
            capabilities = ProductionNodeRepository.list_capabilities(node_id, db=txn)
            ProductionNodePolicy.validate_node(
                node=node, capabilities=capabilities, operation=operation,
                order=policy_order, standard=dict(standard) if standard else None,
                quantity=max(int(item["quantity"] or 0), 1),
            )
            calendar = ScheduleCapacityRepository.get_calendar(node["calendar_id"], db=txn)
            shifts = ScheduleCapacityRepository.list_calendar_shifts(node["calendar_id"], db=txn)
            if calendar is None or not shifts:
                raise NodeSchedulingError("NODE_CALENDAR_UNAVAILABLE", "生产节点日历没有可用时间")
            occupied = []
            for row in ScheduleCapacityRepository.list_node_occupancy_for_adjustment(
                node_id, item["source_schedule_id"], db=txn
            ):
                occupied.append({
                    "id": f"{row['fact_type']}:{row['id']}",
                    "production_node_id": node_id,
                    "start_at": row["start_at"],
                    "end_at": row["end_at"],
                    "locked": bool(row["locked"]),
                })
            for override in ProductionNodeRepository.list_node_calendar_overrides(
                node_id, db=txn
            ):
                if override["override_type"] != "overtime":
                    occupied.append({
                        "id": f"calendar_override:{override['id']}",
                        "production_node_id": node_id,
                        "start_at": override["start_at"],
                        "end_at": override["end_at"],
                        "locked": False,
                    })
            duration = max(float(item["occupied_minutes"] or 0), 1.0)
            segments = ScheduleCapacityService._allocate_on_line(
                txn, calendar, shifts, None, start, duration, []
            )
            if not segments or ScheduleCapacityService._parse_timestamp(segments[0]["start_at"]) != start:
                raise NodeSchedulingError("NODE_CALENDAR_UNAVAILABLE", "指定开始时间不在生产节点可用日历内")
            for segment in segments:
                ProductionNodePolicy.validate_node(
                    node=node,
                    capabilities=capabilities,
                    operation=operation,
                    order=policy_order,
                    standard=dict(standard) if standard else None,
                    requested_start_at=segment["start_at"],
                    requested_end_at=segment["end_at"],
                    calendar_intervals=[segment],
                    calendar_available=True,
                    occupancy=occupied,
                    quantity=max(int(item["quantity"] or 0), 1),
                    batch_orders=[item["order_id"]],
                )
            end = ScheduleCapacityService._parse_timestamp(segments[-1]["end_at"])
            segment_payload = [
                {
                    **segment,
                    "production_node_id": node_id,
                    "process_line_id": node.get("legacy_process_line_id"),
                }
                for segment in segments
            ]
            try:
                source_payload = json.loads(item["payload_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                source_payload = {}
            source_payload.update({
                "production_node_id": node_id,
                "process_line_id": node.get("legacy_process_line_id"),
                "node_code_snapshot": node.get("node_code") or "",
                "node_name_snapshot": node.get("node_name") or "",
                "capacity_mode_snapshot": node.get("capacity_mode") or "",
                "planned_start_at": ScheduleCapacityService._format_timestamp(start),
                "planned_end_at": ScheduleCapacityService._format_timestamp(end),
                "plan_start": start.strftime("%Y-%m-%d"),
                "plan_end": end.strftime("%Y-%m-%d"),
                "segments": segment_payload,
            })
            encoded_payload = json.dumps(
                source_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            new_revision_id, item_map = ScheduleCapacityRepository.clone_revision_with_override(
                item["revision_id"], override_item_id=revision_item_id,
                overrides={
                    "production_node_id": node_id,
                    "process_line_id": node.get("legacy_process_line_id"),
                    "node_code_snapshot": node.get("node_code") or "",
                    "node_name_snapshot": node.get("node_name") or "",
                    "capacity_mode_snapshot": node.get("capacity_mode") or "",
                    "planned_start_at": ScheduleCapacityService._format_timestamp(start),
                    "planned_end_at": ScheduleCapacityService._format_timestamp(end),
                    "payload_json": encoded_payload,
                    "payload_digest": hashlib.sha256(encoded_payload.encode("utf-8")).hexdigest(),
                },
                created_by=actor, reason=reason, db=txn,
            )
            new_item_id = item_map[revision_item_id]
            after = {
                "source_revision_id": item["revision_id"],
                "revision_id": new_revision_id,
                "revision_item_id": new_item_id,
                "production_node_id": node_id,
                "planned_start_at": ScheduleCapacityService._format_timestamp(start),
                "planned_end_at": ScheduleCapacityService._format_timestamp(end),
                "approval_status": "draft",
            }
            return ScheduleCapacityService._record_workflow_event(
                txn, revision_id=new_revision_id, revision_item_id=new_item_id,
                event_type="adjust", actor_id=actor, reason=reason,
                before={"revision_id": item["revision_id"], "revision_item_id": revision_item_id},
                after=after, digest=digest, key=key,
            )

    @staticmethod
    def _transition_revision(revision_id, target_status, reason, idempotency_key,
                             actor_id, db=None):
        reason, key, actor = ScheduleCapacityService._workflow_input(
            reason, idempotency_key, actor_id
        )
        try:
            revision_id = int(revision_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("排程版本 ID 不正确") from exc
        payload = {"action": target_status, "revision_id": revision_id,
                   "reason": reason, "actor_id": actor}
        digest = ScheduleCapacityService._workflow_digest(payload)
        with ScheduleCapacityService._transaction(db) as txn:
            replay = ScheduleCapacityService._workflow_replay(txn, key, digest)
            if replay:
                return replay
            revision = ScheduleCapacityRepository.find_revision(revision_id, db=txn)
            if revision is None:
                raise ValueError("排程版本不存在")
            if revision["status"] != "draft":
                raise NodeSchedulingError("REVISION_STATE_CONFLICT", "只有草稿排程版本可执行审批流程")
            current = revision["approval_status"]
            expected = {
                "submitted": ("draft", "rejected"),
                "approved": ("submitted",),
                "rejected": ("submitted",),
            }[target_status]
            if current not in expected:
                raise NodeSchedulingError(
                    "REVISION_STATE_CONFLICT", "排程版本审批状态不允许当前操作",
                    {"approval_status": current, "target_status": target_status},
                )
            if target_status == "approved" and revision["created_by"] == actor:
                raise NodeSchedulingError(
                    "INDEPENDENT_APPROVER_REQUIRED", "排程版本创建人不能批准自己的版本"
                )
            changed = ScheduleCapacityRepository.transition_revision(
                revision_id, current, target_status, actor, reason, txn
            )
            if changed != 1:
                raise NodeSchedulingError("REVISION_STATE_CONFLICT", "排程版本状态已发生变化")
            after_revision = dict(ScheduleCapacityRepository.find_revision(revision_id, db=txn))
            return ScheduleCapacityService._record_workflow_event(
                txn, revision_id=revision_id, revision_item_id=None,
                event_type={"submitted": "submit", "approved": "approve", "rejected": "reject"}[target_status],
                actor_id=actor, reason=reason,
                before={"approval_status": current}, after=after_revision,
                digest=digest, key=key,
            )

    @staticmethod
    def submit_revision(revision_id, reason, idempotency_key, actor_id, db=None):
        return ScheduleCapacityService._transition_revision(
            revision_id, "submitted", reason, idempotency_key, actor_id, db=db
        )

    @staticmethod
    def approve_revision(revision_id, reason, idempotency_key, actor_id, db=None):
        return ScheduleCapacityService._transition_revision(
            revision_id, "approved", reason, idempotency_key, actor_id, db=db
        )

    @staticmethod
    def reject_revision(revision_id, reason, idempotency_key, actor_id, db=None):
        return ScheduleCapacityService._transition_revision(
            revision_id, "rejected", reason, idempotency_key, actor_id, db=db
        )

    @staticmethod
    def publish_revision(revision_id, published_by=None, db=None):
        with ScheduleCapacityService._transaction(db) as txn:
            revision = ScheduleCapacityRepository.find_revision(revision_id, db=txn)
            if revision is None:
                raise ValueError("排程版本不存在")
            if revision["status"] not in ("draft", "published"):
                raise NodeSchedulingError(
                    "REVISION_STATE_CONFLICT",
                    "排程版本当前状态不可发布",
                    {
                        "revision_id": revision_id,
                        "status": revision["status"],
                    },
                )
            if revision["approval_status"] != "approved":
                raise NodeSchedulingError(
                    "REVISION_STATE_CONFLICT",
                    "排程版本必须先经独立审批后才能发布",
                    {
                        "revision_id": revision_id,
                        "approval_status": revision["approval_status"],
                    },
                )
            ScheduleCapacityRepository.publish_revision(revision_id, txn, published_by=published_by)
            published = ScheduleCapacityRepository.find_revision(revision_id, db=txn)
            return {"ok": True, "revision": dict(published)}

    @staticmethod
    def list_schedules(limit=500):
        limit = ScheduleCapacityService._limit(limit)
        operations = [
            dict(row)
            for row in ScheduleCapacityRepository.list_scheduled_operations(limit)
        ]
        allocations_by_schedule = {}
        for row in ScheduleCapacityRepository.list_schedule_allocations(
            [operation.get("id") for operation in operations]
        ):
            allocation = dict(row)
            allocations_by_schedule.setdefault(allocation["schedule_id"], []).append(
                allocation
            )
        for operation in operations:
            # V089 stores a legacy schedule-level ``locked`` flag and also
            # exposes the active revision-item lock through ``task_lock_id``.
            # SQLite rows keep the first duplicate column name from ``s.*``,
            # so normalize both sources here for old and versioned schedules.
            operation["locked"] = bool(
                operation.get("locked") or operation.get("task_lock_id")
            )
            operation["allocations"] = allocations_by_schedule.get(
                operation.get("id"), []
            )
        return {"ok": True, "operations": operations}

    @staticmethod
    def audit_schedule_capacity(limit=1000, now=None):
        """Summarize persisted precision facts and detect line overlaps."""
        limit = ScheduleCapacityService._limit(limit)
        rows = [dict(row) for row in ScheduleCapacityRepository.list_scheduled_operations(limit)]
        planned = [row for row in rows if row.get("status") == "planned"]
        blocked = [row for row in rows if row.get("status") == "blocked"]
        conflicts = [dict(row) for row in ScheduleCapacityRepository.list_schedule_conflicts()]
        line_loads = [dict(row) for row in ScheduleCapacityRepository.list_line_loads()]
        conflict_counts = Counter(row.get("process_line_id") for row in conflicts)
        for line in line_loads:
            line["conflict_count"] = conflict_counts.get(line.get("process_line_id"), 0)
        risk_orders = []
        risk_counts = Counter()
        for raw_row in ScheduleCapacityRepository.list_schedule_risk_inputs(limit=limit):
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
            "conflicts": conflicts[:limit],
            "line_loads": line_loads,
            "calendars": ScheduleCapacityRepository.list_calendars(),
        }
