"""Strict request schemas for versioned process configuration."""


_row_version = {"type": "integer", "minimum": 0}
_idempotency_key = {
    "type": "string",
    "minLength": 8,
    "maxLength": 128,
    "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
}
_reason = {"type": "string", "minLength": 2, "maxLength": 512, "pattern": r"\S"}
_flag = {"type": "integer", "enum": [0, 1]}
_config_fields = {
    "process_order_mode": {
        "type": "string",
        "enum": ["sequential", "out_of_order"],
    },
    "serial_process_report_mode": {
        "type": "string",
        "enum": ["strict", "controlled_backfill"],
    },
    "limit_by_prev_process": _flag,
    "limit_by_order_qty": _flag,
    "approval_enabled": _flag,
}
_has_config_change = {
    "anyOf": [{"required": [field]} for field in _config_fields]
}


process_config_revision_create = {
    "type": "object",
    "additionalProperties": False,
    "required": ["row_version", "revision_reason", "idempotency_key"],
    "properties": {
        "row_version": _row_version,
        "revision_reason": _reason,
        "idempotency_key": _idempotency_key,
        **_config_fields,
    },
    **_has_config_change,
}

process_config_revision_update = {
    "type": "object",
    "additionalProperties": False,
    "required": ["row_version", "idempotency_key"],
    "properties": {
        "row_version": _row_version,
        "revision_reason": _reason,
        "idempotency_key": _idempotency_key,
        **_config_fields,
    },
    **_has_config_change,
}

process_config_transition = {
    "type": "object",
    "additionalProperties": False,
    "required": ["row_version", "idempotency_key"],
    "properties": {
        "row_version": _row_version,
        "idempotency_key": _idempotency_key,
    },
}

process_config_reject = {
    "type": "object",
    "additionalProperties": False,
    "required": ["row_version", "idempotency_key", "reason"],
    "properties": {
        "row_version": _row_version,
        "idempotency_key": _idempotency_key,
        "reason": _reason,
    },
}

process_config_schemas = {
    "process_config_revision_create": process_config_revision_create,
    "process_config_revision_update": process_config_revision_update,
    "process_config_transition": process_config_transition,
    "process_config_reject": process_config_reject,
}
