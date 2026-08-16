"""products schema definitions."""

_category = {'enum': ['结构件', '机加工'], 'maxLength': 32, 'type': 'string'}
_optional_number = {'minimum': 0, 'type': ['number', 'null']}
_product_properties = {
    'category': _category,
    'description': {'maxLength': 1024, 'type': 'string'},
    'lower_opening': {'maxLength': 64, 'type': 'string'},
    'model': {'maxLength': 64, 'type': 'string'},
    'plate_thickness': {'maxLength': 32, 'type': 'string'},
    'price': _optional_number,
    'process_route_id': {'type': ['integer', 'null']},
    'product_code': {'maxLength': 128, 'type': 'string'},
    'product_name': {'maxLength': 128, 'minLength': 1, 'type': 'string'},
    'route_id': {'type': ['integer', 'null']},
    'spec': {'maxLength': 256, 'type': 'string'},
    'style': {'maxLength': 64, 'type': 'string'},
    'upper_opening': {'maxLength': 64, 'type': 'string'},
    'weight': _optional_number,
}


products_schemas = {
    'create_product': {'additionalProperties': False,
 'properties': _product_properties,
 'required': ['product_name'],
 'type': 'object'},
    'update_product': {'additionalProperties': False,
 'properties': _product_properties,
 'minProperties': 1,
 'type': 'object'},
    'product_code_preview': {'additionalProperties': False,
 'properties': _product_properties,
 'required': ['product_name'],
 'type': 'object'},
    'add_product_bom': {'additionalProperties': False,
 'properties': {'material_id': {'minimum': 1, 'type': 'integer'},
                'process_id': {'minimum': 1, 'type': ['integer', 'null']},
                'quantity': {'exclusiveMinimum': 0, 'type': 'number'},
                'quantity_per_unit': {'exclusiveMinimum': 0, 'type': 'number'}},
 'type': 'object'},
}
