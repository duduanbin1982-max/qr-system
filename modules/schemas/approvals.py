"""approvals schema definitions."""

approvals_schemas = {
    'approval_action': {'additionalProperties': False, 'properties': {'comment': {'maxLength': 512, 'type': 'string'}}, 'type': 'object'},
}
