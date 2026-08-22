"""approvals schema definitions."""

approval_action = {
    'type': 'object',
    'additionalProperties': False,
    'properties': {
        'comment': {'maxLength': 512, 'type': 'string'},
    },
}

approval_config_item = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['process_id', 'require_approval', 'approval_level'],
    'properties': {
        'process_id': {'type': 'integer', 'minimum': 1},
        'require_approval': {'type': 'integer', 'enum': [0, 1]},
        'approval_level': {'type': 'integer', 'minimum': 1, 'maximum': 3},
        'approver_role': {'maxLength': 64, 'type': 'string'},
        'approver_role_2': {'maxLength': 64, 'type': 'string'},
        'approver_role_3': {'maxLength': 64, 'type': 'string'},
        'approver_role_id': {'type': 'integer', 'minimum': 1},
        'approver_role_2_id': {'type': 'integer', 'minimum': 1},
        'approver_role_3_id': {'type': 'integer', 'minimum': 1},
    },
}

approval_config_payload = {
    'anyOf': [
        approval_config_item,
        {
            'type': 'object',
            'additionalProperties': False,
            'required': ['configs'],
            'properties': {
                'configs': {
                    'type': 'array',
                    'minItems': 1,
                    'items': approval_config_item,
                },
            },
        },
    ],
}

approval_batch_payload = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['ids', 'action'],
    'properties': {
        'ids': {
            'type': 'array',
            'minItems': 1,
            'items': {'type': 'integer', 'minimum': 1},
            'uniqueItems': True,
        },
        'action': {'enum': ['approve', 'reject'], 'type': 'string'},
        'comment': {'maxLength': 512, 'type': 'string'},
    },
}

approval_policy_revision_payload = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['idempotency_key', 'approval_level', 'require_approval', 'steps'],
    'properties': {
        'process_id': {'type': ['integer', 'null'], 'minimum': 1},
        'idempotency_key': {'type': 'string', 'minLength': 8, 'maxLength': 128},
        'require_approval': {'type': 'integer', 'enum': [0, 1]},
        'approval_level': {'type': 'integer', 'minimum': 1, 'maximum': 3},
        'steps': {
            'type': 'array', 'maxItems': 3,
            'items': {
                'type': 'object', 'additionalProperties': False,
                'required': ['code'],
                'properties': {
                    'level': {'type': 'integer', 'minimum': 1, 'maximum': 3},
                    'role_id': {'type': 'integer', 'minimum': 1},
                    'code': {'type': 'string', 'minLength': 2, 'maxLength': 64},
                    'name': {'type': 'string', 'maxLength': 128},
                },
            },
        },
    },
}

approvals_schemas = {
    'approval_action': approval_action,
    'approval_batch_payload': approval_batch_payload,
    'approval_config_item': approval_config_item,
    'approval_config_payload': approval_config_payload,
    'approval_policy_revision_payload': approval_policy_revision_payload,
}
