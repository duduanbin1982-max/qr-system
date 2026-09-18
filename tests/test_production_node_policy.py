from copy import deepcopy

import pytest

from modules.domain.production_node_scheduling import (
    NodeSchedulingError,
    ProductionNodePolicy,
)


def _node(**overrides):
    node = {
        "id": 10,
        "process_id": 7,
        "status": "active",
        "capacity_mode": "exclusive",
        "calendar_id": 1,
    }
    node.update(overrides)
    return node


def _operation(**overrides):
    operation = {
        "process_id": 7,
        "route_version_id": 70,
        "process_version_id": 71,
        "standard_id": 72,
        "standard_minutes_per_unit": 12,
        "product_id": 20,
        "product_family": "housing",
        "material_code": "Q235",
        "specification": "SB121",
    }
    operation.update(overrides)
    return operation


def _order(**overrides):
    order = {
        "id": 30,
        "route_version_id": 70,
        "process_version_id": 71,
        "product_id": 20,
        "product_family": "housing",
        "material_code": "Q235",
        "specification": "SB121",
    }
    order.update(overrides)
    return order


def _standard(**overrides):
    standard = {
        "id": 72,
        "process_id": 7,
        "route_version_id": 70,
        "process_version_id": 71,
        "standard_minutes_per_unit": 12,
    }
    standard.update(overrides)
    return standard


def _capability(**overrides):
    capability = {
        "id": 40,
        "status": "active",
        "product_id": 20,
        "product_family": "",
        "material_code": "Q235",
        "specification": "SB121",
        "route_version_id": 70,
        "process_version_id": 71,
        "max_batch_quantity": None,
        "batch_minutes": None,
        "changeover_minutes": 0,
        "allow_mixed_orders": 0,
    }
    capability.update(overrides)
    return capability


def _validate(**overrides):
    values = {
        "node": _node(),
        "capabilities": [_capability()],
        "operation": _operation(),
        "order": _order(),
        "requested_start_at": "2026-09-18 08:00",
        "requested_end_at": "2026-09-18 09:00",
        "calendar_intervals": [
            {"start_at": "2026-09-18 08:00", "end_at": "2026-09-18 12:00"}
        ],
        "occupancy": [],
    }
    values.update(overrides)
    return ProductionNodePolicy.validate_node(**values)


def _assert_error(code, **overrides):
    with pytest.raises(NodeSchedulingError) as error:
        _validate(**overrides)
    assert error.value.code == code
    return error.value


def test_node_scheduling_error_has_exact_payload_contract():
    error = NodeSchedulingError("NO_COMPATIBLE_NODE", "no node", {"process_id": 7})

    assert str(error) == "no node"
    assert error.message == "no node"
    assert error.details == {"process_id": 7}
    assert error.to_payload() == {
        "code": "NO_COMPATIBLE_NODE",
        "error": "no node",
        "details": {"process_id": 7},
    }


@pytest.mark.parametrize("status", ["inactive", "maintenance"])
def test_inactive_or_maintenance_node_is_not_compatible(status):
    error = _assert_error("NO_COMPATIBLE_NODE", node=_node(status=status))
    assert error.details == {"production_node_id": 10, "status": status}


def test_node_process_must_match_operation_process():
    error = _assert_error("NO_COMPATIBLE_NODE", node=_node(process_id=99))
    assert error.details == {
        "production_node_id": 10,
        "node_process_id": 99,
        "operation_process_id": 7,
    }


def test_version_binding_errors_take_precedence_over_node_and_capability_errors():
    error = _assert_error(
        "VERSION_BINDING_MISMATCH",
        node=_node(status="maintenance", capacity_mode="invented"),
        capabilities=[_capability(product_id=999)],
        operation=_operation(route_version_id=None),
    )
    assert error.details == {
        "binding": "operation.route_version_id",
        "expected": "positive integer",
        "actual": None,
    }


def test_missing_work_time_takes_precedence_over_node_and_capability_errors():
    error = _assert_error(
        "MISSING_WORK_TIME_STANDARD",
        node=_node(status="inactive", capacity_mode="invented"),
        capabilities=[_capability(product_id=999)],
        operation=_operation(standard_id=None),
    )
    assert error.details == {"process_id": 7}


@pytest.mark.parametrize(
    ("capability_override", "operation_override", "order_override"),
    [
        ({"product_id": 21}, {}, {}),
        ({"product_family": "cover", "product_id": None}, {}, {}),
        ({"material_code": "304"}, {}, {}),
        ({"specification": "SB195"}, {}, {}),
        ({"route_version_id": 700}, {}, {}),
        ({"process_version_id": 710}, {}, {}),
    ],
)
def test_each_capability_dimension_must_match(
    capability_override, operation_override, order_override
):
    error = _assert_error(
        "NO_COMPATIBLE_NODE",
        capabilities=[_capability(**capability_override)],
        operation=_operation(**operation_override),
        order=_order(**order_override),
    )
    assert error.details["production_node_id"] == 10


@pytest.mark.parametrize(
    "capabilities",
    [
        [],
        None,
        [_capability(status="inactive")],
    ],
)
def test_empty_null_or_inactive_capability_is_unrestricted(capabilities):
    assert _validate(capabilities=capabilities) == {}


def test_active_wildcard_capability_is_unrestricted_but_remains_a_snapshot():
    selected = _validate(
        capabilities=[
            _capability(
                product_id=None,
                product_family=None,
                material_code=None,
                specification=None,
                route_version_id=None,
                process_version_id=None,
            )
        ]
    )
    assert selected["id"] == 40


def test_capability_and_operation_text_use_trimmed_fallback_values():
    selected = _validate(
        capabilities=[
            _capability(
                status=" active ",
                product_family=" HOUSING ",
                material_code=" Q235 ",
                specification=" SB121 ",
            )
        ],
        operation=_operation(product_family=" ", material_code=" Q235 "),
    )
    assert selected["id"] == 40


def test_capability_rows_are_or_alternatives_and_selection_is_deterministic():
    selected = _validate(
        capabilities=[
            _capability(id=42, product_id=999),
            _capability(id=41),
            _capability(id=40),
        ]
    )
    assert selected["id"] == 40


@pytest.mark.parametrize(
    ("operation_override", "order_override", "expected_details"),
    [
        (
            {"route_version_id": 700},
            {},
            {
                "binding": "route_version_id",
                "expected": 70,
                "actual": 700,
            },
        ),
        (
            {"expected_process_version_id": 72},
            {},
            {
                "binding": "process_version_id",
                "expected": 72,
                "actual": 71,
            },
        ),
    ],
)
def test_version_binding_mismatch_is_structured(
    operation_override, order_override, expected_details
):
    error = _assert_error(
        "VERSION_BINDING_MISMATCH",
        operation=_operation(**operation_override),
        order=_order(**order_override),
    )
    assert error.details == expected_details


def test_expected_route_version_is_enforced_when_supplied():
    error = _assert_error(
        "VERSION_BINDING_MISMATCH",
        operation=_operation(expected_route_version_id=999),
    )
    assert error.details == {
        "binding": "route_version_id",
        "expected": 999,
        "actual": 70,
    }


@pytest.mark.parametrize(
    ("operation", "order", "expected_binding"),
    [
        (_operation(route_version_id=None), _order(), "operation.route_version_id"),
        (_operation(process_version_id=None), _order(), "operation.process_version_id"),
        (_operation(), _order(route_version_id=None), "order.route_version_id"),
        (_operation(), _order(process_version_id=None), "order.process_version_id"),
        (_operation(), _order(process_version_id=999), "process_version_id"),
    ],
)
def test_route_and_process_version_facts_are_required_and_exact(
    operation, order, expected_binding
):
    error = _assert_error(
        "VERSION_BINDING_MISMATCH", operation=operation, order=order
    )
    assert error.details["binding"] == expected_binding


@pytest.mark.parametrize(
    ("standard_override", "binding"),
    [
        ({"id": 999}, "standard_id"),
        ({"process_id": 999}, "standard.process_id"),
        ({"route_version_id": 999}, "standard.route_version_id"),
        ({"process_version_id": 999}, "standard.process_version_id"),
    ],
)
def test_explicit_standard_must_bind_exactly_to_operation(
    standard_override, binding
):
    error = _assert_error(
        "VERSION_BINDING_MISMATCH", standard=_standard(**standard_override)
    )
    assert error.details["binding"] == binding


def test_explicit_standard_missing_or_non_positive_minutes_is_missing_work_time():
    error = _assert_error(
        "MISSING_WORK_TIME_STANDARD",
        standard=_standard(standard_minutes_per_unit=0),
    )
    assert error.details == {"process_id": 7}


@pytest.mark.parametrize(
    "operation",
    [
        _operation(standard_id=None),
        _operation(standard_minutes_per_unit=0),
        _operation(standard_minutes_per_unit=None),
    ],
)
def test_missing_or_invalid_work_time_standard_is_blocked(operation):
    error = _assert_error("MISSING_WORK_TIME_STANDARD", operation=operation)
    assert error.details == {"process_id": 7}


def test_calendar_must_contain_requested_interval():
    error = _assert_error(
        "NODE_CALENDAR_UNAVAILABLE",
        requested_start_at="2026-09-18 12:00",
        requested_end_at="2026-09-18 13:00",
    )
    assert error.details["production_node_id"] == 10


def test_explicit_calendar_unavailability_is_blocked():
    _assert_error(
        "NODE_CALENDAR_UNAVAILABLE",
        calendar_intervals=None,
        calendar_available=False,
    )


@pytest.mark.parametrize("calendar_intervals", [None, []])
def test_requested_interval_requires_supplied_calendar_intervals(calendar_intervals):
    _assert_error(
        "NODE_CALENDAR_UNAVAILABLE", calendar_intervals=calendar_intervals
    )


def test_calendar_normalizes_aware_and_naive_timestamps_to_utc():
    selected = _validate(
        requested_start_at="2026-09-18T08:00:00+08:00",
        requested_end_at="2026-09-18T09:00:00+08:00",
        calendar_intervals=[
            {
                "start_at": "2026-09-18 00:00:00",
                "end_at": "2026-09-18T01:00:00Z",
            }
        ],
    )
    assert selected["id"] == 40


def test_invalid_calendar_interval_fails_closed_without_native_datetime_error():
    _assert_error(
        "NODE_CALENDAR_UNAVAILABLE",
        calendar_intervals=[
            {"start_at": "not-a-time", "end_at": "2026-09-18 12:00"}
        ],
    )


def test_adjacent_exclusive_intervals_do_not_overlap():
    selected = _validate(
        occupancy=[
            {
                "production_node_id": 10,
                "start_at": "2026-09-18 07:00",
                "end_at": "2026-09-18 08:00",
            },
            {
                "production_node_id": 10,
                "start_at": "2026-09-18 09:00",
                "end_at": "2026-09-18 10:00",
            },
        ]
    )
    assert selected["id"] == 40


def test_exclusive_overlap_makes_node_unavailable():
    error = _assert_error(
        "NODE_CALENDAR_UNAVAILABLE",
        occupancy=[
            {
                "production_node_id": 10,
                "start_at": "2026-09-18 08:30",
                "end_at": "2026-09-18 09:30",
            }
        ],
    )
    assert error.details == {
        "production_node_id": 10,
        "conflicting_occupancy_ids": [],
    }


def test_locked_overlap_has_precedence_over_regular_capacity_conflict():
    error = _assert_error(
        "LOCKED_TASK_CONFLICT",
        occupancy=[
            {
                "id": 90,
                "production_node_id": 10,
                "start_at": "2026-09-18 08:30",
                "end_at": "2026-09-18 09:30",
                "locked": 1,
            },
            {
                "id": 91,
                "production_node_id": 10,
                "start_at": "2026-09-18 08:15",
                "end_at": "2026-09-18 09:15",
            },
        ],
    )
    assert error.details == {
        "production_node_id": 10,
        "locked_occupancy_ids": [90],
    }


def test_aware_occupancy_overlap_is_compared_in_utc():
    error = _assert_error(
        "NODE_CALENDAR_UNAVAILABLE",
        occupancy=[
            {
                "id": 92,
                "production_node_id": 10,
                "start_at": "2026-09-18T00:30:00Z",
                "end_at": "2026-09-18T01:30:00Z",
            }
        ],
        requested_start_at="2026-09-18T08:00:00+08:00",
        requested_end_at="2026-09-18T09:00:00+08:00",
        calendar_intervals=[
            {
                "start_at": "2026-09-18T00:00:00Z",
                "end_at": "2026-09-18T04:00:00Z",
            }
        ],
    )
    assert error.details["conflicting_occupancy_ids"] == [92]


@pytest.mark.parametrize("capacity_mode", [None, "", "unknown", "ExclusiveX"])
def test_invalid_capacity_mode_fails_closed(capacity_mode):
    error = _assert_error(
        "NO_COMPATIBLE_NODE", node=_node(capacity_mode=capacity_mode)
    )
    assert error.details == {
        "production_node_id": 10,
        "reason": "invalid_capacity_mode",
        "capacity_mode": None if capacity_mode in (None, "") else capacity_mode,
    }


def test_node_text_enums_are_trimmed_before_validation():
    selected = _validate(node=_node(status=" active ", capacity_mode=" exclusive "))
    assert selected["id"] == 40


def test_batch_node_rejects_quantity_above_single_batch_capacity():
    capability = _capability(
        max_batch_quantity=10,
        batch_minutes=45,
        allow_mixed_orders=1,
    )
    error = _assert_error(
        "BATCH_CAPACITY_EXCEEDED",
        node=_node(capacity_mode="batch"),
        capabilities=[capability],
        quantity=11,
    )
    assert error.details == {
        "quantity": 11,
        "max_batch_quantity": 10,
    }


def test_batch_node_rejects_mixed_orders_when_capability_denies_them():
    capability = _capability(max_batch_quantity=10, batch_minutes=45)
    error = _assert_error(
        "BATCH_CAPACITY_EXCEEDED",
        node=_node(capacity_mode="batch"),
        capabilities=[capability],
        quantity=8,
        batch_orders=[30, 31],
    )
    assert error.details == {"order_ids": [30, 31], "allow_mixed_orders": False}


def test_batch_node_allows_repeated_rows_for_the_same_order():
    capability = _capability(max_batch_quantity=10, batch_minutes=45)
    selected = _validate(
        node=_node(capacity_mode="batch"),
        capabilities=[capability],
        quantity=8,
        batch_orders=[30, 30],
    )
    assert selected["id"] == 40


def test_batch_orders_must_include_the_current_order():
    capability = _capability(
        max_batch_quantity=10, batch_minutes=45, allow_mixed_orders=1
    )
    error = _assert_error(
        "BATCH_CAPACITY_EXCEEDED",
        node=_node(capacity_mode="batch"),
        capabilities=[capability],
        quantity=8,
        batch_orders=[31, 31],
    )
    assert error.details == {"order_id": 30, "order_ids": [31]}


@pytest.mark.parametrize("allow_mixed_orders", ["0", 0, False, None, "false"])
def test_false_like_mixed_order_flags_do_not_enable_mixing(allow_mixed_orders):
    error = _assert_error(
        "BATCH_CAPACITY_EXCEEDED",
        node=_node(capacity_mode="batch"),
        capabilities=[
            _capability(
                max_batch_quantity=10,
                batch_minutes=45,
                allow_mixed_orders=allow_mixed_orders,
            )
        ],
        quantity=8,
        batch_orders=[30, 31],
    )
    assert error.details["allow_mixed_orders"] is False


@pytest.mark.parametrize("allow_mixed_orders", [1, True, "1", "true", " TRUE "])
def test_true_like_mixed_order_flags_enable_mixing(allow_mixed_orders):
    selected = _validate(
        node=_node(capacity_mode="batch"),
        capabilities=[
            _capability(
                max_batch_quantity=10,
                batch_minutes=45,
                allow_mixed_orders=allow_mixed_orders,
            )
        ],
        quantity=8,
        batch_orders=[30, 31, 31],
    )
    assert selected["id"] == 40


@pytest.mark.parametrize(
    "batch_orders", [[], [30, None], [30, 0], [30, "bad"], 30, "30"]
)
def test_invalid_batch_order_inputs_fail_stably(batch_orders):
    with pytest.raises(NodeSchedulingError) as error:
        _validate(
            node=_node(capacity_mode="batch"),
            capabilities=[
                _capability(
                    max_batch_quantity=10,
                    batch_minutes=45,
                    allow_mixed_orders=1,
                )
            ],
            quantity=8,
            batch_orders=batch_orders,
        )
    assert error.value.code == "BATCH_CAPACITY_EXCEEDED"


@pytest.mark.parametrize("quantity", [0, -1, None, "1.5"])
def test_batch_duration_rejects_non_positive_or_non_integral_quantity(quantity):
    with pytest.raises(NodeSchedulingError) as error:
        ProductionNodePolicy.batch_duration_minutes(
            quantity,
            {
                "max_batch_quantity": 10,
                "batch_minutes": 45,
                "changeover_minutes": 15,
            },
        )
    assert error.value.code == "BATCH_CAPACITY_EXCEEDED"


@pytest.mark.parametrize(
    "capability",
    [
        {"max_batch_quantity": None, "batch_minutes": 45},
        {"max_batch_quantity": 0, "batch_minutes": 45},
        {"max_batch_quantity": 10, "batch_minutes": None},
        {"max_batch_quantity": 10, "batch_minutes": 0},
        {
            "max_batch_quantity": 10,
            "batch_minutes": 45,
            "changeover_minutes": -1,
        },
    ],
)
def test_batch_duration_rejects_missing_or_invalid_configuration(capability):
    with pytest.raises(NodeSchedulingError) as error:
        ProductionNodePolicy.batch_duration_minutes(10, capability)
    assert error.value.code == "BATCH_CAPACITY_EXCEEDED"


def test_batch_duration_uses_exact_ceiling_batches_and_changeover():
    capability = {
        "max_batch_quantity": 10,
        "batch_minutes": 45,
        "changeover_minutes": 15,
    }

    assert ProductionNodePolicy.batch_duration_minutes(20, capability) == 90
    assert ProductionNodePolicy.batch_duration_minutes(21, capability) == 135
    assert (
        ProductionNodePolicy.batch_duration_minutes(
            21, capability, changeover_required=True
        )
        == 150
    )


def test_serial_item_cannot_split_across_nodes():
    with pytest.raises(NodeSchedulingError) as error:
        ProductionNodePolicy.validate_serial_allocation(
            serial_ids=["26072401-001"],
            allocations=[
                {
                    "production_node_id": 10,
                    "serial_ids": ["26072401-001"],
                },
                {
                    "production_node_id": 11,
                    "serial_ids": ["26072401-001"],
                },
            ],
        )
    assert error.value.code == "SERIAL_ITEM_SPLIT_FORBIDDEN"
    assert error.value.details == {"duplicate_serial_ids": ["26072401-001"]}


@pytest.mark.parametrize(
    ("serial_ids", "allocations", "details"),
    [
        (
            ["A", "A"],
            [{"production_node_id": 10, "serial_ids": ["A"]}],
            {"duplicate_input_serial_ids": ["A"]},
        ),
        (
            ["A", "B"],
            [{"production_node_id": 10, "serial_ids": ["A"]}],
            {"missing_serial_ids": ["B"], "unexpected_serial_ids": []},
        ),
        (
            ["A"],
            [{"production_node_id": 10, "serial_ids": ["A", "B"]}],
            {"missing_serial_ids": [], "unexpected_serial_ids": ["B"]},
        ),
    ],
)
def test_serial_allocation_detects_duplicate_or_non_conserved_inputs(
    serial_ids, allocations, details
):
    with pytest.raises(NodeSchedulingError) as error:
        ProductionNodePolicy.validate_serial_allocation(serial_ids, allocations)
    assert error.value.code == "SERIAL_ITEM_SPLIT_FORBIDDEN"
    assert error.value.details == details


def test_serial_allocation_is_valid_when_each_item_has_exactly_one_node():
    serial_ids = ["A", "B"]
    allocations = [
        {"production_node_id": 10, "serial_ids": ["A"]},
        {"production_node_id": 11, "serial_ids": ["B"]},
    ]
    before_serials = deepcopy(serial_ids)
    before_allocations = deepcopy(allocations)

    assert ProductionNodePolicy.validate_serial_allocation(serial_ids, allocations) is True
    assert serial_ids == before_serials
    assert allocations == before_allocations


@pytest.mark.parametrize("production_node_id", [None, 0, -1, "bad", True])
def test_serial_allocation_requires_a_positive_node_id(production_node_id):
    with pytest.raises(NodeSchedulingError) as error:
        ProductionNodePolicy.validate_serial_allocation(
            ["A"],
            [{"production_node_id": production_node_id, "serial_ids": ["A"]}],
        )
    assert error.value.code == "SERIAL_ITEM_SPLIT_FORBIDDEN"
    assert error.value.details == {
        "allocation_index": 0,
        "production_node_id": production_node_id,
    }


def test_node_ranking_is_stable_and_does_not_mutate_input():
    nodes = [
        {
            "id": 12,
            "finish_at": "2026-09-18 11:00",
            "risk": 0,
            "load_minutes": 90,
        },
        {
            "id": 13,
            "finish_at": "2026-09-18 10:00",
            "risk": 1,
            "load_minutes": 120,
        },
        {
            "id": 11,
            "finish_at": "2026-09-18 11:00",
            "risk": 0,
            "load_minutes": 90,
        },
    ]
    before = deepcopy(nodes)

    ranked = ProductionNodePolicy.rank_nodes(nodes)

    assert [node["id"] for node in ranked] == [13, 11, 12]
    assert nodes == before
    assert all(ranked[index] is not nodes[index] for index in range(len(nodes)))


def test_node_ranking_normalizes_timezones_and_puts_invalid_finish_last():
    ranked = ProductionNodePolicy.rank_nodes(
        [
            {"id": 3, "finish_at": "invalid", "risk": 0, "load_minutes": 0},
            {
                "id": 2,
                "finish_at": "2026-09-18T09:00:00+08:00",
                "risk": 0,
                "load_minutes": 0,
            },
            {
                "id": 1,
                "finish_at": "2026-09-18 01:00:00",
                "risk": 0,
                "load_minutes": 0,
            },
        ]
    )
    assert [row["id"] for row in ranked] == [1, 2, 3]


def test_node_ranking_missing_ids_is_permutation_invariant():
    first = {
        "node_code": "B",
        "finish_at": "2026-09-18 11:00",
        "risk": "bad",
        "load_minutes": None,
    }
    second = {
        "node_code": "A",
        "finish_at": "2026-09-18 11:00",
        "risk": "bad",
        "load_minutes": None,
    }

    forward = ProductionNodePolicy.rank_nodes([first, second])
    reverse = ProductionNodePolicy.rank_nodes([second, first])

    assert [row["node_code"] for row in forward] == [
        row["node_code"] for row in reverse
    ]
