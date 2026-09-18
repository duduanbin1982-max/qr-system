"""Pure production-node capability and capacity policies.

The policy accepts only caller-supplied facts.  It deliberately does not read
the database, environment flags, configuration, or the current clock, so the
same immutable input always produces the same result.
"""

from collections import Counter
from datetime import datetime
import math


class NodeSchedulingError(ValueError):
    """Structured business conflict returned by node scheduling policies."""

    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})

    def to_payload(self):
        return {"code": self.code, "error": self.message, "details": self.details}


class ProductionNodePolicy:
    """Validate and rank production nodes without mutable dependencies."""

    ERROR_CODES = frozenset(
        {
            "NO_COMPATIBLE_NODE",
            "MISSING_WORK_TIME_STANDARD",
            "VERSION_BINDING_MISMATCH",
            "NODE_CALENDAR_UNAVAILABLE",
            "LOCKED_TASK_CONFLICT",
            "SERIAL_ITEM_SPLIT_FORBIDDEN",
            "BATCH_CAPACITY_EXCEEDED",
        }
    )
    CAPABILITY_FIELDS = (
        "product_id",
        "product_family",
        "material_code",
        "specification",
        "route_version_id",
        "process_version_id",
    )

    @staticmethod
    def _value(source, key):
        if not source:
            return None
        value = source.get(key)
        return None if value in (None, "") else value

    @staticmethod
    def _id_value(value):
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return value

    @staticmethod
    def _text_value(value):
        if value in (None, ""):
            return None
        return str(value).strip().casefold() or None

    @classmethod
    def _fact_value(cls, operation, order, key):
        value = cls._value(operation, key)
        if value is None:
            value = cls._value(order, key)
        if key.endswith("_id"):
            return cls._id_value(value)
        return cls._text_value(value)

    @classmethod
    def _capability_matches(cls, capability, operation, order):
        for field in cls.CAPABILITY_FIELDS:
            expected = capability.get(field)
            if field.endswith("_id"):
                expected = cls._id_value(expected)
            else:
                expected = cls._text_value(expected)
            if expected is None:
                continue
            if expected != cls._fact_value(operation, order, field):
                return False
        return True

    @staticmethod
    def _capability_sort_key(item):
        capability = item[1]
        try:
            capability_id = int(capability.get("id"))
        except (TypeError, ValueError):
            capability_id = math.inf
        return capability_id, item[0]

    @classmethod
    def matching_capability(cls, *, capabilities, operation, order):
        """Return a deterministic matching capability, or ``{}`` for wildcard.

        No active capability rows means the node has no configured restriction.
        Multiple rows are alternatives; constraints inside one row are ANDed.
        """

        active = [
            (index, dict(capability))
            for index, capability in enumerate(capabilities or ())
            if (capability.get("status") or "active") == "active"
        ]
        if not active:
            return {}
        matching = [
            item
            for item in active
            if cls._capability_matches(item[1], operation, order)
        ]
        if not matching:
            return None
        return dict(min(matching, key=cls._capability_sort_key)[1])

    @classmethod
    def matches_capabilities(
        cls, *, node=None, capabilities=None, operation=None, order=None, at_time=None
    ):
        """Compatibility predicate used by later repository-backed schedulers.

        ``node`` and ``at_time`` are accepted to keep the pure seam aligned with
        the future scheduling adapter; capability matching itself needs neither.
        """

        del node, at_time
        return (
            cls.matching_capability(
                capabilities=capabilities,
                operation=operation or {},
                order=order or {},
            )
            is not None
        )

    @staticmethod
    def _parse_datetime(value):
        if isinstance(value, datetime):
            return value
        if value in (None, ""):
            return None
        try:
            return datetime.fromisoformat(str(value).strip().replace("T", " "))
        except (TypeError, ValueError):
            return None

    @classmethod
    def _interval(cls, item):
        start = cls._parse_datetime(
            item.get("start_at", item.get("segment_start_at"))
        )
        end = cls._parse_datetime(item.get("end_at", item.get("segment_end_at")))
        return start, end

    @staticmethod
    def _overlaps(first_start, first_end, second_start, second_end):
        # Half-open intervals make adjacent work (08:00-09:00, 09:00-10:00)
        # valid without manufacturing a one-minute gap.
        return first_start < second_end and second_start < first_end

    @classmethod
    def _validate_version_bindings(cls, operation, order):
        checks = (
            (
                "route_version_id",
                cls._value(order, "route_version_id"),
                cls._value(operation, "route_version_id"),
            ),
            (
                "process_version_id",
                cls._value(operation, "expected_process_version_id"),
                cls._value(operation, "process_version_id"),
            ),
        )
        for binding, expected, actual in checks:
            expected = cls._id_value(expected)
            actual = cls._id_value(actual)
            if expected is not None and expected != actual:
                raise NodeSchedulingError(
                    "VERSION_BINDING_MISMATCH",
                    "订单、路线和工序版本不一致",
                    {"binding": binding, "expected": expected, "actual": actual},
                )

    @classmethod
    def _validate_work_time_standard(cls, operation, standard):
        fact = standard if standard is not None else operation
        standard_id = cls._value(fact, "id") if standard is not None else None
        if standard_id is None:
            standard_id = cls._value(fact, "standard_id")
        minutes = cls._value(fact, "standard_minutes_per_unit")
        try:
            valid_minutes = float(minutes) > 0 and math.isfinite(float(minutes))
        except (TypeError, ValueError):
            valid_minutes = False
        if standard_id is None or not valid_minutes:
            raise NodeSchedulingError(
                "MISSING_WORK_TIME_STANDARD",
                "未配置有效标准工时",
                {"process_id": cls._id_value(operation.get("process_id"))},
            )

    @classmethod
    def _validate_calendar(
        cls,
        *,
        node_id,
        requested_start_at,
        requested_end_at,
        calendar_intervals,
        calendar_available,
    ):
        if calendar_available is False:
            raise NodeSchedulingError(
                "NODE_CALENDAR_UNAVAILABLE",
                "生产节点日历没有可用时间",
                {"production_node_id": node_id},
            )
        start = cls._parse_datetime(requested_start_at)
        end = cls._parse_datetime(requested_end_at)
        if requested_start_at not in (None, "") or requested_end_at not in (None, ""):
            if start is None or end is None or start >= end:
                raise NodeSchedulingError(
                    "NODE_CALENDAR_UNAVAILABLE",
                    "生产节点日历没有可用时间",
                    {"production_node_id": node_id},
                )
        if calendar_intervals is not None and start is not None:
            available = False
            for interval in calendar_intervals:
                interval_start, interval_end = cls._interval(interval)
                if (
                    interval_start is not None
                    and interval_end is not None
                    and interval_start <= start
                    and end <= interval_end
                ):
                    available = True
                    break
            if not available:
                raise NodeSchedulingError(
                    "NODE_CALENDAR_UNAVAILABLE",
                    "生产节点日历没有可用时间",
                    {"production_node_id": node_id},
                )
        return start, end

    @classmethod
    def _validate_occupancy(
        cls, *, node, start, end, occupancy
    ):
        if start is None or end is None:
            return
        node_id = cls._id_value(node.get("id"))
        overlaps = []
        for item in occupancy or ():
            item_node_id = cls._id_value(item.get("production_node_id"))
            if item_node_id is not None and item_node_id != node_id:
                continue
            item_start, item_end = cls._interval(item)
            if (
                item_start is not None
                and item_end is not None
                and cls._overlaps(start, end, item_start, item_end)
            ):
                overlaps.append(dict(item))
        locked = [
            item
            for item in overlaps
            if bool(item.get("locked") or item.get("is_locked"))
        ]
        if locked:
            raise NodeSchedulingError(
                "LOCKED_TASK_CONFLICT",
                "锁定任务发生冲突，需要授权解锁",
                {
                    "production_node_id": node_id,
                    "locked_occupancy_ids": sorted(
                        [
                            item.get("id")
                            for item in locked
                            if item.get("id") is not None
                        ],
                        key=str,
                    ),
                },
            )
        if overlaps and (node.get("capacity_mode") or "exclusive") == "exclusive":
            raise NodeSchedulingError(
                "NODE_CALENDAR_UNAVAILABLE",
                "生产节点已被其他任务占用",
                {
                    "production_node_id": node_id,
                    "conflicting_occupancy_ids": sorted(
                        [
                            item.get("id")
                            for item in overlaps
                            if item.get("id") is not None
                        ],
                        key=str,
                    ),
                },
            )

    @staticmethod
    def _positive_integer(value):
        if isinstance(value, bool):
            return None
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        if number <= 0 or str(value).strip() != str(number):
            return None
        return number

    @staticmethod
    def _positive_number(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if number <= 0 or not math.isfinite(number):
            return None
        return number

    @classmethod
    def _batch_configuration(cls, capability):
        batch_size = cls._positive_integer(capability.get("max_batch_quantity"))
        batch_minutes = cls._positive_number(capability.get("batch_minutes"))
        try:
            changeover_minutes = float(capability.get("changeover_minutes") or 0)
        except (TypeError, ValueError):
            changeover_minutes = -1
        if (
            batch_size is None
            or batch_minutes is None
            or changeover_minutes < 0
            or not math.isfinite(changeover_minutes)
        ):
            raise NodeSchedulingError(
                "BATCH_CAPACITY_EXCEEDED",
                "批处理数量或批次配置不符合要求",
                {
                    "max_batch_quantity": capability.get("max_batch_quantity"),
                    "batch_minutes": capability.get("batch_minutes"),
                    "changeover_minutes": capability.get("changeover_minutes") or 0,
                },
            )
        return batch_size, batch_minutes, changeover_minutes

    @staticmethod
    def _batch_order_id(item):
        if isinstance(item, dict):
            return item.get("order_id", item.get("id"))
        return item

    @classmethod
    def _validate_batch(
        cls,
        *,
        capability,
        operation,
        order,
        quantity,
        batch_orders,
        changeover_required,
    ):
        batch_size, _, changeover_minutes = cls._batch_configuration(capability)
        requested = quantity
        if requested in (None, ""):
            requested = operation.get("quantity")
        requested = cls._positive_integer(requested)
        if requested is None:
            raise NodeSchedulingError(
                "BATCH_CAPACITY_EXCEEDED",
                "批处理数量或批次配置不符合要求",
                {"quantity": quantity, "max_batch_quantity": batch_size},
            )
        if requested > batch_size:
            raise NodeSchedulingError(
                "BATCH_CAPACITY_EXCEEDED",
                "单批数量超过节点批处理上限",
                {"quantity": requested, "max_batch_quantity": batch_size},
            )
        orders = list(batch_orders or [order.get("id")])
        order_ids = sorted(
            {
                cls._batch_order_id(item)
                for item in orders
                if cls._batch_order_id(item) not in (None, "")
            },
            key=str,
        )
        allow_mixed = bool(capability.get("allow_mixed_orders"))
        if len(order_ids) > 1 and not allow_mixed:
            raise NodeSchedulingError(
                "BATCH_CAPACITY_EXCEEDED",
                "当前生产节点不允许混合不同订单",
                {"order_ids": order_ids, "allow_mixed_orders": False},
            )
        if changeover_required and changeover_minutes < 0:
            # Kept explicit even though configuration validation catches this;
            # it documents that changeover facts are part of batch eligibility.
            raise NodeSchedulingError(
                "BATCH_CAPACITY_EXCEEDED",
                "换型时间配置不符合要求",
                {"changeover_minutes": changeover_minutes},
            )

    @classmethod
    def validate_node(
        cls,
        *,
        node,
        capabilities=None,
        operation,
        order,
        standard=None,
        requested_start_at=None,
        requested_end_at=None,
        calendar_intervals=None,
        calendar_available=None,
        occupancy=None,
        quantity=None,
        batch_orders=None,
        changeover_required=False,
    ):
        """Validate one requested allocation and return its capability snapshot."""

        node_id = cls._id_value(node.get("id"))
        status = node.get("status") or "inactive"
        if status != "active":
            raise NodeSchedulingError(
                "NO_COMPATIBLE_NODE",
                "生产节点不可用",
                {"production_node_id": node_id, "status": status},
            )
        node_process_id = cls._id_value(node.get("process_id"))
        operation_process_id = cls._id_value(operation.get("process_id"))
        if node_process_id != operation_process_id:
            raise NodeSchedulingError(
                "NO_COMPATIBLE_NODE",
                "生产节点与订单工序不匹配",
                {
                    "production_node_id": node_id,
                    "node_process_id": node_process_id,
                    "operation_process_id": operation_process_id,
                },
            )
        cls._validate_version_bindings(operation, order)
        cls._validate_work_time_standard(operation, standard)
        capability = cls.matching_capability(
            capabilities=capabilities, operation=operation, order=order
        )
        if capability is None:
            raise NodeSchedulingError(
                "NO_COMPATIBLE_NODE",
                "没有满足能力要求的生产节点",
                {"production_node_id": node_id},
            )
        start, end = cls._validate_calendar(
            node_id=node_id,
            requested_start_at=requested_start_at,
            requested_end_at=requested_end_at,
            calendar_intervals=calendar_intervals,
            calendar_available=calendar_available,
        )
        cls._validate_occupancy(
            node=node, start=start, end=end, occupancy=occupancy
        )
        if (node.get("capacity_mode") or "exclusive") == "batch":
            cls._validate_batch(
                capability=capability,
                operation=operation,
                order=order,
                quantity=quantity,
                batch_orders=batch_orders,
                changeover_required=changeover_required,
            )
        return dict(capability)

    @staticmethod
    def _rank_finish(value):
        parsed = ProductionNodePolicy._parse_datetime(value)
        return (1, datetime.max) if parsed is None else (0, parsed)

    @staticmethod
    def _rank_number(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return math.inf
        return number if math.isfinite(number) else math.inf

    @classmethod
    def rank_nodes(cls, nodes):
        """Rank by earliest finish, risk, load, then stable node id."""

        copies = [dict(node) for node in nodes]
        return sorted(
            copies,
            key=lambda node: (
                cls._rank_finish(node.get("finish_at")),
                cls._rank_number(node.get("risk")),
                cls._rank_number(node.get("load_minutes")),
                cls._rank_number(node.get("id")),
            ),
        )

    @staticmethod
    def _duplicates(values):
        return sorted(
            [value for value, count in Counter(values).items() if count > 1],
            key=str,
        )

    @classmethod
    def validate_serial_allocation(cls, serial_ids, allocations):
        """Require every serial item to be assigned to exactly one node."""

        expected = list(serial_ids or ())
        duplicate_inputs = cls._duplicates(expected)
        if duplicate_inputs:
            raise NodeSchedulingError(
                "SERIAL_ITEM_SPLIT_FORBIDDEN",
                "序列件输入包含重复记录",
                {"duplicate_input_serial_ids": duplicate_inputs},
            )
        assigned = [
            serial_id
            for allocation in allocations or ()
            for serial_id in list(allocation.get("serial_ids") or ())
        ]
        duplicates = cls._duplicates(assigned)
        if duplicates:
            raise NodeSchedulingError(
                "SERIAL_ITEM_SPLIT_FORBIDDEN",
                "单个序列工件不能跨节点拆分",
                {"duplicate_serial_ids": duplicates},
            )
        expected_set = set(expected)
        assigned_set = set(assigned)
        missing = sorted(expected_set - assigned_set, key=str)
        unexpected = sorted(assigned_set - expected_set, key=str)
        if missing or unexpected:
            raise NodeSchedulingError(
                "SERIAL_ITEM_SPLIT_FORBIDDEN",
                "序列件分配与待生产输入不守恒",
                {
                    "missing_serial_ids": missing,
                    "unexpected_serial_ids": unexpected,
                },
            )
        return True

    @classmethod
    def batch_duration_minutes(
        cls, quantity, capability, changeover_required=False
    ):
        """Return exact fixed-batch duration using ceiling batch count."""

        requested = cls._positive_integer(quantity)
        if requested is None:
            raise NodeSchedulingError(
                "BATCH_CAPACITY_EXCEEDED",
                "批处理数量必须为正整数",
                {"quantity": quantity},
            )
        batch_size, batch_minutes, changeover_minutes = cls._batch_configuration(
            capability
        )
        batches = (requested + batch_size - 1) // batch_size
        duration = batches * batch_minutes
        if changeover_required:
            duration += changeover_minutes
        return duration


__all__ = ["NodeSchedulingError", "ProductionNodePolicy"]
