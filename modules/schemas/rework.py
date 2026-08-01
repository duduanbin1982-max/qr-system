"""Rework request schema definitions."""


rework_result = {"type": "string", "enum": ["ok", "scrap", "rework_again"]}

rework_schemas = {
    "create_rework": {
        "type": "object",
        "additionalProperties": False,
        "required": ["order_id", "process_id", "quantity"],
        "properties": {
            "order_id": {"type": "integer", "minimum": 1},
            "process_id": {"type": "integer", "minimum": 1},
            "quantity": {"type": "integer", "minimum": 1, "maximum": 99999},
            "reason": {"type": "string", "maxLength": 512},
        },
    },
    "update_rework": {
        "type": "object",
        "additionalProperties": False,
        "required": ["reason"],
        "properties": {
            "reason": {"type": "string", "maxLength": 512},
        },
    },
    "complete_rework": {
        "type": "object",
        "additionalProperties": False,
        "required": ["result"],
        "properties": {
            "reason": {"type": "string", "maxLength": 512},
            "result": rework_result,
            "result_remark": {"type": "string", "maxLength": 512},
        },
    },
    "batch_complete_rework": {
        "type": "object",
        "additionalProperties": False,
        "required": ["ids", "result"],
        "properties": {
            "ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 100,
                "uniqueItems": True,
                "items": {"type": "integer", "minimum": 1},
            },
            "reason": {"type": "string", "maxLength": 512},
            "result": rework_result,
            "result_remark": {"type": "string", "maxLength": 512},
        },
    },
}
