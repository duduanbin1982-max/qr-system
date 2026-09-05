"""工序级、多产线、工时驱动的排程策略。"""

import hashlib
import json
import math
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta

from modules.services import BaseService
from modules.domain.schedule_deadline_risk import ScheduleDeadlineRiskPolicy
from modules.domain.schedule_dynamic_replan import ScheduleDynamicReplanPolicy
from modules.repositories.schedule_capacity_repository import ScheduleCapacityRepository


class ScheduleCapacityService:
    DEFAULT_DAILY_MINUTES = 480

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
    def list_schedulable_orders(limit=500):
        limit = ScheduleCapacityService._limit(limit)
        return {"ok": True, "orders": [dict(row) for row in ScheduleCapacityRepository.list_schedulable_orders(limit)]}

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
        remaining = float(duration)
        segments = []
        epsilon = 1e-7
        intervals = ScheduleCapacityService._merge_intervals(occupied)
        for slot in ScheduleCapacityService._calendar_slots(
            db, calendar, shifts, earliest, daily_minutes=daily_minutes
        ):
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
    def generate_order_schedule(order_id, start_date=None, schedule_run_key="", db=None):
        failure = None
        response = None
        with ScheduleCapacityService._transaction(db) as txn:
            order = ScheduleCapacityRepository.ensure_order_version_bindings(order_id, txn)
            if not order:
                raise ValueError("订单不存在")
            operations = ScheduleCapacityRepository.find_order_operations(order_id, db=txn)
            if not operations:
                raise ValueError("订单没有工序，无法生成排程")
            cursor = ScheduleCapacityService._date(start_date or order["plan_start"], "计划开始日期")
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
                order_id, run_id, run_key, txn,
            )
            try:
                # Keep the run ledger even if scheduling fails halfway through.
                txn.execute("SAVEPOINT schedule_generation")
                ScheduleCapacityRepository.clear_order_schedules(order_id, txn)
                occupancy = {}
                for row in ScheduleCapacityRepository.list_line_occupancy(order_id, txn):
                    start_at = ScheduleCapacityService._parse_timestamp(row["start_at"])
                    end_at = ScheduleCapacityService._parse_timestamp(row["end_at"])
                    if start_at and end_at and end_at > start_at:
                        occupancy.setdefault(row["process_line_id"], []).append((start_at, end_at))
                result = []
                blocked = False
                for operation in operations:
                    route_version_id = operation["route_version_id"]
                    process_version_id = operation["process_version_id"]
                    process_snapshot = operation["process_name_snapshot"] or operation["process_name"] or ""
                    route_snapshot = operation["route_name_snapshot"] or order["route_name_snapshot"] or ""
                    common = {"order_id": order_id, "order_process_id": operation["order_process_id"],
                              "process_id": operation["process_id"], "seq_order": operation["seq_order"],
                              "quantity": order["quantity"], "route_version_id": route_version_id,
                              "process_version_id": process_version_id, "process_name_snapshot": process_snapshot,
                              "route_name_snapshot": route_snapshot, "schedule_run_key": run_key,
                              "schedule_run_id": run_id, "schedule_revision_id": revision_id}
                    if blocked:
                        payload = {**common, "process_line_id": None, "standard_id": None, "standard_version": None,
                                   "standard_minutes_per_unit": 0, "setup_minutes": 0, "difficulty_factor": 1,
                                   "planned_minutes": 0, "plan_start": cursor.strftime("%Y-%m-%d"),
                                   "plan_end": cursor.strftime("%Y-%m-%d"), "status": "blocked",
                                   "blocked_reason": "前序工序无法排程"}
                        payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                        result.append({**payload, "line_name": None, "process_name": process_snapshot,
                                       "reason": payload["blocked_reason"]})
                        continue

                    standard = ScheduleCapacityService._find_standard(
                        txn, order["route_id"], route_version_id, operation["process_id"],
                        process_version_id, order["product_id"], order["product_code"],
                        cursor.strftime("%Y-%m-%d"),
                    )
                    lines = [line for line in ScheduleCapacityRepository.list_process_lines(operation["process_id"], db=txn)
                             if line["status"] == "active"]
                    if not standard:
                        blocked = True
                        payload = {**common, "process_line_id": None, "standard_id": None, "standard_version": None,
                                   "standard_minutes_per_unit": 0, "setup_minutes": 0, "difficulty_factor": 1,
                                   "planned_minutes": 0, "plan_start": cursor.strftime("%Y-%m-%d"),
                                   "plan_end": cursor.strftime("%Y-%m-%d"), "status": "blocked",
                                   "blocked_reason": "未配置标准工时"}
                        payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                        result.append({**payload, "line_name": None, "process_name": process_snapshot,
                                       "reason": payload["blocked_reason"]})
                        continue
                    if not lines:
                        blocked = True
                        payload = {**common, "process_line_id": None, "standard_id": standard["id"],
                                   "standard_version": standard["version"],
                                   "standard_minutes_per_unit": standard["standard_minutes_per_unit"],
                                   "setup_minutes": standard["setup_minutes"], "difficulty_factor": standard["difficulty_factor"],
                                   "planned_minutes": 0, "plan_start": cursor.strftime("%Y-%m-%d"),
                                   "plan_end": cursor.strftime("%Y-%m-%d"), "status": "blocked",
                                   "blocked_reason": "工序未配置可用产线"}
                        payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                        result.append({**payload, "line_name": None, "process_name": process_snapshot,
                                       "reason": payload["blocked_reason"]})
                        continue

                    try:
                        segments = ScheduleCapacityService._allocate_split_on_lines(
                            txn, lines, cursor, order["quantity"], standard, occupancy,
                        )
                    except ValueError as exc:
                        blocked = True
                        payload = {**common, "process_line_id": None, "standard_id": standard["id"],
                                   "standard_version": standard["version"],
                                   "standard_minutes_per_unit": standard["standard_minutes_per_unit"],
                                   "setup_minutes": standard["setup_minutes"], "difficulty_factor": standard["difficulty_factor"],
                                   "planned_minutes": 0, "plan_start": cursor.strftime("%Y-%m-%d"),
                                   "plan_end": cursor.strftime("%Y-%m-%d"), "status": "blocked",
                                   "blocked_reason": str(exc) or "未配置有效工作日历或班次"}
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
                    line_ids = sorted({segment["process_line_id"] for segment in segments})
                    line_by_id = {line["id"]: line for line in lines}
                    primary_line = max(
                        line_ids,
                        key=lambda line_id: (
                            sum(float(segment["occupied_minutes"]) for segment in segments
                                if segment["process_line_id"] == line_id),
                            -line_id,
                        ),
                    )
                    line_snapshots = []
                    for line_id in line_ids:
                        line = line_by_id[line_id]
                        calendar = ScheduleCapacityRepository.get_calendar(
                            line["calendar_id"], db=txn
                        ) or ScheduleCapacityRepository.get_calendar(db=txn)
                        shifts = ScheduleCapacityRepository.list_calendar_shifts(
                            calendar["id"], db=txn
                        ) if calendar else []
                        snapshot = ScheduleCapacityService._calendar_snapshot(calendar, shifts)
                        snapshot.update({
                            "process_line_id": line_id,
                            "line_code": line["line_code"],
                            "line_name": line["line_name"],
                            "daily_minutes": float(line["daily_minutes"] or ScheduleCapacityService.DEFAULT_DAILY_MINUTES),
                            "quantity": sum(
                                int(segment.get("quantity") or 0)
                                for segment in segments if segment["process_line_id"] == line_id
                            ),
                        })
                        line_snapshots.append(snapshot)
                    primary_snapshot = next(item for item in line_snapshots if item["process_line_id"] == primary_line)
                    total_duration = sum(float(segment["occupied_minutes"]) for segment in segments)
                    capacity_snapshot = {
                        **primary_snapshot,
                        "line_count": len(line_snapshots),
                        "lines": line_snapshots,
                    }
                    payload = {**common, "process_line_id": primary_line, "standard_id": standard["id"],
                               "standard_version": standard["version"],
                               "standard_minutes_per_unit": standard["standard_minutes_per_unit"],
                               "setup_minutes": standard["setup_minutes"], "difficulty_factor": standard["difficulty_factor"],
                               "planned_minutes": total_duration, "occupied_minutes": total_duration, "status": "planned",
                               "standard_match_scope": standard["match_scope"],
                               "planned_start_at": ScheduleCapacityService._format_timestamp(begin),
                               "planned_end_at": ScheduleCapacityService._format_timestamp(end),
                               "capacity_snapshot_json": json.dumps(capacity_snapshot, ensure_ascii=False, sort_keys=True),
                               "shift_snapshot_json": json.dumps(
                                   [shift for snapshot in line_snapshots for shift in snapshot["shifts"]],
                                   ensure_ascii=False, sort_keys=True,
                               ),
                               "calendar_id": primary_snapshot["calendar_id"],
                               "line_name_snapshot": primary_snapshot["line_name"],
                               "segments": segments,
                               "plan_start": begin.strftime("%Y-%m-%d"), "plan_end": end.strftime("%Y-%m-%d")}
                    payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                    cursor = end
                    result.append({**payload, "line_name": primary_snapshot["line_name"],
                                   "line_count": len(line_snapshots), "lines": line_snapshots,
                                   "process_name": process_snapshot})
                planned = [row for row in result if row.get("status") == "planned" and row.get("process_line_id")]
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
    def _add_downtime_to_occupancy(occupancy, downtime):
        for event in downtime:
            start = ScheduleCapacityService._parse_timestamp(event.get("start_at"))
            end = ScheduleCapacityService._parse_timestamp(event.get("end_at"))
            if not start or not end or end <= start:
                continue
            occupancy.setdefault(int(event["process_line_id"]), []).append((start, end))

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
        reason = str(reason or "").strip()
        if len(reason) > 512:
            raise ValueError("重排原因不能超过 512 个字符")
        run_key = str(schedule_run_key or "").strip()
        if not run_key:
            raise ValueError("排程幂等键不能为空")
        response = None
        failure = None
        with ScheduleCapacityService._transaction(db) as txn:
            # Resolve legacy orders to their immutable route/process bindings
            # before any new revision fact is written.
            if not ScheduleCapacityRepository.ensure_order_version_bindings(order_id, txn):
                raise ValueError("订单不存在")
            context = ScheduleCapacityRepository.dynamic_replan_order_context(order_id, db=txn)
            if not context:
                raise ValueError("订单不存在")
            order = context["order"]
            prior_run = ScheduleCapacityRepository.find_run(run_key, txn)
            if prior_run:
                if prior_run["order_id"] != order_id:
                    raise ValueError("排程幂等键已被其他订单使用")
                revision = ScheduleCapacityRepository.find_revision_by_run(prior_run["id"], db=txn)
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
                    "operations": ScheduleCapacityRepository.run_result(prior_run),
                }

            snapshot, input_digest = ScheduleDynamicReplanPolicy.build_input_snapshot(
                order=order, operations=context["operations"], downtime=context["downtime"],
                occupancy=context["occupancy"], reason=reason,
                as_of=ScheduleCapacityService._format_timestamp(start),
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
                for row in ScheduleCapacityRepository.list_line_occupancy(order_id, txn):
                    begin = ScheduleCapacityService._parse_timestamp(row["start_at"])
                    end = ScheduleCapacityService._parse_timestamp(row["end_at"])
                    if begin and end and end > begin:
                        occupancy.setdefault(int(row["process_line_id"]), []).append((begin, end))
                ScheduleCapacityService._add_downtime_to_occupancy(occupancy, context["downtime"])
                prior_by_op = {int(row["order_process_id"]): row for row in context["prior_schedules"]}
                result = []
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
                    if blocked:
                        payload = {
                            **common, "process_line_id": None, "standard_id": None, "standard_version": None,
                            "standard_minutes_per_unit": 0, "setup_minutes": 0, "difficulty_factor": 1,
                            "planned_minutes": 0, "occupied_minutes": 0,
                            "plan_start": cursor.strftime("%Y-%m-%d"), "plan_end": cursor.strftime("%Y-%m-%d"),
                            "planned_start_at": "", "planned_end_at": "", "status": "blocked",
                            "blocked_reason": "前序工序无法重排", "line_name_snapshot": "", "segments": [],
                        }
                        payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                        result.append({**payload, "line_name": None, "process_name": process_snapshot,
                                       "reason": payload["blocked_reason"]})
                        continue

                    standard = ScheduleCapacityService._find_standard(
                        txn, order.get("route_id"), operation.get("route_version_id") or order.get("route_version_id"),
                        operation["process_id"], operation.get("process_version_id"), order.get("product_id"),
                        order.get("product_code"), cursor.strftime("%Y-%m-%d"),
                    )
                    lines = [line for line in ScheduleCapacityRepository.list_process_lines(operation["process_id"], db=txn)
                             if line["status"] == "active"]
                    if not standard:
                        blocked = True
                        block_reason = "未配置标准工时"
                        payload = {
                            **common, "process_line_id": None, "standard_id": None, "standard_version": None,
                            "standard_minutes_per_unit": 0, "setup_minutes": 0, "difficulty_factor": 1,
                            "planned_minutes": 0, "occupied_minutes": 0,
                            "plan_start": cursor.strftime("%Y-%m-%d"), "plan_end": cursor.strftime("%Y-%m-%d"),
                            "planned_start_at": "", "planned_end_at": "", "status": "blocked",
                            "blocked_reason": block_reason, "line_name_snapshot": "", "segments": [],
                        }
                        payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                        result.append({**payload, "line_name": None, "process_name": process_snapshot,
                                       "reason": block_reason})
                        continue
                    if not lines:
                        blocked = True
                        block_reason = "工序未配置可用产线"
                        payload = {
                            **common, "process_line_id": None, "standard_id": standard["id"],
                            "standard_version": standard["version"],
                            "standard_minutes_per_unit": standard["standard_minutes_per_unit"],
                            "setup_minutes": standard["setup_minutes"], "difficulty_factor": standard["difficulty_factor"],
                            "planned_minutes": 0, "occupied_minutes": 0,
                            "plan_start": cursor.strftime("%Y-%m-%d"), "plan_end": cursor.strftime("%Y-%m-%d"),
                            "planned_start_at": "", "planned_end_at": "", "status": "blocked",
                            "blocked_reason": block_reason, "line_name_snapshot": "", "segments": [],
                        }
                        payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                        result.append({**payload, "line_name": None, "process_name": process_snapshot,
                                       "reason": block_reason})
                        continue
                    try:
                        segments = ScheduleCapacityService._allocate_split_on_lines(
                            txn, lines, cursor, baseline["remaining_quantity"], standard, occupancy,
                        )
                    except ValueError as exc:
                        blocked = True
                        block_reason = str(exc) or "工作日历没有足够产能"
                        payload = {
                            **common, "process_line_id": None, "standard_id": standard["id"],
                            "standard_version": standard["version"],
                            "standard_minutes_per_unit": standard["standard_minutes_per_unit"],
                            "setup_minutes": standard["setup_minutes"], "difficulty_factor": standard["difficulty_factor"],
                            "planned_minutes": 0, "occupied_minutes": 0,
                            "plan_start": cursor.strftime("%Y-%m-%d"), "plan_end": cursor.strftime("%Y-%m-%d"),
                            "planned_start_at": "", "planned_end_at": "", "status": "blocked",
                            "blocked_reason": block_reason, "line_name_snapshot": "", "segments": [],
                        }
                        payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                        result.append({**payload, "line_name": None, "process_name": process_snapshot,
                                       "reason": block_reason})
                        continue
                    begin = min(ScheduleCapacityService._parse_timestamp(item["start_at"]) for item in segments)
                    end = max(ScheduleCapacityService._parse_timestamp(item["end_at"]) for item in segments)
                    line_ids = sorted({item["process_line_id"] for item in segments})
                    line_by_id = {line["id"]: line for line in lines}
                    primary_line = max(
                        line_ids,
                        key=lambda line_id: (
                            sum(float(item["occupied_minutes"]) for item in segments if item["process_line_id"] == line_id),
                            -line_id,
                        ),
                    )
                    snapshots = []
                    for line_id in line_ids:
                        line = line_by_id[line_id]
                        calendar = ScheduleCapacityRepository.get_calendar(line["calendar_id"], db=txn) or ScheduleCapacityRepository.get_calendar(db=txn)
                        shifts = ScheduleCapacityRepository.list_calendar_shifts(calendar["id"], db=txn) if calendar else []
                        item = ScheduleCapacityService._calendar_snapshot(calendar, shifts)
                        item.update({
                            "process_line_id": line_id, "line_code": line["line_code"], "line_name": line["line_name"],
                            "daily_minutes": float(line["daily_minutes"] or ScheduleCapacityService.DEFAULT_DAILY_MINUTES),
                            "quantity": sum(int(segment.get("quantity") or 0) for segment in segments if segment["process_line_id"] == line_id),
                        })
                        snapshots.append(item)
                    primary_snapshot = next(item for item in snapshots if item["process_line_id"] == primary_line)
                    duration = sum(float(item["occupied_minutes"]) for item in segments)
                    payload = {
                        **common, "process_line_id": primary_line, "standard_id": standard["id"],
                        "standard_version": standard["version"],
                        "standard_minutes_per_unit": standard["standard_minutes_per_unit"],
                        "setup_minutes": standard["setup_minutes"], "difficulty_factor": standard["difficulty_factor"],
                        "planned_minutes": duration, "occupied_minutes": duration, "status": "planned",
                        "standard_match_scope": standard["match_scope"],
                        "planned_start_at": ScheduleCapacityService._format_timestamp(begin),
                        "planned_end_at": ScheduleCapacityService._format_timestamp(end),
                        "capacity_snapshot_json": json.dumps({**primary_snapshot, "line_count": len(snapshots), "lines": snapshots}, ensure_ascii=False, sort_keys=True),
                        "shift_snapshot_json": json.dumps([shift for item in snapshots for shift in item["shifts"]], ensure_ascii=False, sort_keys=True),
                        "calendar_id": primary_snapshot["calendar_id"], "line_name_snapshot": primary_snapshot["line_name"],
                        "segments": segments, "plan_start": begin.strftime("%Y-%m-%d"), "plan_end": end.strftime("%Y-%m-%d"),
                    }
                    payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                    cursor = end
                    result.append({**payload, "line_name": primary_snapshot["line_name"], "line_count": len(snapshots),
                                   "lines": snapshots, "process_name": process_snapshot})

                planned = [item for item in result if item.get("status") == "planned" and item.get("process_line_id")]
                if planned:
                    ScheduleCapacityRepository.update_order_summary(
                        order_id, min(item["plan_start"] for item in planned), max(item["plan_end"] for item in planned), txn
                    )
                result_json = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                ScheduleCapacityRepository.set_revision_digest(
                    revision_id, hashlib.sha256(result_json.encode("utf-8")).hexdigest(), txn
                )
                ScheduleCapacityRepository.complete_run(run_id, "completed", result, db=txn)
                txn.execute("RELEASE SAVEPOINT dynamic_schedule_replan")
                response = {
                    "ok": True, "order_id": order_id, "schedule_run_key": run_key,
                    "idempotent_replay": False, "status": "completed", "input_digest": input_digest,
                    "schedule_revision_id": revision_id, "revision_status": "draft",
                    "replan_reason": reason, "input_snapshot": snapshot, "operations": result,
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
    def list_downtime_events(process_line_id=None, start_at="", end_at="", limit=1000):
        return {
            "ok": True,
            "events": [dict(row) for row in ScheduleCapacityRepository.list_downtime_events(
                process_line_id=process_line_id, start_at=start_at, end_at=end_at, limit=limit,
            )],
        }

    @staticmethod
    def create_downtime_event(process_line_id, start_at, end_at, reason="", created_by=None):
        if isinstance(process_line_id, bool):
            raise ValueError("产线参数不正确")
        try:
            line_id = int(process_line_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("产线参数不正确") from exc
        if line_id <= 0:
            raise ValueError("产线参数不正确")
        start = ScheduleCapacityService._parse_timestamp(start_at)
        end = ScheduleCapacityService._parse_timestamp(end_at)
        if not start or not end or end <= start:
            raise ValueError("停机开始和结束时间必须有效且结束时间晚于开始时间")
        reason = str(reason or "").strip()
        if len(reason) > 512:
            raise ValueError("停机原因不能超过 512 个字符")
        with BaseService.transaction() as txn:
            event_id = ScheduleCapacityRepository.create_downtime_event(
                line_id, ScheduleCapacityService._format_timestamp(start),
                ScheduleCapacityService._format_timestamp(end), reason, created_by, db=txn,
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
    def publish_revision(revision_id, published_by=None, db=None):
        with ScheduleCapacityService._transaction(db) as txn:
            revision = ScheduleCapacityRepository.find_revision(revision_id, db=txn)
            if revision is None:
                raise ValueError("排程版本不存在")
            ScheduleCapacityRepository.publish_revision(revision_id, txn, published_by=published_by)
            published = ScheduleCapacityRepository.find_revision(revision_id, db=txn)
            return {"ok": True, "revision": dict(published)}

    @staticmethod
    def list_schedules(limit=500):
        limit = ScheduleCapacityService._limit(limit)
        return {"ok": True, "operations": [dict(row) for row in ScheduleCapacityRepository.list_scheduled_operations(limit)]}

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
