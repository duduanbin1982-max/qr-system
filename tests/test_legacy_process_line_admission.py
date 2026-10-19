"""Pure and compatibility contracts for the retired production-line field."""

import pytest

from modules.domain.errors import LegacyProcessLineWriteBlockedError
from modules.domain.legacy_process_line_admission import (
    LEGACY_PROCESS_LINE_FIELD,
    assert_legacy_process_line_write_allowed,
)
from modules.services.order_service import OrderService
from modules.services.schedule_service import ScheduleService


PAYLOADS = (
    {},
    {"plan_start": "2026-10-15"},
    {LEGACY_PROCESS_LINE_FIELD: None},
    {LEGACY_PROCESS_LINE_FIELD: 17},
)


@pytest.mark.parametrize(
    "legacy_write_blocked", [False, True], ids=["open", "blocked"]
)
@pytest.mark.parametrize(
    "payload",
    PAYLOADS,
    ids=["missing", "other-field", "explicit-null", "explicit-id"],
)
def test_pure_policy_covers_switch_and_field_presence_matrix(
    legacy_write_blocked, payload
):
    original = dict(payload)
    if legacy_write_blocked and LEGACY_PROCESS_LINE_FIELD in payload:
        with pytest.raises(LegacyProcessLineWriteBlockedError) as caught:
            assert_legacy_process_line_write_allowed(
                payload,
                legacy_write_blocked=legacy_write_blocked,
            )
        assert caught.value.to_payload() == {
            "error": "Legacy 订单产线写入已关闭，请使用生产节点排程接口",
            "code": "LEGACY_PROCESS_LINE_WRITE_BLOCKED",
            "details": {"fields": [LEGACY_PROCESS_LINE_FIELD]},
            "action": "use_production_node_api",
        }
    else:
        assert (
            assert_legacy_process_line_write_allowed(
                payload,
                legacy_write_blocked=legacy_write_blocked,
            )
            is None
        )
    assert payload == original


@pytest.mark.parametrize("payload", [None, [], "production-line"])
def test_pure_policy_preserves_non_dict_inputs(payload):
    assert (
        assert_legacy_process_line_write_allowed(
            payload,
            legacy_write_blocked=True,
        )
        is None
    )


@pytest.mark.parametrize(
    "guard",
    [
        OrderService._assert_no_legacy_production_line_write,
        ScheduleService.assert_no_legacy_production_line_write,
    ],
)
def test_compatibility_guards_delegate_same_public_error_contract(monkeypatch, guard):
    monkeypatch.setattr(
        "modules.config.LEGACY_PROCESS_LINE_WRITE_BLOCKED",
        True,
    )
    with pytest.raises(LegacyProcessLineWriteBlockedError) as caught:
        guard({LEGACY_PROCESS_LINE_FIELD: None})
    assert caught.value.status_code == 409
    assert caught.value.to_payload() == {
        "error": "Legacy 订单产线写入已关闭，请使用生产节点排程接口",
        "code": "LEGACY_PROCESS_LINE_WRITE_BLOCKED",
        "details": {"fields": [LEGACY_PROCESS_LINE_FIELD]},
        "action": "use_production_node_api",
    }
