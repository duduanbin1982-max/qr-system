"""Pure, deterministic priority rules for automatic production scheduling."""

from datetime import datetime

from modules.domain.schedule_deadline_risk import parse_schedule_datetime


class ScheduleOrderPriorityPolicy:
    """Rank live orders without consulting mutable external state."""

    SCHEDULABLE_STATUSES = {"pending", "producing"}

    @staticmethod
    def _int(value, default):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _parse_effective_at(value):
        """Expose the shared timestamp parser for update validation."""
        return parse_schedule_datetime(value or "")

    @classmethod
    def effective_intent(cls, order, now=None):
        now = now or datetime.now()
        effective_at = parse_schedule_datetime(order.get("priority_effective_at") or "")
        use_previous = effective_at is not None and effective_at > now
        current_level = cls._int(order.get("priority_level"), 3)
        current_expedited = cls._int(order.get("is_expedited"), 0)
        # Legacy callers and pre-V084 rows may not expose the previous_*
        # fields.  Falling back to the current intent is deterministic and,
        # importantly, avoids silently inventing a P3/non-expedited value.
        previous_level = cls._int(order.get("previous_priority_level"), current_level)
        previous_expedited = cls._int(order.get("previous_is_expedited"), current_expedited)
        level = min(max(previous_level if use_previous else current_level, 1), 5)
        expedited = bool(previous_expedited if use_previous else current_expedited)
        return {
            "priority_level": level,
            "is_expedited": expedited,
            "priority_effective_at": order.get("priority_effective_at") or "",
            "pending_effective_change": use_previous,
        }

    @classmethod
    def is_schedulable(cls, order, now=None):
        intent = cls.effective_intent(order, now=now)
        return (
            (order.get("status") or "") in cls.SCHEDULABLE_STATUSES
            and intent["priority_level"] < 5
        )

    @classmethod
    def sort_key(cls, order, now=None):
        intent = cls.effective_intent(order, now=now)
        deadline = parse_schedule_datetime(order.get("deadline") or "", end_of_day=True)
        plan_start = parse_schedule_datetime(order.get("plan_start") or "")
        return (
            intent["priority_level"],
            0 if intent["is_expedited"] else 1,
            1 if deadline is None else 0,
            deadline or datetime.max,
            plan_start or datetime.max,
            cls._int(order.get("id"), 0),
        )

    @classmethod
    def order_queue(cls, orders, now=None):
        return sorted((dict(order) for order in orders), key=lambda row: cls.sort_key(row, now=now))


__all__ = ["ScheduleOrderPriorityPolicy"]
