"""工序级、多产线、工时驱动的排程策略。"""

import json
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta

from modules.services import BaseService
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
        intervals = sorted(occupied, key=lambda item: item[0])
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
                        "start_at": end.strftime("%Y-%m-%d %H:%M"),
                        "end_at": end.strftime("%Y-%m-%d %H:%M"),
                        "occupied_minutes": take,
                        "shift_id": slot["shift_id"],
                    })
                    segments[-1]["start_at"] = cursor.strftime("%Y-%m-%d %H:%M")
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
                    "start_at": cursor.strftime("%Y-%m-%d %H:%M"),
                    "end_at": end.strftime("%Y-%m-%d %H:%M"),
                    "occupied_minutes": take,
                    "shift_id": slot["shift_id"],
                })
                remaining -= take
        if remaining > epsilon:
            raise ValueError("工作日历在可搜索范围内没有足够产能")
        return segments

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
                return {"ok": prior_run["status"] == "completed", "order_id": order_id,
                        "schedule_run_key": run_key, "idempotent_replay": True,
                        "status": prior_run["status"], "error": prior_run["error_message"] or "",
                        "operations": replay}

            run_id = ScheduleCapacityRepository.create_run(order_id, run_key, cursor.strftime("%Y-%m-%d"), txn)
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
                              "schedule_run_id": run_id}
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

                    duration = ScheduleCapacityService._duration_minutes(order["quantity"], standard)
                    candidates = []
                    for line in lines:
                        calendar = ScheduleCapacityRepository.get_calendar(line["calendar_id"], db=txn)
                        if calendar is None:
                            calendar = ScheduleCapacityRepository.get_calendar(db=txn)
                        shifts = ScheduleCapacityRepository.list_calendar_shifts(calendar["id"], db=txn) if calendar else []
                        if not calendar or not shifts:
                            continue
                        try:
                            line_segments = ScheduleCapacityService._allocate_on_line(
                                txn, calendar, shifts,
                                float(line["daily_minutes"] or ScheduleCapacityService.DEFAULT_DAILY_MINUTES),
                                cursor, duration,
                                occupancy.get(line["id"], []),
                            )
                        except ValueError:
                            # One saturated line must not prevent another line
                            # in the same process pool from being considered.
                            continue
                        candidates.append((
                            ScheduleCapacityService._parse_timestamp(line_segments[-1]["end_at"]),
                            line, calendar, shifts, line_segments,
                        ))
                    if not candidates:
                        blocked = True
                        payload = {**common, "process_line_id": None, "standard_id": standard["id"],
                                   "standard_version": standard["version"],
                                   "standard_minutes_per_unit": standard["standard_minutes_per_unit"],
                                   "setup_minutes": standard["setup_minutes"], "difficulty_factor": standard["difficulty_factor"],
                                   "planned_minutes": 0, "plan_start": cursor.strftime("%Y-%m-%d"),
                                   "plan_end": cursor.strftime("%Y-%m-%d"), "status": "blocked",
                                   "blocked_reason": "未配置有效工作日历或班次"}
                        payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                        result.append({**payload, "line_name": None, "process_name": process_snapshot,
                                       "reason": payload["blocked_reason"]})
                        continue
                    _, chosen, calendar, shifts, segments = min(
                        candidates, key=lambda item: (item[0], item[1]["id"])
                    )
                    begin = ScheduleCapacityService._parse_timestamp(segments[0]["start_at"])
                    end = ScheduleCapacityService._parse_timestamp(segments[-1]["end_at"])
                    capacity_snapshot = ScheduleCapacityService._calendar_snapshot(calendar, shifts)
                    capacity_snapshot.update({
                        "process_line_id": chosen["id"],
                        "line_code": chosen["line_code"],
                        "line_name": chosen["line_name"],
                        "daily_minutes": float(chosen["daily_minutes"] or ScheduleCapacityService.DEFAULT_DAILY_MINUTES),
                    })
                    payload = {**common, "process_line_id": chosen["id"], "standard_id": standard["id"],
                               "standard_version": standard["version"],
                               "standard_minutes_per_unit": standard["standard_minutes_per_unit"],
                               "setup_minutes": standard["setup_minutes"], "difficulty_factor": standard["difficulty_factor"],
                               "planned_minutes": duration, "occupied_minutes": duration, "status": "planned",
                               "standard_match_scope": standard["match_scope"],
                               "planned_start_at": begin.strftime("%Y-%m-%d %H:%M"),
                               "planned_end_at": end.strftime("%Y-%m-%d %H:%M"),
                               "capacity_snapshot_json": json.dumps(capacity_snapshot, ensure_ascii=False, sort_keys=True),
                               "shift_snapshot_json": json.dumps(capacity_snapshot["shifts"], ensure_ascii=False, sort_keys=True),
                               "calendar_id": calendar["id"], "line_name_snapshot": chosen["line_name"],
                               "segments": segments,
                               "plan_start": begin.strftime("%Y-%m-%d"), "plan_end": end.strftime("%Y-%m-%d")}
                    payload["id"] = ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                    ScheduleCapacityService._add_segments_to_occupancy(occupancy, chosen["id"], segments)
                    cursor = end
                    result.append({**payload, "line_name": chosen["line_name"], "process_name": process_snapshot})
                planned = [row for row in result if row.get("status") == "planned" and row.get("process_line_id")]
                if planned:
                    first_start = min(row["plan_start"] for row in planned)
                    last_end = max(row["plan_end"] for row in planned)
                    ScheduleCapacityRepository.update_order_summary(order_id, first_start, last_end, txn)
                txn.execute("RELEASE SAVEPOINT schedule_generation")
                ScheduleCapacityRepository.complete_run(run_id, "completed", result, db=txn)
                response = {"ok": True, "order_id": order_id, "schedule_run_key": run_key,
                            "idempotent_replay": False, "status": "completed", "operations": result}
            except Exception as exc:
                txn.execute("ROLLBACK TO SAVEPOINT schedule_generation")
                txn.execute("RELEASE SAVEPOINT schedule_generation")
                ScheduleCapacityRepository.complete_run(run_id, "failed", [], str(exc), db=txn)
                failure = str(exc)
        if failure:
            raise ValueError(failure)
        return response

    @staticmethod
    def list_order_schedule(order_id, limit=500):
        limit = ScheduleCapacityService._limit(limit)
        return {"ok": True, "order_id": order_id, "operations": [dict(row) for row in ScheduleCapacityRepository.find_order_operations(order_id, limit=limit)]}

    @staticmethod
    def list_schedules(limit=500):
        limit = ScheduleCapacityService._limit(limit)
        return {"ok": True, "operations": [dict(row) for row in ScheduleCapacityRepository.list_scheduled_operations(limit)]}

    @staticmethod
    def audit_schedule_capacity(limit=1000):
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
            "line_conflicts": len(conflicts),
            "conflicts": conflicts[:limit],
            "line_loads": line_loads,
            "calendars": ScheduleCapacityRepository.list_calendars(),
        }
