"""Domain rules for versioned process-reporting configuration."""

from modules.domain.errors import ConflictError, ValidationError


PROCESS_CONFIG_FIELDS = (
    "process_order_mode",
    "serial_process_report_mode",
    "limit_by_prev_process",
    "limit_by_order_qty",
    "approval_enabled",
)

PROCESS_CONFIG_DEFAULTS = {
    "process_order_mode": "sequential",
    "serial_process_report_mode": "strict",
    "limit_by_prev_process": 1,
    "limit_by_order_qty": 1,
    "approval_enabled": 1,
}

PROCESS_CONFIG_FIELD_LABELS = {
    "process_order_mode": "工序报工顺序",
    "serial_process_report_mode": "序列号报工规则",
    "limit_by_prev_process": "上道工序累计上限",
    "limit_by_order_qty": "订单总数上限",
    "approval_enabled": "报工审批",
}

PROCESS_ORDER_MODES = frozenset({"sequential", "out_of_order"})
SERIAL_REPORT_MODES = frozenset({"strict", "controlled_backfill"})
REVISION_STATUSES = frozenset(
    {"draft", "pending_approval", "published", "rejected"}
)


class ProcessConfigStaleError(ConflictError):
    code = "PROCESS_CONFIG_STALE"

    def to_payload(self):
        payload = super().to_payload()
        payload["action"] = "reload_process_config"
        return payload


class ProcessConfigApprovalSeparationError(ConflictError):
    code = "PROCESS_CONFIG_APPROVAL_SEPARATION_REQUIRED"

    def to_payload(self):
        payload = super().to_payload()
        payload["action"] = "select_different_approver"
        return payload


class ProcessConfigOpenRevisionError(ConflictError):
    code = "PROCESS_CONFIG_OPEN_REVISION_EXISTS"

    def to_payload(self):
        payload = super().to_payload()
        payload["action"] = "review_open_process_config_revision"
        return payload


class LegacyProcessConfigWriteBlockedError(ConflictError):
    code = "LEGACY_PROCESS_CONFIG_WRITE_BLOCKED"

    def to_payload(self):
        payload = super().to_payload()
        payload["action"] = "use_process_config_api"
        return payload


def _normalize_flag(value, field):
    if value in (True, 1, "1"):
        return 1
    if value in (False, 0, "0"):
        return 0
    raise ValidationError(
        f"{PROCESS_CONFIG_FIELD_LABELS[field]}必须是开启或关闭状态",
        details={"field": field},
    )


def normalize_process_config(values, *, base=None, require_changes=False):
    if not isinstance(values, dict):
        raise ValidationError("工艺配置必须是对象")
    unknown = sorted(set(values) - set(PROCESS_CONFIG_FIELDS))
    if unknown:
        raise ValidationError(
            "包含不支持的工艺配置字段", details={"fields": unknown}
        )

    normalized = dict(PROCESS_CONFIG_DEFAULTS if base is None else base)
    for field in PROCESS_CONFIG_FIELDS:
        if field not in normalized:
            normalized[field] = PROCESS_CONFIG_DEFAULTS[field]
        if field not in values:
            continue
        value = values[field]
        if field == "process_order_mode":
            value = str(value or "").strip()
            if value not in PROCESS_ORDER_MODES:
                raise ValidationError("工序报工顺序无效", details={"field": field})
            normalized[field] = value
        elif field == "serial_process_report_mode":
            value = str(value or "").strip()
            if value not in SERIAL_REPORT_MODES:
                raise ValidationError("序列号报工规则无效", details={"field": field})
            normalized[field] = value
        else:
            normalized[field] = _normalize_flag(value, field)

    if (
        normalized["process_order_mode"] == "out_of_order"
        and normalized["limit_by_prev_process"] != 0
    ):
        normalized["limit_by_prev_process"] = 0

    if require_changes and not changed_process_config_fields(base or {}, normalized):
        raise ValidationError("工艺配置没有发生变化")
    return normalized


def changed_process_config_fields(current, candidate):
    return [
        field
        for field in PROCESS_CONFIG_FIELDS
        if candidate.get(field) != current.get(field)
    ]


def require_row_version(value):
    if isinstance(value, bool):
        raise ValidationError("row_version 必须是整数")
    try:
        version = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("row_version 必须是整数") from exc
    if version < 0:
        raise ValidationError("row_version 不能小于 0")
    return version


def assert_row_version(expected, actual):
    expected = require_row_version(expected)
    actual = require_row_version(actual)
    if expected != actual:
        raise ProcessConfigStaleError(
            "工艺配置已被其他用户更新，请刷新后重试",
            details={"expected": expected, "actual": actual},
        )
    return actual


def assert_approval_separation(prepared_by, approved_by):
    try:
        prepared_by = int(prepared_by)
        approved_by = int(approved_by)
    except (TypeError, ValueError) as exc:
        raise ValidationError("制单人或批准人无效") from exc
    if prepared_by <= 0 or approved_by <= 0:
        raise ValidationError("制单人或批准人无效")
    if prepared_by == approved_by:
        raise ProcessConfigApprovalSeparationError("制单人与批准人必须不同")
    return True
