"""Pure admission policy for writes to the retired production-line field."""

from modules.domain.errors import LegacyProcessLineWriteBlockedError


LEGACY_PROCESS_LINE_FIELD = "production_line_id"
LEGACY_PROCESS_LINE_WRITE_MESSAGE = "Legacy 订单产线写入已关闭，请使用生产节点排程接口"


def assert_legacy_process_line_write_allowed(data, *, legacy_write_blocked):
    """Reject an explicit legacy-line write when the cutover switch is enabled.

    The switch is passed explicitly so this policy stays independent from
    configuration, Flask, services, repositories, and mutable global state.
    The input mapping is never changed; omitted fields remain compatible with
    the pre-cutover behavior.
    """
    if (
        legacy_write_blocked
        and isinstance(data, dict)
        and LEGACY_PROCESS_LINE_FIELD in data
    ):
        raise LegacyProcessLineWriteBlockedError(
            LEGACY_PROCESS_LINE_WRITE_MESSAGE,
            details={"fields": [LEGACY_PROCESS_LINE_FIELD]},
        )
