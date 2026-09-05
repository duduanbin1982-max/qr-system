"""
qr-system - ScheduleService (Refactored: SQL -> ScheduleRepository)
"""
from datetime import datetime, timedelta
from modules.services import BaseService
from modules.domain.schedule_deadline_risk import ScheduleDeadlineRiskPolicy
from modules.repositories.production_line_repository import ProductionLineRepository
from modules.repositories.schedule_repository import ScheduleRepository


class ScheduleNotFoundError(ValueError):
    pass


class ScheduleConflictError(ValueError):
    pass


class ScheduleService:
    VALID_SCOPES = {"active", "completed", "all"}
    MAX_PAGE_SIZE = 500
    MAX_BATCH_SIZE = 50
    MAX_SHIFT_DAYS = 30
    _UNSET = object()

    @staticmethod
    def _normalize_scope(schedule_scope):
        return schedule_scope if schedule_scope in ScheduleService.VALID_SCOPES else "active"

    @staticmethod
    def _is_completed_order(order):
        if not order:
            return False
        quantity = order["quantity"] or 0
        completed = order["completed"] or 0
        return order["status"] == "completed" or (quantity > 0 and completed >= quantity)

    @staticmethod
    def _normalize_date(value, field_label):
        if not isinstance(value, str):
            raise ValueError(f"{field_label}格式不正确")
        text = value.strip()
        if not text:
            raise ValueError(f"{field_label}不能为空")
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError(f"{field_label}必须使用 YYYY-MM-DD 格式") from exc
        return parsed.strftime("%Y-%m-%d")

    @staticmethod
    def _normalize_production_line_id(value):
        if value in (None, ""):
            return None
        if isinstance(value, bool):
            raise ValueError("产线参数不正确")
        try:
            line_id = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("产线参数不正确") from exc
        if line_id <= 0:
            raise ValueError("产线参数不正确")
        return line_id

    @staticmethod
    def _normalize_pagination(limit, offset):
        try:
            page_size = int(limit)
            page_offset = int(offset)
        except (TypeError, ValueError) as exc:
            raise ValueError("分页参数不正确") from exc
        return min(max(page_size, 1), ScheduleService.MAX_PAGE_SIZE), max(page_offset, 0)

    @staticmethod
    def _extend_timeline_end(max_date, now):
        ref = now
        if max_date:
            try:
                ref = datetime.strptime(max_date, "%Y-%m-%d")
            except ValueError:
                ref = now
        year, month = ref.year, ref.month + 1
        if month > 12:
            year += 1
            month -= 12
        if month == 12:
            last_day = datetime(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = datetime(year, month + 1, 1) - timedelta(days=1)
        return last_day.strftime("%Y-%m-%d")

    @staticmethod
    def get_gantt_data(limit=200, offset=0, schedule_scope="active"):
        schedule_scope = ScheduleService._normalize_scope(schedule_scope)
        limit, offset = ScheduleService._normalize_pagination(limit, offset)
        rows = ScheduleRepository.find_scheduled_orders(
            limit=limit, offset=offset, schedule_scope=schedule_scope
        )
        summary = ScheduleRepository.get_schedule_summary(schedule_scope=schedule_scope)
        total = summary["total"]

        orders = []
        now = datetime.now()
        for r in rows:
            start = r["plan_start"]
            end = r["plan_end"]
            completed = r["completed"] or 0
            quantity = r["quantity"] or 0
            progress = min(round(completed / quantity * 100), 100) if quantity else 0

            is_completed = bool(r["is_completed"])
            blocked_reasons = tuple(
                reason.strip()
                for reason in str(r["schedule_blocked_reasons"] or "").split("；")
                if reason.strip()
            )
            deadline_risk = ScheduleDeadlineRiskPolicy.evaluate(
                deadline_text=r["deadline"] or "",
                projected_completion_at=r["projected_completion_at"] or "",
                plan_end=end or "",
                now=now,
                completed=is_completed,
                blocked_count=r["schedule_blocked_count"] or 0,
                blocked_reasons=blocked_reasons,
                conflict_count=r["schedule_conflict_count"] or 0,
            )
            risk_level = deadline_risk["level"]
            risk = "overdue" if risk_level == "overdue" else (
                "warning" if risk_level in ("low", "medium", "high") else "normal"
            )

            orders.append({
                "id": r["id"], "order_no": r["order_no"],
                "deadline": r["deadline"],
                "completed_qty": completed,
                "product_name": r["product_name"],
                "product_code": r["product_code"],
                "customer_name": r["customer_name"],
                "plan_start": start, "plan_end": end,
                "status": "completed" if is_completed else r["status"],
                "quantity": quantity,
                "completed": completed,
                "is_completed": is_completed,
                "progress": progress,
                "risk": risk,
                "risk_level": risk_level,
                "risk_reason": deadline_risk["reason"],
                "delay_minutes": deadline_risk["delay_minutes"],
                "slack_minutes": deadline_risk["slack_minutes"],
                "deadline_at": deadline_risk["deadline_at"],
                "projected_completion_at": deadline_risk["projected_completion_at"],
                "schedule_blocked_count": deadline_risk["blocked_count"],
                "schedule_conflict_count": deadline_risk["conflict_count"],
                "production_line": r["production_line"],
                "production_line_id": r["production_line_id"],
                "line_capacity": r["line_capacity"],
            })
        min_date = summary["min_date"]
        max_date = ScheduleService._extend_timeline_end(summary["max_date"], now)

        return {
            "ok": True, "orders": orders,
            "min_date": min_date, "max_date": max_date,
            "total": total, "limit": limit, "offset": offset,
            "has_more": offset + len(orders) < total,
            "stats": {
                "total": total,
                "producing": summary["producing"],
                "pending": summary["pending"],
                "completed": summary["completed"],
            },
            "schedule_scope": schedule_scope
        }

    @staticmethod
    def update_order_schedule(
        order_id,
        plan_start,
        plan_end,
        production_line_id=_UNSET,
    ):
        """Update order plan dates and production line."""
        plan_start = ScheduleService._normalize_date(plan_start, "计划开始日期")
        plan_end = ScheduleService._normalize_date(plan_end, "计划结束日期")
        if plan_start > plan_end:
            raise ValueError("计划开始日期不能晚于计划结束日期")

        update_production_line = production_line_id is not ScheduleService._UNSET
        if update_production_line:
            production_line_id = ScheduleService._normalize_production_line_id(production_line_id)

        with BaseService.transaction() as txn:
            order = ScheduleRepository.find_order_by_id(order_id, db=txn)
            if not order:
                raise ScheduleNotFoundError("订单不存在")
            if ScheduleService._is_completed_order(order):
                raise ScheduleConflictError("已完成订单排程只读，不能调整")
            if update_production_line and production_line_id is not None:
                production_line = ProductionLineRepository.find_by_id(production_line_id, db=txn)
                if not production_line:
                    raise ValueError("所选产线不存在")
                if production_line["status"] != "active":
                    raise ValueError("所选产线已停用")

            updated = ScheduleRepository.update_order_schedule_txn(
                order_id,
                plan_start,
                plan_end,
                production_line_id,
                update_production_line=update_production_line,
                db=txn,
            )
            if not updated:
                raise ScheduleConflictError("订单状态已变化，请刷新后重试")

    @staticmethod
    def batch_shift(order_ids, days):
        """Batch shift order schedule dates (transactional)."""
        if not isinstance(order_ids, list) or not order_ids:
            raise ValueError("请选择需要调整的订单")
        if len(order_ids) > ScheduleService.MAX_BATCH_SIZE:
            raise ValueError(f"每次最多调整 {ScheduleService.MAX_BATCH_SIZE} 个订单")
        normalized_ids = []
        for order_id in order_ids:
            if isinstance(order_id, bool):
                raise ValueError("订单参数不正确")
            try:
                normalized_id = int(order_id)
            except (TypeError, ValueError) as exc:
                raise ValueError("订单参数不正确") from exc
            if normalized_id <= 0:
                raise ValueError("订单参数不正确")
            if normalized_id not in normalized_ids:
                normalized_ids.append(normalized_id)
        if isinstance(days, bool):
            raise ValueError("调整天数不正确")
        try:
            days = int(days)
        except (TypeError, ValueError) as exc:
            raise ValueError("调整天数不正确") from exc
        if days == 0 or abs(days) > ScheduleService.MAX_SHIFT_DAYS:
            raise ValueError(f"调整天数必须在 1 至 {ScheduleService.MAX_SHIFT_DAYS} 天之间")

        count = 0
        with BaseService.transaction() as txn:
            for oid in normalized_ids:
                if ScheduleRepository.shift_order_dates_txn(oid, days, db=txn):
                    count += 1
        return count
