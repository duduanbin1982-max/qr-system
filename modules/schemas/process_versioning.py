"""Strict request schemas for versioned process master data APIs."""


_idempotency_key = {
    "type": "string",
    "minLength": 8,
    "maxLength": 128,
    "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
}
_row_version = {"type": "integer", "minimum": 0}
_reason = {"type": "string", "minLength": 2, "maxLength": 512, "pattern": r"\S"}
_name = {"type": "string", "minLength": 1, "maxLength": 128, "pattern": r"\S"}
_category = {"type": "string", "enum": ["结构件", "机加工"]}
_positive_id = {"type": "integer", "minimum": 1}
_flag = {"type": "integer", "enum": [0, 1]}

_process_content = {
    "name": _name,
    "category": _category,
    "description": {"type": "string", "maxLength": 512},
    "seq_order": {"type": "integer", "minimum": 0, "maximum": 1000000},
}

route_version_item = {
    "type": "object",
    "additionalProperties": False,
    "required": ["process_id", "process_version_id", "seq_order"],
    "properties": {
        "process_id": _positive_id,
        "process_version_id": _positive_id,
        "seq_order": {"type": "integer", "minimum": 0, "maximum": 1000000},
        "is_required": _flag,
        "required_audit": _flag,
    },
}

_route_content = {
    "name": _name,
    "category": _category,
    "description": {"type": "string", "maxLength": 512},
    "items": {
        "type": "array",
        "minItems": 1,
        "maxItems": 100,
        "uniqueItems": True,
        "items": route_version_item,
    },
}

price_disposition = {
    "type": "object",
    "additionalProperties": False,
    "required": ["process_id", "disposition"],
    "properties": {
        "process_id": _positive_id,
        "disposition": {
            "type": "string",
            "enum": ["price_version", "not_applicable"],
        },
        "price_version_id": _positive_id,
        "reason": {"type": "string", "maxLength": 512},
    },
}

release_exception = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "route_version_id",
        "retained_process_version_id",
        "replacement_process_version_id",
        "reason",
        "approved_by",
        "approved_by_name",
        "valid_from",
        "valid_to",
    ],
    "properties": {
        "route_version_id": _positive_id,
        "retained_process_version_id": _positive_id,
        "replacement_process_version_id": _positive_id,
        "reason": _reason,
        "approved_by": _positive_id,
        "approved_by_name": _name,
        "valid_from": {"type": "string", "minLength": 10, "maxLength": 32},
        "valid_to": {"type": "string", "minLength": 10, "maxLength": 32},
    },
}


def _object(required, properties, *, min_properties=None):
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": list(required),
        "properties": properties,
    }
    if min_properties is not None:
        schema["minProperties"] = min_properties
    return schema


process_version_create = _object(
    ["name", "category", "revision_reason", "idempotency_key"],
    {
        "name": _name,
        "category": _category,
        "revision_reason": _reason,
        "idempotency_key": _idempotency_key,
        "description": _process_content["description"],
        "seq_order": _process_content["seq_order"],
    },
)


process_revision_create = _object(
    ["row_version", "revision_reason", "idempotency_key"],
    {
        "row_version": _row_version,
        "revision_reason": _reason,
        "idempotency_key": _idempotency_key,
        **_process_content,
    },
)

process_version_update = _object(
    ["row_version"],
    {"row_version": _row_version, **_process_content},
    min_properties=2,
)

route_version_create = _object(
    ["name", "category", "items", "revision_reason", "idempotency_key"],
    {
        "name": _name,
        "category": _category,
        "items": _route_content["items"],
        "revision_reason": _reason,
        "idempotency_key": _idempotency_key,
        "description": _route_content["description"],
    },
)

route_revision_create = _object(
    ["row_version", "revision_reason", "idempotency_key"],
    {
        "row_version": _row_version,
        "revision_reason": _reason,
        "idempotency_key": _idempotency_key,
        **_route_content,
    },
)

route_version_update = _object(
    ["row_version"],
    {"row_version": _row_version, **_route_content},
    min_properties=2,
)

version_transition = _object(
    ["row_version", "idempotency_key"],
    {"row_version": _row_version, "idempotency_key": _idempotency_key},
)

version_reject = _object(
    ["row_version", "idempotency_key", "reason"],
    {
        "row_version": _row_version,
        "idempotency_key": _idempotency_key,
        "reason": _reason,
    },
)

route_version_approve = _object(
    ["row_version", "idempotency_key"],
    {
        "row_version": _row_version,
        "idempotency_key": _idempotency_key,
        "required_price_process_ids": {
            "type": "array",
            "uniqueItems": True,
            "maxItems": 100,
            "items": _positive_id,
        },
        "price_dispositions": {
            "type": "array",
            "uniqueItems": True,
            "maxItems": 100,
            "items": price_disposition,
        },
    },
)

lifecycle_request = _object(
    ["row_version", "idempotency_key"],
    {
        "row_version": _row_version,
        "idempotency_key": _idempotency_key,
        "lifecycle_reason": _reason,
        "reason": _reason,
    },
)
lifecycle_request["anyOf"] = [
    {"required": ["lifecycle_reason"]},
    {"required": ["reason"]},
]

lifecycle_approve = _object(
    ["row_version", "idempotency_key"],
    {"row_version": _row_version, "idempotency_key": _idempotency_key},
)

master_data_release_create = _object(
    ["release_no", "revision_reason", "idempotency_key"],
    {
        "release_no": {
            "type": "string",
            "minLength": 3,
            "maxLength": 64,
            "pattern": r"\S",
        },
        "revision_reason": _reason,
        "idempotency_key": _idempotency_key,
        "process_version_ids": {
            "type": "array",
            "uniqueItems": True,
            "maxItems": 200,
            "items": _positive_id,
        },
        "route_version_ids": {
            "type": "array",
            "uniqueItems": True,
            "maxItems": 200,
            "items": _positive_id,
        },
        "price_version_ids": {
            "type": "array",
            "uniqueItems": True,
            "maxItems": 200,
            "items": _positive_id,
        },
    },
)

master_data_release_submit = _object(
    ["row_version", "idempotency_key"],
    {
        "row_version": _row_version,
        "idempotency_key": _idempotency_key,
        "approved_exceptions": {
            "type": "array",
            "uniqueItems": True,
            "maxItems": 200,
            "items": release_exception,
        },
    },
)

master_data_release_approve = _object(
    ["row_version", "idempotency_key"],
    {
        "row_version": _row_version,
        "idempotency_key": _idempotency_key,
        "required_price_process_ids": {
            "type": "array",
            "uniqueItems": True,
            "maxItems": 100,
            "items": _positive_id,
        },
        "price_dispositions": {
            "type": "array",
            "uniqueItems": True,
            "maxItems": 100,
            "items": price_disposition,
        },
    },
)

master_data_release_reject = version_reject

process_versioning_schemas = {
    "process_version_create": process_version_create,
    "process_revision_create": process_revision_create,
    "process_version_update": process_version_update,
    "route_version_create": route_version_create,
    "route_revision_create": route_revision_create,
    "route_version_update": route_version_update,
    "version_transition": version_transition,
    "version_reject": version_reject,
    "route_version_approve": route_version_approve,
    "lifecycle_request": lifecycle_request,
    "lifecycle_approve": lifecycle_approve,
    "master_data_release_create": master_data_release_create,
    "master_data_release_submit": master_data_release_submit,
    "master_data_release_approve": master_data_release_approve,
    "master_data_release_reject": master_data_release_reject,
}
