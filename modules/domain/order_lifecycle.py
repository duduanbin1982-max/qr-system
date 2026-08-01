"""Pure lifecycle rules for production orders."""


VALID_TRANSITIONS = {
    "pending": {"producing", "cancelled", "paused"},
    "producing": {"cancelled", "paused"},
    "completed": set(),
    "cancelled": {"pending"},
    "paused": {"producing", "pending", "cancelled"},
}
COMPLETED_READONLY_MESSAGE = "已完成订单已归档，只读，请先重新打开订单"
REOPEN_STATUSES = {"pending", "producing"}


class OrderLifecycle:
    @staticmethod
    def _value(order, key, default=None):
        if hasattr(order, "get"):
            return order.get(key, default)
        try:
            return order[key]
        except (KeyError, IndexError, TypeError):
            return default

    @staticmethod
    def validate_editable(order):
        if OrderLifecycle._value(order, "deleted_at"):
            raise ValueError("订单已在回收站中")
        if OrderLifecycle._value(order, "status") == "completed":
            raise ValueError(COMPLETED_READONLY_MESSAGE)

    @classmethod
    def validate_update(cls, order, data):
        cls.validate_editable(order)
        requested_status = data.get("status")
        if requested_status == "completed":
            raise ValueError("订单完成状态只能由系统根据实际完工事实自动生成")
        current_status = cls._value(order, "status")
        if requested_status and requested_status != current_status:
            allowed = VALID_TRANSITIONS.get(current_status, set())
            if requested_status not in allowed:
                raise ValueError(
                    f"不允许从「{current_status}」切换到「{requested_status}」"
                )

    @classmethod
    def normalize_reopen(cls, order, reason, status):
        normalized_reason = (reason or "").strip()
        if not normalized_reason:
            raise ValueError("请填写重新打开原因")
        normalized_status = (status or "producing").strip().lower()
        if normalized_status not in REOPEN_STATUSES:
            raise ValueError("重新打开后的状态只能是 pending 或 producing")
        if cls._value(order, "deleted_at"):
            raise ValueError("订单已在回收站中")
        if cls._value(order, "status") != "completed":
            raise ValueError("只有已完成订单可以重新打开")
        return normalized_reason, normalized_status
