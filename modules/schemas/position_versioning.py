"""Strict request schemas for versioned position master data APIs."""


_idempotency_key = {
    "type": "string",
    "minLength": 8,
    "maxLength": 128,
    "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
}
_row_version = {"type": "integer", "minimum": 0}
_reason = {"type": "string", "minLength": 2, "maxLength": 512, "pattern": r"\S"}
_name = {"type": "string", "minLength": 1, "maxLength": 128, "pattern": r"\S"}
_description = {"type": "string", "maxLength": 512}
_process_ids = {
    "type": "array",
    "uniqueItems": True,
    "maxItems": 100,
    "items": {"type": "integer", "minimum": 1},
}
_identity_flags = {
    "organizational_meaning_changed": {"type": "boolean"},
    "responsibility_changed": {"type": "boolean"},
    "skill_requirement_changed": {"type": "boolean"},
    "root_identity_changed": {"type": "boolean"},
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


position_version_create = _object(
    ["name", "revision_reason", "idempotency_key"],
    {
        "name": _name,
        "description": _description,
        "process_ids": _process_ids,
        "revision_reason": _reason,
        "idempotency_key": _idempotency_key,
    },
)

position_revision_create = _object(
    ["row_version", "revision_reason", "idempotency_key"],
    {
        "row_version": _row_version,
        "revision_reason": _reason,
        "idempotency_key": _idempotency_key,
        "name": _name,
        "description": _description,
        "process_ids": _process_ids,
        **_identity_flags,
    },
)

position_version_update = _object(
    ["row_version", "idempotency_key"],
    {
        "row_version": _row_version,
        "idempotency_key": _idempotency_key,
        "name": _name,
        "description": _description,
        "process_ids": _process_ids,
        **_identity_flags,
    },
    min_properties=3,
)

position_version_transition = _object(
    ["row_version", "idempotency_key"],
    {"row_version": _row_version, "idempotency_key": _idempotency_key},
)

position_version_terminal = _object(
    ["row_version", "idempotency_key", "reason"],
    {
        "row_version": _row_version,
        "idempotency_key": _idempotency_key,
        "reason": _reason,
    },
)

position_lifecycle_request = _object(
    ["row_version", "idempotency_key"],
    {
        "row_version": _row_version,
        "idempotency_key": _idempotency_key,
        "lifecycle_reason": _reason,
        "reason": _reason,
    },
)
position_lifecycle_request["anyOf"] = [
    {"required": ["lifecycle_reason"]},
    {"required": ["reason"]},
]

position_lifecycle_approve = position_version_transition
position_lifecycle_reject = position_version_terminal


position_versioning_schemas = {
    "position_version_create": position_version_create,
    "position_revision_create": position_revision_create,
    "position_version_update": position_version_update,
    "position_version_transition": position_version_transition,
    "position_version_terminal": position_version_terminal,
    "position_lifecycle_request": position_lifecycle_request,
    "position_lifecycle_approve": position_lifecycle_approve,
    "position_lifecycle_reject": position_lifecycle_reject,
}
