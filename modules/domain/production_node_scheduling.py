"""Pure production-node capability and capacity policies.

The policy accepts only caller-supplied facts.  It deliberately does not read
the database, environment flags, configuration, or the current clock, so the
same immutable input always produces the same result.
"""

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


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
            "QUANTITY_CONSERVATION_FAILED",
            "IDEMPOTENCY_CONFLICT",
            "ROW_VERSION_CONFLICT",
            "REVISION_STATE_CONFLICT",
            "INDEPENDENT_APPROVER_REQUIRED",
            "SCHEDULE_CONFLICT_GATE_FAILED",
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
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @staticmethod
    def _id_value(value):
        if value in (None, "") or isinstance(value, bool):
            return None
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        try:
            if float(value) != number:
                return None
        except (TypeError, ValueError):
            return None
        return number if number > 0 else None

    @staticmethod
    def _text_value(value):
        if value is None:
            return None
        return str(value).strip().casefold() or None

    @staticmethod
    def _display_value(value):
        if isinstance(value, str):
            return value.strip() or None
        return value

    @staticmethod
    def _bool_value(value):
        if value is True or value == 1:
            return True
        if isinstance(value, str):
            return value.strip().casefold() in {"1", "true", "yes", "on"}
        return False

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
            raw_expected = capability.get(field)
            if field.endswith("_id"):
                if raw_expected is None or (
                    isinstance(raw_expected, str) and not raw_expected.strip()
                ):
                    continue
                expected = cls._id_value(raw_expected)
                if expected is None:
                    return False
            else:
                expected = cls._text_value(raw_expected)
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
            if (cls._text_value(capability.get("status")) or "active") == "active"
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
            parsed = value
        elif value in (None, ""):
            return None
        else:
            try:
                text = str(value).strip()
                if not text:
                    return None
                if text.endswith(("Z", "z")):
                    text = text[:-1] + "+00:00"
                parsed = datetime.fromisoformat(text.replace("T", " "))
            except (TypeError, ValueError):
                return None
        if parsed.tzinfo is None:
            try:
                parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            except (ZoneInfoNotFoundError, ValueError, OverflowError):
                return None
        return parsed.astimezone(timezone.utc)

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
    def _binding_error(cls, binding, expected, actual):
        raise NodeSchedulingError(
            "VERSION_BINDING_MISMATCH",
            "订单、路线和工序版本不一致",
            {"binding": binding, "expected": expected, "actual": actual},
        )

    @classmethod
    def _required_binding_id(cls, source, key, label):
        raw = cls._value(source, key)
        value = cls._id_value(raw)
        if value is None:
            cls._binding_error(
                label, "positive integer", cls._display_value(raw)
            )
        return value

    @classmethod
    def _validate_version_bindings(cls, operation, order, standard):
        operation_route_id = cls._required_binding_id(
            operation, "route_version_id", "operation.route_version_id"
        )
        operation_process_version_id = cls._required_binding_id(
            operation, "process_version_id", "operation.process_version_id"
        )
        order_route_id = cls._required_binding_id(
            order, "route_version_id", "order.route_version_id"
        )
        order_process_version_id = cls._required_binding_id(
            order, "process_version_id", "order.process_version_id"
        )
        if operation_route_id != order_route_id:
            cls._binding_error(
                "route_version_id", order_route_id, operation_route_id
            )
        if operation_process_version_id != order_process_version_id:
            cls._binding_error(
                "process_version_id",
                order_process_version_id,
                operation_process_version_id,
            )

        expected_bindings = (
            (operation, "expected_route_version_id", operation_route_id),
            (operation, "expected_process_version_id", operation_process_version_id),
            (order, "expected_route_version_id", operation_route_id),
            (order, "expected_process_version_id", operation_process_version_id),
        )
        for source, key, actual in expected_bindings:
            raw = cls._value(source, key)
            if raw is None:
                continue
            expected = cls._id_value(raw)
            if expected is None or expected != actual:
                cls._binding_error(
                    key.removeprefix("expected_"),
                    cls._display_value(raw),
                    actual,
                )

        if standard is None:
            return
        operation_standard_id = cls._id_value(cls._value(operation, "standard_id"))
        standard_id = cls._required_binding_id(standard, "id", "standard_id")
        if operation_standard_id is None or standard_id != operation_standard_id:
            cls._binding_error(
                "standard_id", operation_standard_id, standard_id
            )
        standard_checks = (
            ("process_id", cls._id_value(operation.get("process_id"))),
            ("route_version_id", operation_route_id),
            ("process_version_id", operation_process_version_id),
        )
        for key, expected in standard_checks:
            actual = cls._required_binding_id(
                standard, key, f"standard.{key}"
            )
            if actual != expected:
                cls._binding_error(f"standard.{key}", expected, actual)

    @classmethod
    def _validate_work_time_standard(cls, operation, standard):
        fact = standard if standard is not None else operation
        standard_id = (
            cls._id_value(cls._value(standard, "id"))
            if standard is not None
            else cls._id_value(cls._value(operation, "standard_id"))
        )
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
        has_requested_interval = (
            cls._display_value(requested_start_at) is not None
            or cls._display_value(requested_end_at) is not None
        )
        if has_requested_interval:
            if start is None or end is None or start >= end:
                raise NodeSchedulingError(
                    "NODE_CALENDAR_UNAVAILABLE",
                    "生产节点日历没有可用时间",
                    {"production_node_id": node_id},
                )
        if has_requested_interval:
            intervals = list(calendar_intervals or ())
            if not intervals:
                raise NodeSchedulingError(
                    "NODE_CALENDAR_UNAVAILABLE",
                    "生产节点日历没有可用时间",
                    {"production_node_id": node_id},
                )
            available = False
            for interval in intervals:
                if not isinstance(interval, dict):
                    continue
                interval_start, interval_end = cls._interval(interval)
                if (
                    interval_start is not None
                    and interval_end is not None
                    and interval_start < interval_end
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
        for index, item in enumerate(occupancy or ()):
            if not isinstance(item, dict):
                raise NodeSchedulingError(
                    "NODE_CALENDAR_UNAVAILABLE",
                    "生产节点占用事实无效",
                    {
                        "production_node_id": node_id,
                        "reason": "invalid_occupancy_fact",
                        "occupancy_id": None,
                        "fact_index": index,
                    },
                )
            item_node_id = cls._id_value(item.get("production_node_id"))
            item_start, item_end = cls._interval(item)
            if (
                item_start is None
                or item_end is None
                or item_start >= item_end
            ):
                raise NodeSchedulingError(
                    "NODE_CALENDAR_UNAVAILABLE",
                    "生产节点占用事实无效",
                    {
                        "production_node_id": node_id,
                        "reason": "invalid_occupancy_fact",
                        "occupancy_id": item.get("id"),
                        "fact_index": index,
                    },
                )
            if item_node_id is not None and item_node_id != node_id:
                continue
            if (
                cls._overlaps(start, end, item_start, item_end)
            ):
                overlaps.append(dict(item))
        locked = [
            item
            for item in overlaps
            if cls._bool_value(item.get("locked"))
            or cls._bool_value(item.get("is_locked"))
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
        current_order_id = cls._id_value(order.get("id"))
        if batch_orders is not None and not isinstance(batch_orders, (list, tuple)):
            raise NodeSchedulingError(
                "BATCH_CAPACITY_EXCEEDED",
                "批处理订单列表不符合要求",
                {
                    "reason": "invalid_batch_orders",
                    "invalid_order_ids": [cls._display_value(batch_orders)],
                },
            )
        orders = [order.get("id")] if batch_orders is None else list(batch_orders)
        normalized_order_ids = []
        invalid_order_ids = []
        for item in orders:
            raw_order_id = cls._batch_order_id(item)
            order_id = cls._id_value(raw_order_id)
            if order_id is None:
                invalid_order_ids.append(cls._display_value(raw_order_id))
            else:
                normalized_order_ids.append(order_id)
        if not orders or invalid_order_ids or current_order_id is None:
            raise NodeSchedulingError(
                "BATCH_CAPACITY_EXCEEDED",
                "批处理订单列表不符合要求",
                {
                    "reason": "invalid_batch_orders",
                    "invalid_order_ids": sorted(invalid_order_ids, key=str),
                },
            )
        order_ids = sorted(set(normalized_order_ids))
        if current_order_id not in order_ids:
            raise NodeSchedulingError(
                "BATCH_CAPACITY_EXCEEDED",
                "批处理订单列表未包含当前订单",
                {"order_id": current_order_id, "order_ids": order_ids},
            )
        allow_mixed = cls._bool_value(capability.get("allow_mixed_orders"))
        if len(order_ids) > 1 and not allow_mixed:
            raise NodeSchedulingError(
                "BATCH_CAPACITY_EXCEEDED",
                "当前生产节点不允许混合不同订单",
                {"order_ids": order_ids, "allow_mixed_orders": False},
            )
        # Access the validated value when changeover is requested so callers
        # cannot accidentally bypass configuration validation.
        if changeover_required:
            float(changeover_minutes)

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

        # Business-fact validation has a stable priority.  A stale or incomplete
        # version/standard must never be hidden by a bad candidate node.
        cls._validate_version_bindings(operation, order, standard)
        cls._validate_work_time_standard(operation, standard)

        node_id = cls._id_value(node.get("id"))
        if node_id is None:
            raise NodeSchedulingError(
                "NO_COMPATIBLE_NODE",
                "生产节点标识无效",
                {
                    "reason": "invalid_node_id",
                    "actual": cls._display_value(node.get("id")),
                },
            )
        status = cls._text_value(node.get("status")) or "inactive"
        if status != "active":
            raise NodeSchedulingError(
                "NO_COMPATIBLE_NODE",
                "生产节点不可用",
                {"production_node_id": node_id, "status": status},
            )
        capacity_mode = cls._text_value(node.get("capacity_mode"))
        if capacity_mode not in {"exclusive", "batch"}:
            raise NodeSchedulingError(
                "NO_COMPATIBLE_NODE",
                "生产节点容量模式不受支持",
                {
                    "production_node_id": node_id,
                    "reason": "invalid_capacity_mode",
                    "capacity_mode": cls._display_value(node.get("capacity_mode")),
                },
            )
        node_process_id = cls._id_value(node.get("process_id"))
        operation_process_id = cls._id_value(operation.get("process_id"))
        if node_process_id is None:
            raise NodeSchedulingError(
                "NO_COMPATIBLE_NODE",
                "生产节点工序标识无效",
                {
                    "reason": "invalid_node_process_id",
                    "actual": cls._display_value(node.get("process_id")),
                },
            )
        if operation_process_id is None:
            raise NodeSchedulingError(
                "NO_COMPATIBLE_NODE",
                "订单工序标识无效",
                {
                    "reason": "invalid_operation_process_id",
                    "actual": cls._display_value(operation.get("process_id")),
                },
            )
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
        normalized_node = dict(node)
        normalized_node["capacity_mode"] = capacity_mode
        cls._validate_occupancy(
            node=normalized_node, start=start, end=end, occupancy=occupancy
        )
        if capacity_mode == "batch":
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
        return (1, math.inf) if parsed is None else (0, parsed.timestamp())

    @staticmethod
    def _rank_number(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return math.inf
        return number if math.isfinite(number) else math.inf

    @staticmethod
    def _canonical_row_digest(node):
        encoded = json.dumps(
            node,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=lambda value: (
                value.isoformat() if isinstance(value, datetime) else str(value)
            ),
        )
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @classmethod
    def _rank_node_id(cls, node):
        digest = cls._canonical_row_digest(node)
        node_id = cls._id_value(node.get("id"))
        if node_id is None:
            return 1, math.inf, digest
        return 0, node_id, digest

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
                cls._rank_node_id(node),
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
        normalized_allocations = []
        for index, allocation in enumerate(allocations or ()):
            if not isinstance(allocation, dict):
                raise NodeSchedulingError(
                    "SERIAL_ITEM_SPLIT_FORBIDDEN",
                    "序列件分配节点无效",
                    {"allocation_index": index, "production_node_id": None},
                )
            raw_node_id = allocation.get("production_node_id")
            if cls._id_value(raw_node_id) is None:
                raise NodeSchedulingError(
                    "SERIAL_ITEM_SPLIT_FORBIDDEN",
                    "序列件分配节点无效",
                    {
                        "allocation_index": index,
                        "production_node_id": raw_node_id,
                    },
                )
            normalized_allocations.append(allocation)
        assigned = [
            serial_id
            for allocation in normalized_allocations
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

    @classmethod
    def validate_quantity_conservation(cls, requested_quantity, allocations):
        """Require allocation quantities to conserve the requested amount exactly.

        Allocations are intentionally treated as immutable facts at this seam:
        negative, fractional and non-integer quantities fail closed instead of
        being silently rounded by the scheduler.
        """
        expected = cls._positive_integer(requested_quantity)
        if expected is None:
            raise NodeSchedulingError(
                "QUANTITY_CONSERVATION_FAILED",
                "待排数量必须为正整数",
                {"requested_quantity": requested_quantity, "allocated_quantity": 0},
            )
        normalized = []
        for index, allocation in enumerate(allocations or ()):
            if not isinstance(allocation, dict):
                raise NodeSchedulingError(
                    "QUANTITY_CONSERVATION_FAILED",
                    "分配明细无效",
                    {"allocation_index": index, "allocated_quantity": 0},
                )
            quantity = cls._positive_integer(allocation.get("quantity"))
            if quantity is None:
                raise NodeSchedulingError(
                    "QUANTITY_CONSERVATION_FAILED",
                    "分配数量必须为正整数",
                    {"allocation_index": index, "quantity": allocation.get("quantity")},
                )
            normalized.append(quantity)
        actual = sum(normalized)
        if actual != expected:
            raise NodeSchedulingError(
                "QUANTITY_CONSERVATION_FAILED",
                "排程分配数量未守恒",
                {"requested_quantity": expected, "allocated_quantity": actual},
            )
        return True


__all__ = ["NodeSchedulingError", "ProductionNodePolicy"]
