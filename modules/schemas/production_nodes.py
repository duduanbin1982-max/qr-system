"""Strict request schemas for production-node administration."""

_KEY = {"type": "string", "minLength": 8, "maxLength": 128}
_REASON = {"type": "string", "minLength": 1, "maxLength": 1024}
_DATETIME = {
    "type": "string",
    "pattern": r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$",
}

production_node_write = {
    "type": "object",
    "required": [
        "process_id",
        "node_code",
        "node_name",
        "capacity_mode",
        "calendar_id",
        "row_version",
        "idempotency_key",
    ],
    "properties": {
        "process_id": {"type": "integer", "minimum": 1},
        "node_code": {"type": "string", "minLength": 1, "maxLength": 64},
        "node_name": {"type": "string", "minLength": 1, "maxLength": 128},
        "capacity_mode": {"enum": ["exclusive", "batch"]},
        "status": {"enum": ["active", "inactive", "maintenance"]},
        "calendar_id": {"type": "integer", "minimum": 1},
        "row_version": {"type": "integer", "minimum": 1},
        "reason": _REASON,
        "idempotency_key": _KEY,
    },
    "additionalProperties": False,
}

_nullable_id = {"type": ["integer", "null"], "minimum": 1}
_nullable_positive_integer = {"type": ["integer", "null"], "minimum": 1}
_nullable_positive_number = {
    "type": ["number", "null"],
    "exclusiveMinimum": 0,
}

production_node_capability = {
    "type": "object",
    "properties": {
        "product_id": _nullable_id,
        "product_family": {"type": "string", "maxLength": 128},
        "material_code": {"type": "string", "maxLength": 128},
        "specification": {"type": "string", "maxLength": 256},
        "route_version_id": _nullable_id,
        "process_version_id": _nullable_id,
        "max_batch_quantity": _nullable_positive_integer,
        "batch_minutes": _nullable_positive_number,
        "changeover_minutes": {"type": "number", "minimum": 0},
        "allow_mixed_orders": {"type": "boolean"},
        "status": {"enum": ["active", "inactive"]},
    },
    "additionalProperties": False,
}

production_node_capabilities_replace = {
    "type": "object",
    "required": ["capabilities", "reason", "idempotency_key"],
    "properties": {
        "capabilities": {
            "type": "array",
            "maxItems": 100,
            "items": production_node_capability,
        },
        "reason": _REASON,
        "idempotency_key": _KEY,
    },
    "additionalProperties": False,
}

production_node_calendar_override_create = {
    "type": "object",
    "required": [
        "start_at",
        "end_at",
        "override_type",
        "reason",
        "idempotency_key",
    ],
    "properties": {
        "start_at": _DATETIME,
        "end_at": _DATETIME,
        "override_type": {
            "enum": ["unavailable", "maintenance", "overtime", "holiday"]
        },
        "reason": _REASON,
        "idempotency_key": _KEY,
    },
    "additionalProperties": False,
}

production_node_calendar_override_cancel = {
    "type": "object",
    "required": ["reason", "idempotency_key"],
    "properties": {"reason": _REASON, "idempotency_key": _KEY},
    "additionalProperties": False,
}

schedule_workflow_action = {
    "type": "object",
    "required": ["reason", "idempotency_key"],
    "properties": {"reason": _REASON, "idempotency_key": _KEY},
    "additionalProperties": False,
}

schedule_revision_item_adjust = {
    "type": "object",
    "required": [
        "production_node_id",
        "planned_start_at",
        "row_version",
        "reason",
        "idempotency_key",
    ],
    "properties": {
        "production_node_id": {"type": "integer", "minimum": 1},
        "planned_start_at": _DATETIME,
        "row_version": {"type": "integer", "minimum": 1},
        "reason": _REASON,
        "idempotency_key": _KEY,
    },
    "additionalProperties": False,
}

schedule_shadow_generate = {
    "type": "object",
    "required": ["shadow_run_key"],
    "properties": {
        "shadow_run_key": _KEY,
        "start_date": {
            "type": "string",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
        },
    },
    "additionalProperties": False,
}

production_node_schemas = {
    "production_node_write": production_node_write,
    "production_node_capabilities_replace": production_node_capabilities_replace,
    "production_node_calendar_override_create": production_node_calendar_override_create,
    "production_node_calendar_override_cancel": production_node_calendar_override_cancel,
    "schedule_workflow_action": schedule_workflow_action,
    "schedule_revision_item_adjust": schedule_revision_item_adjust,
    "schedule_shadow_generate": schedule_shadow_generate,
}
