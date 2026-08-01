import pytest

from modules.domain.order_lifecycle import OrderLifecycle


def test_order_lifecycle_allows_configured_transition():
    OrderLifecycle.validate_update(
        {"status": "pending", "deleted_at": None},
        {"status": "producing"},
    )


def test_order_lifecycle_rejects_manual_completion():
    with pytest.raises(ValueError, match="只能由系统"):
        OrderLifecycle.validate_update(
            {"status": "producing", "deleted_at": None},
            {"status": "completed"},
        )


def test_order_lifecycle_rejects_invalid_transition():
    with pytest.raises(ValueError, match="不允许从"):
        OrderLifecycle.validate_update(
            {"status": "producing", "deleted_at": None},
            {"status": "pending"},
        )


def test_order_lifecycle_keeps_completed_order_readonly():
    with pytest.raises(ValueError, match="已完成订单已归档"):
        OrderLifecycle.validate_update(
            {"status": "completed", "deleted_at": None},
            {"remark": "blocked"},
        )


def test_order_lifecycle_normalizes_reopen_request():
    reason, status = OrderLifecycle.normalize_reopen(
        {"status": "completed", "deleted_at": None},
        " 返修重新生产 ",
        "PENDING",
    )

    assert reason == "返修重新生产"
    assert status == "pending"
