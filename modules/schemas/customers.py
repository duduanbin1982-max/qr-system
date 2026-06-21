"""customers schema definitions."""

customers_schemas = {
    'create_customer': {'additionalProperties': False,
 'properties': {'address': {'maxLength': 256, 'type': 'string'},
                'contact': {'maxLength': 64, 'type': 'string'},
                'email': {'maxLength': 128, 'type': 'string'},
                'name': {'maxLength': 128, 'minLength': 1, 'type': 'string'},
                'phone': {'maxLength': 32, 'type': 'string'},
                'remark': {'maxLength': 512, 'type': 'string'},
                'tags': {'maxLength': 256, 'type': 'string'}},
 'required': ['name'],
 'type': 'object'},
    'update_customer': {'additionalProperties': False,
 'properties': {'address': {'maxLength': 256, 'type': 'string'},
                'contact': {'maxLength': 64, 'type': 'string'},
                'email': {'maxLength': 128, 'type': 'string'},
                'name': {'maxLength': 128, 'minLength': 1, 'type': 'string'},
                'phone': {'maxLength': 32, 'type': 'string'},
                'remark': {'maxLength': 512, 'type': 'string'},
                'tags': {'maxLength': 256, 'type': 'string'}},
 'type': 'object'},
}
