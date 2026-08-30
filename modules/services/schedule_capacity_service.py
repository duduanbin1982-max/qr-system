"""工序级、多产线、工时驱动的排程策略。"""

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
    def _find_standard(db, route_id, route_version_id, process_id, process_version_id, product_code):
        return ScheduleCapacityRepository.find_active_standard(
            route_id, route_version_id, process_id, process_version_id, product_code, db
        )

    @staticmethod
    def generate_order_schedule(order_id, start_date=None, schedule_run_key=""):
        failure = None
        response = None
        with BaseService.transaction() as txn:
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
                line_available = {row["process_line_id"]: ScheduleCapacityService._date(row["last_end"], "已有排程结束日期") + timedelta(days=1)
                                  for row in ScheduleCapacityRepository.line_available_dates(order_id, txn)
                                  if row["last_end"]}
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
                        ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                        result.append({**payload, "line_name": None, "process_name": process_snapshot,
                                       "reason": payload["blocked_reason"]})
                        continue

                    standard = ScheduleCapacityService._find_standard(
                        txn, order["route_id"], route_version_id, operation["process_id"],
                        process_version_id, order["product_code"]
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
                        ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
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
                        ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                        result.append({**payload, "line_name": None, "process_name": process_snapshot,
                                       "reason": payload["blocked_reason"]})
                        continue

                    duration = ScheduleCapacityService._duration_minutes(order["quantity"], standard)
                    chosen = min(lines, key=lambda line: line_available.get(line["id"], cursor))
                    begin = max(cursor, line_available.get(chosen["id"], cursor))
                    capacity = float(chosen["daily_minutes"] or ScheduleCapacityService.DEFAULT_DAILY_MINUTES)
                    days = max(1, int((duration + capacity - 1) // capacity))
                    end = begin + timedelta(days=days - 1)
                    payload = {**common, "process_line_id": chosen["id"], "standard_id": standard["id"],
                               "standard_version": standard["version"],
                               "standard_minutes_per_unit": standard["standard_minutes_per_unit"],
                               "setup_minutes": standard["setup_minutes"], "difficulty_factor": standard["difficulty_factor"],
                               "planned_minutes": duration, "status": "planned",
                               "plan_start": begin.strftime("%Y-%m-%d"), "plan_end": end.strftime("%Y-%m-%d")}
                    ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                    line_available[chosen["id"]] = end + timedelta(days=1)
                    cursor = end + timedelta(days=1)
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
