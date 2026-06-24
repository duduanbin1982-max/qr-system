"""auth schema definitions."""

auth_schemas = {
    'login': {'additionalProperties': False,
 'properties': {'password': {'maxLength': 128, 'minLength': 6, 'type': 'string'},
                'username': {'maxLength': 64, 'minLength': 2, 'type': 'string'}},
 'required': ['username', 'password'],
 'type': 'object'},
    'change_password': {'additionalProperties': False,
 'properties': {'new_password': {'maxLength': 128, 'minLength': 8, 'type': 'string'}},
 'required': ['new_password'],
 'type': 'object'},
}
