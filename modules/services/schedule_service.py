"""
qr-system - ScheduleService (Refactored: SQL -> ScheduleRepository)
"""
from datetime import datetime, timedelta
from modules.services import BaseService
from modules.repositories.schedule_repository import ScheduleRepository


class ScheduleService:
    @staticmethod
    def get_gantt_data(limit=200, offset=0):
        rows = ScheduleRepository.find_scheduled_orders(limit=limit, offset=offset)
        total = ScheduleRepository.count_scheduled_orders()

        orders = []
        min_date = None
        max_date = None
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        two_days_later = (now + timedelta(days=2)).strftime("%Y-%m-%d")
        for r in rows:
            start = r["plan_start"]
            end = r["plan_end"]
            progress = min(round(r["completed"] / r["quantity"] * 100), 100) if r["quantity"] else 0

            # Deadline risk assessment
            deadline = r["deadline"] if r["deadline"] else None
            risk = "normal"
            if end and end < today_str and progress < 100:
                risk = "overdue"
            elif end and end <= two_days_later and progress < 60:
                risk = "warning"

            orders.append({
                "id": r["id"], "order_no": r["order_no"],
                "deadline": r["deadline"],
                "completed_qty": r["completed"],
                "product_name": r["product_name"],
                "product_code": r["product_code"],
                "customer_name": r["customer_name"],
                "plan_start": start, "plan_end": end,
                "status": r["status"], "quantity": r["quantity"],
                "completed": r["completed"],
                "progress": progress,
                "risk": risk,
                "production_line": r["production_line"],
                "production_line_id": r["production_line_id"],
                "line_capacity": r["line_capacity"],
            })
            if start:
                if min_date is None or start < min_date: min_date = start
                if max_date is None or end > max_date: max_date = end

        # Extend max_date to end of next month
        if max_date:
            ref = datetime.strptime(max_date, "%Y-%m-%d")
        else:
            ref = now
        y, m = ref.year, ref.month
        m += 1
        if m > 12:
            y += 1
            m -= 12
        if m == 12:
            last_day = datetime(y + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = datetime(y, m + 1, 1) - timedelta(days=1)
        max_date = last_day.strftime("%Y-%m-%d")

        return {
            "ok": True, "orders": orders,
            "min_date": min_date, "max_date": max_date,
            "total": total, "limit": limit, "offset": offset
        }

    @staticmethod
    def update_order_schedule(order_id, plan_start, plan_end, production_line_id=None):
        """Update order plan dates and production line."""
        order = ScheduleRepository.find_order_by_id(order_id)
        if not order:
            raise ValueError("order not found")

        with BaseService.transaction() as txn:
            ScheduleRepository.update_order_schedule_txn(
                order_id, plan_start, plan_end, production_line_id, db=txn
            )

    @staticmethod
    def batch_shift(order_ids, days):
        """Batch shift order schedule dates (transactional)."""
        count = 0
        with BaseService.transaction() as txn:
            for oid in order_ids:
                if ScheduleRepository.shift_order_dates_txn(oid, days, db=txn):
                    count += 1
        return count
