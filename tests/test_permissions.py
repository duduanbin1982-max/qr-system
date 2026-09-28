import itertools

import pytest

from modules import config
from modules.permission_catalog import ACTION_LABELS, ACTION_PERMISSION_DEFS


FLAG_NAMES = (
    "INVENTORY_PRODUCT_QUERY_ENABLED",
    "INVENTORY_ALLOCATION_PREVIEW_ENABLED",
    "INVENTORY_CROSS_ORDER_OUTBOUND_ENABLED",
    "INVENTORY_PRODUCT_THRESHOLD_ENABLED",
)


def _is_valid_inventory_flag_combination(values):
    query, preview, cross_order, threshold = values
    return (
        (not preview or query)
        and (not cross_order or (query and preview))
        and (not threshold or query)
    )


INVALID_INVENTORY_FLAG_ENVIRONMENTS = [
    dict(zip(FLAG_NAMES, ("true" if enabled else "false" for enabled in values)))
    for values in itertools.product((False, True), repeat=4)
    if not _is_valid_inventory_flag_combination(values)
]


def test_inventory_product_flags_default_to_disabled():
    assert config.load_inventory_product_flags({}) == {
        name: False for name in FLAG_NAMES
    }
    assert {name: getattr(config, name) for name in FLAG_NAMES} == {
        name: False for name in FLAG_NAMES
    }


def test_inventory_product_flags_accept_all_enabled():
    assert config.load_inventory_product_flags(
        {name: "true" for name in FLAG_NAMES}
    ) == {name: True for name in FLAG_NAMES}


@pytest.mark.parametrize("environment", INVALID_INVENTORY_FLAG_ENVIRONMENTS)
def test_inventory_product_flags_reject_every_invalid_combination(environment):
    with pytest.raises(RuntimeError):
        config.load_inventory_product_flags(environment)


def test_inventory_permissions_extend_catalog_and_warehouse_role():
    expected_actions = [
        "view",
        "create",
        "edit",
        "delete",
        "export",
        "inbound",
        "outbound",
        "allocate",
        "reserve",
        "adjust",
        "audit",
        "manage_threshold",
    ]
    assert ACTION_PERMISSION_DEFS["inventory"] == ("库存", expected_actions)
    assert {
        "inbound": "入库",
        "outbound": "出库",
        "allocate": "分配",
        "reserve": "预留",
        "manage_threshold": "安全库存管理",
    }.items() <= ACTION_LABELS.items()

    permissions = config.PREDEFINED_ROLES["warehouse_keeper"]["permissions"]
    assert {
        "inventory:view",
        "inventory:create",
        "inventory:edit",
        "inventory:delete",
        *(f"inventory:{action}" for action in expected_actions[4:]),
    }.issubset(permissions)
