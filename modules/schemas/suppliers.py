"""suppliers schema definitions."""

suppliers_schemas = {
    'create_supplier': {'additionalProperties': False,
 'properties': {'address': {'maxLength': 256, 'type': 'string'},
                'contact': {'maxLength': 64, 'type': 'string'},
                'name': {'maxLength': 128, 'minLength': 1, 'type': 'string'},
                'phone': {'maxLength': 32, 'type': 'string'}},
 'required': ['name'],
 'type': 'object'},
}
