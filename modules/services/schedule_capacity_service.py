"""工序级、多产线、工时驱动的排程策略。"""

from datetime import datetime, timedelta

from modules.services import BaseService
from modules.repositories.context import resolve_db
from modules.repositories.schedule_capacity_repository import ScheduleCapacityRepository


class ScheduleCapacityService:
    DEFAULT_DAILY_MINUTES = 480

    @staticmethod
    def list_lines(process_id=None):
        return {"lines": [dict(row) for row in ScheduleCapacityRepository.list_process_lines(process_id)]}

    @staticmethod
    def list_schedulable_orders(limit=500):
        return {"ok": True, "orders": [dict(row) for row in ScheduleCapacityRepository.list_schedulable_orders(limit)]}

    @staticmethod
    def _date(value, label):
        try:
            return datetime.strptime((value or "").strip(), "%Y-%m-%d")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label}必须使用 YYYY-MM-DD 格式") from exc

    @staticmethod
    def _duration_minutes(quantity, standard):
        quantity = max(int(quantity or 0), 0)
        if not standard:
            return float(quantity)
        setup = float(standard["setup_minutes"] or 0)
        unit = float(standard["standard_minutes_per_unit"] or 0)
        factor = max(float(standard["difficulty_factor"] or 1), 0.01)
        return max(setup + quantity * unit * factor, 1.0)

    @staticmethod
    def _find_standard(db, route_id, process_id, product_code):
        return ScheduleCapacityRepository.find_active_standard(route_id, process_id, product_code, db)

    @staticmethod
    def generate_order_schedule(order_id, start_date=None, schedule_run_key=""):
        with BaseService.transaction() as txn:
            order = ScheduleCapacityRepository.find_order(order_id, txn)
            if not order:
                raise ValueError("订单不存在")
            operations = ScheduleCapacityRepository.find_order_operations(order_id, db=txn)
            if not operations:
                raise ValueError("订单没有工序，无法生成排程")
            cursor = ScheduleCapacityService._date(start_date or order["plan_start"], "计划开始日期")
            run_key = (schedule_run_key or datetime.now().strftime("schedule-%Y%m%d%H%M%S")).strip()
            if not run_key:
                raise ValueError("排程幂等键不能为空")
            prior_runs = ScheduleCapacityRepository.find_run(order_id, run_key, txn)
            if prior_runs:
                if any(row["order_id"] != order_id for row in prior_runs):
                    raise ValueError("排程幂等键已被其他订单使用")
                return {"ok": True, "order_id": order_id, "schedule_run_key": run_key,
                        "idempotent_replay": True,
                        "operations": [dict(row) for row in ScheduleCapacityRepository.find_order_operations(order_id, txn)]}
            ScheduleCapacityRepository.clear_order_schedules(order_id, txn)
            line_available = {row["process_line_id"]: ScheduleCapacityService._date(row["last_end"], "已有排程结束日期") + timedelta(days=1)
                              for row in ScheduleCapacityRepository.line_available_dates(order_id, txn)
                              if row["last_end"]}
            result = []
            blocked = False
            for operation in operations:
                if blocked:
                    payload = {"order_id": order_id, "order_process_id": operation["order_process_id"],
                               "process_id": operation["process_id"], "process_line_id": None,
                               "seq_order": operation["seq_order"], "quantity": order["quantity"],
                               "standard_minutes_per_unit": 0, "setup_minutes": 0, "difficulty_factor": 1,
                               "planned_minutes": 0, "plan_start": cursor.strftime("%Y-%m-%d"),
                               "plan_end": cursor.strftime("%Y-%m-%d"), "status": "blocked",
                               "blocked_reason": "前序工序无法排程",
                               "schedule_run_key": run_key}
                    ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                    result.append({**payload, "line_name": None, "process_name": operation["process_name"],
                                   "reason": "前序工序无法排程", "blocked_reason": "前序工序无法排程"})
                    continue
                lines = ScheduleCapacityRepository.list_process_lines(operation["process_id"], db=txn)
                lines = [line for line in lines if line["status"] == "active"]
                if not lines:
                    blocked = True
                    payload = {"order_id": order_id, "order_process_id": operation["order_process_id"],
                               "process_id": operation["process_id"], "process_line_id": None,
                               "seq_order": operation["seq_order"], "quantity": order["quantity"],
                               "standard_minutes_per_unit": 0, "setup_minutes": 0, "difficulty_factor": 1,
                               "planned_minutes": 0, "plan_start": cursor.strftime("%Y-%m-%d"),
                               "plan_end": cursor.strftime("%Y-%m-%d"), "status": "blocked",
                               "blocked_reason": "工序未配置可用产线",
                               "schedule_run_key": run_key}
                    ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                    result.append({**payload, "line_name": None, "process_name": operation["process_name"],
                                   "reason": "工序未配置可用产线", "blocked_reason": "工序未配置可用产线"})
                    continue
                standard = ScheduleCapacityService._find_standard(txn, order["route_id"], operation["process_id"], order["product_code"])
                duration = ScheduleCapacityService._duration_minutes(order["quantity"], standard)
                chosen = min(lines, key=lambda line: line_available.get(line["id"], cursor))
                begin = max(cursor, line_available.get(chosen["id"], cursor))
                capacity = float(chosen["daily_minutes"] or ScheduleCapacityService.DEFAULT_DAILY_MINUTES)
                days = max(1, int((duration + capacity - 1) // capacity))
                end = begin + timedelta(days=days - 1)
                payload = {"order_id": order_id, "order_process_id": operation["order_process_id"], "process_id": operation["process_id"],
                           "process_line_id": chosen["id"], "seq_order": operation["seq_order"], "quantity": order["quantity"],
                           "standard_minutes_per_unit": standard["standard_minutes_per_unit"] if standard else 0,
                           "setup_minutes": standard["setup_minutes"] if standard else 0,
                           "difficulty_factor": standard["difficulty_factor"] if standard else 1,
                           "planned_minutes": duration, "status": "planned",
                           "plan_start": begin.strftime("%Y-%m-%d"), "plan_end": end.strftime("%Y-%m-%d"), "schedule_run_key": run_key}
                ScheduleCapacityRepository.insert_operation_schedule(payload, txn)
                line_available[chosen["id"]] = end + timedelta(days=1)
                cursor = end + timedelta(days=1)
                result.append({**payload, "line_name": chosen["line_name"], "process_name": operation["process_name"]})
            planned = [row for row in result if row.get("status", "planned") != "blocked" and row.get("process_line_id")]
            if planned:
                first_start = min(row["plan_start"] for row in planned)
                last_end = max(row["plan_end"] for row in planned)
                ScheduleCapacityRepository.update_order_summary(order_id, first_start, last_end, txn)
            return {"ok": True, "order_id": order_id, "schedule_run_key": run_key, "idempotent_replay": False, "operations": result}

    @staticmethod
    def list_order_schedule(order_id):
        return {"ok": True, "order_id": order_id, "operations": [dict(row) for row in ScheduleCapacityRepository.find_order_operations(order_id)]}

    @staticmethod
    def list_schedules(limit=500):
        return {"ok": True, "operations": [dict(row) for row in ScheduleCapacityRepository.list_scheduled_operations(limit)]}
