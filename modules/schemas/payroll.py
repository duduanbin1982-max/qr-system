"""Strict request schemas for route price version APIs."""


_positive_id = {"type": "integer", "minimum": 1}
_digest = {"type": "string", "minLength": 1, "maxLength": 128}
_idempotency_key = {
    "type": "string",
    "minLength": 8,
    "maxLength": 128,
    "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
}

route_price_version_create = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "route_id",
        "route_version_id",
        "process_id",
        "process_version_id",
        "expected_route_content_digest",
        "expected_process_content_digest",
        "valid_from",
        "idempotency_key",
    ],
    "properties": {
        "route_id": _positive_id,
        "route_version_id": _positive_id,
        "process_id": _positive_id,
        "process_version_id": _positive_id,
        "expected_route_content_digest": _digest,
        "expected_process_content_digest": _digest,
        "normal_unit_price": {
            "oneOf": [
                {"type": "number", "exclusiveMinimum": 0},
                {"type": "string", "minLength": 1, "maxLength": 32, "pattern": r"^\d+(\.\d+)?$"},
            ]
        },
        "normal_unit_price_micros": {"type": "integer", "minimum": 1},
        "rework_rate_basis_points": {"type": "integer", "minimum": 0, "maximum": 10000},
        "rework_rate_percent": {"type": "number", "minimum": 0, "maximum": 100},
        "valid_from": {"type": "string", "minLength": 10, "maxLength": 32},
        "remark": {"type": "string", "maxLength": 512},
        "idempotency_key": _idempotency_key,
    },
    "oneOf": [
        {
            "required": ["normal_unit_price"],
            "not": {"required": ["normal_unit_price_micros"]},
        },
        {
            "required": ["normal_unit_price_micros"],
            "not": {"required": ["normal_unit_price"]},
        },
    ],
}

route_price_version_void = {
    "type": "object",
    "additionalProperties": False,
    "required": ["row_version", "reason", "idempotency_key"],
    "properties": {
        "row_version": {"type": "integer", "minimum": 0},
        "reason": {"type": "string", "minLength": 2, "maxLength": 512, "pattern": r"\S"},
        "idempotency_key": _idempotency_key,
    },
}

historical_price_manual_draft_create = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "normal_unit_price", "valid_from", "confirmation_reason", "idempotency_key",
    ],
    "properties": {
        "normal_unit_price": {
            "oneOf": [
                {"type": "number", "exclusiveMinimum": 0},
                {"type": "string", "minLength": 1, "maxLength": 32, "pattern": r"^\d+(\.\d+)?$"},
            ]
        },
        "rework_rate_configured": {"type": "boolean"},
        "rework_rate_percent": {"type": "number", "minimum": 0, "maximum": 100},
        "valid_from": {"type": "string", "minLength": 10, "maxLength": 32},
        "valid_to": {"type": ["string", "null"], "minLength": 10, "maxLength": 32},
        "confirmation_reason": {"type": "string", "minLength": 2, "maxLength": 512, "pattern": r"\S"},
        "idempotency_key": _idempotency_key,
    },
}

historical_price_manual_draft_void = {
    "type": "object",
    "additionalProperties": False,
    "required": ["row_version", "reason", "idempotency_key"],
    "properties": {
        "row_version": {"type": "integer", "minimum": 0},
        "reason": {"type": "string", "minLength": 2, "maxLength": 512, "pattern": r"\S"},
        "idempotency_key": _idempotency_key,
    },
}

historical_price_manual_draft_approve = {
    "type": "object",
    "additionalProperties": False,
    "required": ["row_version", "idempotency_key"],
    "properties": {
        "row_version": {"type": "integer", "minimum": 0},
        "idempotency_key": _idempotency_key,
    },
}

payroll_schemas = {
    "route_price_version_create": route_price_version_create,
    "route_price_version_void": route_price_version_void,
    "historical_price_manual_draft_create": historical_price_manual_draft_create,
    "historical_price_manual_draft_void": historical_price_manual_draft_void,
    "historical_price_manual_draft_approve": historical_price_manual_draft_approve,
}
