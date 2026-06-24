"""positions schema definitions."""

positions_schemas = {
    'create_position': {'additionalProperties': False,
 'properties': {'description': {'maxLength': 256, 'type': 'string'},
                'name': {'maxLength': 64, 'minLength': 1, 'pattern': '^[一-龥a-zA-Z0-9\\s\\-/().+#]+$', 'type': 'string'},
                'process_ids': {'items': {'type': 'integer'}, 'maxItems': 50, 'type': 'array'},
                'status': {'enum': ['active', 'inactive'], 'type': 'string'}},
 'required': ['name'],
 'type': 'object'},
    'update_position': {'additionalProperties': False,
 'properties': {'description': {'maxLength': 256, 'type': 'string'},
                'name': {'maxLength': 64, 'minLength': 1, 'type': 'string'},
                'process_ids': {'items': {'type': 'integer'}, 'maxItems': 50, 'type': 'array'},
                'status': {'enum': ['active', 'inactive'], 'type': 'string'}},
 'type': 'object'},
}
