"""
qr-system — 请求体验证中间件

基于 jsonschema 的请求体校验装饰器。
"""
from functools import wraps
from flask import request, jsonify
import jsonschema


# ============================================================
# JSON Schema 定义
# ============================================================
SCHEMAS = {
    'login': {
        'type': 'object',
        'required': ['username', 'password'],
        'properties': {
            'username': {'type': 'string', 'minLength': 1, 'maxLength': 64},
            'password': {'type': 'string', 'minLength': 8, 'maxLength': 128},
        },
        'additionalProperties': False,
    },
    'change_password': {
        'type': 'object',
        'required': ['new_password'],
        'properties': {
            'new_password': {'type': 'string', 'minLength': 8, 'maxLength': 128},
        },
        'additionalProperties': False,
    },
    'create_user': {
        'type': 'object',
        'required': ['username', 'name'],
        'properties': {
            'username': {'type': 'string', 'minLength': 1, 'maxLength': 64},
            'name': {'type': 'string', 'minLength': 1, 'maxLength': 64},
            'nickname': {'type': 'string', 'maxLength': 64},
            'email': {'type': 'string', 'format': 'email', 'maxLength': 128},
            'role': {'type': 'string', 'enum': ['admin', 'worker']},
            'password': {'type': 'string', 'minLength': 8, 'maxLength': 128},
            'employee_no': {'type': 'string', 'maxLength': 32},
            'phone': {'type': 'string', 'maxLength': 32},
            'position_id': {'type': ['integer', 'null']},
            'process_ids': {'type': 'string', 'maxLength': 256},
            'status': {'type': 'string', 'enum': ['active', 'inactive']},
            'group_name': {'type': 'string', 'maxLength': 64},
        },
        'additionalProperties': False,
    },
    'create_order': {
        'type': 'object',
        'properties': {
            'order_no': {'type': 'string', 'minLength': 1, 'maxLength': 64},
            'customer': {'type': 'string', 'maxLength': 128},
            'customer_id': {'type': ['integer', 'null']},
            'product_name': {'type': 'string', 'maxLength': 128},
            'product_code': {'type': 'string', 'maxLength': 64},
            'quantity': {'type': 'integer', 'minimum': 1, 'maximum': 99999},
            'plan_start': {'type': 'string', 'maxLength': 32},
            'plan_end': {'type': 'string', 'maxLength': 32},
            'deadline': {'type': 'string', 'maxLength': 32},
            'remark': {'type': 'string', 'maxLength': 1024},
            'route_id': {'type': ['integer', 'null']},
            'process_ids': {
                'type': 'array',
                'items': {'type': 'integer'},
                'maxItems': 50,
            },
        },
        'additionalProperties': True,  # extra_fields support
    },
    'update_order': {
        'type': 'object',
        'properties': {
            'customer': {'type': 'string', 'maxLength': 128},
            'customer_id': {'type': ['integer', 'null']},
            'product_name': {'type': 'string', 'maxLength': 128},
            'product_code': {'type': 'string', 'maxLength': 64},
            'quantity': {'type': 'integer', 'minimum': 1, 'maximum': 99999},
            'status': {'type': 'string', 'enum': ['pending', 'producing', 'completed', 'cancelled']},
            'plan_start': {'type': 'string', 'maxLength': 32},
            'plan_end': {'type': 'string', 'maxLength': 32},
            'deadline': {'type': 'string', 'maxLength': 32},
            'remark': {'type': 'string', 'maxLength': 1024},
            'route_id': {'type': ['integer', 'null']},
        },
        'additionalProperties': True,
    },
    'work_report': {
        'type': 'object',
        'required': ['order_id', 'process_id'],
        'properties': {
            'order_id': {'type': 'integer', 'minimum': 1},
            'process_id': {'type': 'integer', 'minimum': 1},
            'quantity': {'type': 'integer', 'minimum': 1, 'maximum': 99999},
            'type': {'type': 'string', 'enum': ['normal', 'rework', 'scrap']},
            'remark': {'type': 'string', 'maxLength': 512},
            'serial_no': {'type': 'string', 'maxLength': 64},
        },
        'additionalProperties': False,
    },

    'mobile_scan': {
        'type': 'object',
        'required': ['code'],
        'properties': {
            'code': {'type': 'string', 'minLength': 1, 'maxLength': 256},
            'latitude': {'type': 'string', 'maxLength': 32},
            'longitude': {'type': 'string', 'maxLength': 32},
        },
        'additionalProperties': False,
    },
    'mobile_report': {
        'type': 'object',
        'required': ['order_id', 'process_id'],
        'properties': {
            'order_id': {'type': 'integer', 'minimum': 1},
            'process_id': {'type': 'integer', 'minimum': 1},
            'quantity': {'type': 'integer', 'minimum': 1, 'maximum': 99999},
            'type': {'type': 'string', 'enum': ['normal', 'rework', 'scrap']},
            'remark': {'type': 'string', 'maxLength': 512},
            'serial_no': {'type': 'string', 'maxLength': 64},
            'latitude': {'type': 'string', 'maxLength': 32},
            'longitude': {'type': 'string', 'maxLength': 32},
        },
        'additionalProperties': False,
    },
    'scan_order': {
        'type': 'object',
        'required': ['order_id'],
        'properties': {
            'order_id': {'type': 'integer', 'minimum': 1},
            'process_id': {'type': 'integer', 'minimum': 1},
            'quantity': {'type': 'integer', 'minimum': 1, 'maximum': 99999},
            'type': {'type': 'string', 'enum': ['normal', 'rework', 'scrap', 'stock_in']},
            'remark': {'type': 'string', 'maxLength': 512},
            'serial_no': {'type': 'string', 'maxLength': 64},
        },
        'additionalProperties': False,
    },
    'update_user': {
        'type': 'object',
        'properties': {
            'name': {'type': 'string', 'minLength': 1, 'maxLength': 64},
            'nickname': {'type': 'string', 'maxLength': 64},
            'email': {'type': 'string', 'format': 'email', 'maxLength': 128},
            'phone': {'type': 'string', 'maxLength': 32},
            'employee_no': {'type': 'string', 'maxLength': 32},
            'position_id': {'type': ['integer', 'null']},
            'process_ids': {'type': 'string', 'maxLength': 256},
            'status': {'type': 'string', 'enum': ['active', 'inactive']},
            'group_name': {'type': 'string', 'maxLength': 64},
            'role': {'type': 'string', 'enum': ['admin', 'worker']},
        },
        'additionalProperties': False,
    },
}


def validate_json(schema_name: str):
    """
    请求体 JSON Schema 校验装饰器。

    用法:
        @app.route('/api/orders', methods=['POST'])
        @check_auth
        @check_permission('orders:create')
        @validate_json('create_order')
        def create_order():
            ...
    """
    schema = SCHEMAS.get(schema_name)
    if not schema:
        raise ValueError(f'Unknown schema: {schema_name}')

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            data = request.get_json(force=True, silent=True)
            if data is None:
                return jsonify({'error': '无效的请求数据，需要 JSON 格式'}), 400
            try:
                jsonschema.validate(instance=data, schema=schema)
            except jsonschema.ValidationError as e:
                # Friendly error message
                path = ' → '.join(str(p) for p in e.absolute_path) if e.absolute_path else '根对象'
                return jsonify({'error': f'参数校验失败: {path} — {e.message}'}), 400
            return f(*args, **kwargs)
        return decorated
    return decorator

