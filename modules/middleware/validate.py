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
    'create_inventory': {
        'type': 'object',
        'required': ['product_model'],
        'properties': {
            'product_model': {'type': 'string', 'minLength': 1, 'maxLength': 128},
            'product_name': {'type': 'string', 'maxLength': 128},
            'specification': {'type': 'string', 'maxLength': 256},
            'quantity': {'type': 'number', 'minimum': 0},
            'safe_stock': {'type': 'number', 'minimum': 0},
            'location': {'type': 'string', 'maxLength': 128},
            'unit': {'type': 'string', 'maxLength': 16},
            'remark': {'type': 'string', 'maxLength': 512},
        },
        'additionalProperties': False,
    },
    'update_inventory': {
        'type': 'object',
        'properties': {
            'product_model': {'type': 'string', 'minLength': 1, 'maxLength': 128},
            'product_name': {'type': 'string', 'maxLength': 128},
            'specification': {'type': 'string', 'maxLength': 256},
            'quantity': {'type': 'number', 'minimum': 0},
            'safe_stock': {'type': 'number', 'minimum': 0},
            'location': {'type': 'string', 'maxLength': 128},
            'unit': {'type': 'string', 'maxLength': 16},
            'remark': {'type': 'string', 'maxLength': 512},
        },
        'additionalProperties': False,
    },
    'approval_action': {
        'type': 'object',
        'properties': {
            'comment': {'type': 'string', 'maxLength': 512},
        },
        'additionalProperties': False,
    },

    'stock_movement': {
        'type': 'object',
        'required': ['inventory_id', 'quantity'],
        'properties': {
            'inventory_id': {'type': 'integer', 'minimum': 1},
            'quantity': {'type': 'number', 'minimum': 0.001},
            'order_id': {'type': ['integer', 'null']},
            'order_no': {'type': 'string', 'maxLength': 64},
            'remark': {'type': 'string', 'maxLength': 512},
        },
        'additionalProperties': False,
    },

    'quality_inspection': {
        'type': 'object',
        'required': ['order_id', 'process_id'],
        'properties': {
            'order_id': {'type': 'integer', 'minimum': 1},
            'process_id': {'type': 'integer', 'minimum': 1},
            'inspection_type': {'type': 'string', 'enum': ['first_article', 'in_process', 'final']},
            'quantity_checked': {'type': 'integer', 'minimum': 0},
            'quantity_passed': {'type': 'integer', 'minimum': 0},
            'quantity_failed': {'type': 'integer', 'minimum': 0},
            'defect_category': {'type': 'string', 'maxLength': 64},
            'defect_quantity': {'type': 'integer', 'minimum': 0},
            'notes': {'type': 'string', 'maxLength': 512},
            'inspected_at': {'type': 'string', 'maxLength': 32},
        },
        'additionalProperties': False,
    },
    'quality_update': {
        'type': 'object',
        'properties': {
            'inspection_type': {'type': 'string', 'enum': ['first_article', 'in_process', 'final']},
            'quantity_checked': {'type': 'integer', 'minimum': 0},
            'quantity_passed': {'type': 'integer', 'minimum': 0},
            'quantity_failed': {'type': 'integer', 'minimum': 0},
            'defect_category': {'type': 'string', 'maxLength': 64},
            'defect_quantity': {'type': 'integer', 'minimum': 0},
            'notes': {'type': 'string', 'maxLength': 512},
            'inspected_at': {'type': 'string', 'maxLength': 32},
        },
        'additionalProperties': False,
    },

    'create_product': {
        'type': 'object',
        'required': ['product_name'],
        'properties': {
            'product_name': {'type': 'string', 'minLength': 1, 'maxLength': 128},
            'model': {'type': 'string', 'maxLength': 64},
            'spec': {'type': 'string', 'maxLength': 256},
            'style': {'type': 'string', 'maxLength': 64},
            'upper_opening': {'type': 'string', 'maxLength': 64},
            'plate_thickness': {'type': 'string', 'maxLength': 32},
            'category': {'type': 'string', 'maxLength': 32},
            'weight': {'type': 'number', 'minimum': 0},
            'price': {'type': 'number', 'minimum': 0},
            'description': {'type': 'string', 'maxLength': 1024},
            'route_id': {'type': ['integer', 'null']},
        },
        'additionalProperties': False,
    },
    'update_product': {
        'type': 'object',
        'properties': {
            'product_name': {'type': 'string', 'minLength': 1, 'maxLength': 128},
            'model': {'type': 'string', 'maxLength': 64},
            'spec': {'type': 'string', 'maxLength': 256},
            'style': {'type': 'string', 'maxLength': 64},
            'upper_opening': {'type': 'string', 'maxLength': 64},
            'plate_thickness': {'type': 'string', 'maxLength': 32},
            'category': {'type': 'string', 'maxLength': 32},
            'weight': {'type': 'number', 'minimum': 0},
            'price': {'type': 'number', 'minimum': 0},
            'description': {'type': 'string', 'maxLength': 1024},
            'route_id': {'type': ['integer', 'null']},
        },
        'additionalProperties': False,
    },

    'create_position': {
        'type': 'object',
        'required': ['name'],
        'properties': {
            'name': {'type': 'string', 'minLength': 1, 'maxLength': 64},
            'description': {'type': 'string', 'maxLength': 256},
            'process_ids': {
                'type': 'array', 'items': {'type': 'integer'}, 'maxItems': 50
            },
        },
        'additionalProperties': False,
    },
    'update_position': {
        'type': 'object',
        'properties': {
            'name': {'type': 'string', 'minLength': 1, 'maxLength': 64},
            'description': {'type': 'string', 'maxLength': 256},
            'status': {'type': 'string', 'enum': ['active', 'inactive']},
            'process_ids': {
                'type': 'array', 'items': {'type': 'integer'}, 'maxItems': 50
            },
        },
        'additionalProperties': False,
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

    'create_material': {
        'type': 'object',
        'required': ['name'],
        'properties': {
            'name': {'type': 'string', 'minLength': 1, 'maxLength': 128},
            'spec': {'type': 'string', 'maxLength': 128},
            'unit': {'type': 'string', 'maxLength': 32},
            'stock': {'type': 'number', 'minimum': 0},
            'min_stock': {'type': 'number', 'minimum': 0},
            'price': {'type': 'number', 'minimum': 0},
        },
        'additionalProperties': False,
    },
    'create_supplier': {
        'type': 'object',
        'required': ['name'],
        'properties': {
            'name': {'type': 'string', 'minLength': 1, 'maxLength': 128},
            'contact': {'type': 'string', 'maxLength': 64},
            'phone': {'type': 'string', 'maxLength': 32},
            'address': {'type': 'string', 'maxLength': 256},
        },
        'additionalProperties': False,
    },
    'create_customer': {
        'type': 'object',
        'required': ['name'],
        'properties': {
            'name': {'type': 'string', 'minLength': 1, 'maxLength': 128},
            'contact': {'type': 'string', 'maxLength': 64},
            'phone': {'type': 'string', 'maxLength': 32},
            'email': {'type': 'string', 'maxLength': 128},
            'address': {'type': 'string', 'maxLength': 256},
            'remark': {'type': 'string', 'maxLength': 512},
        },
        'additionalProperties': False,
    },
    'update_customer': {
        'type': 'object',
        'properties': {
            'name': {'type': 'string', 'minLength': 1, 'maxLength': 128},
            'contact': {'type': 'string', 'maxLength': 64},
            'phone': {'type': 'string', 'maxLength': 32},
            'email': {'type': 'string', 'maxLength': 128},
            'address': {'type': 'string', 'maxLength': 256},
            'remark': {'type': 'string', 'maxLength': 512},
        },
        'additionalProperties': False,
    },
    'process_price': {
        'type': 'object',
        'required': ['process_id', 'unit_price'],
        'properties': {
            'process_id': {'type': 'integer', 'minimum': 1},
            'unit_price': {'type': 'number', 'minimum': 0},
            'description': {'type': 'string', 'maxLength': 256},
        },
        'additionalProperties': False,
    },
    'route_price': {
        'type': 'object',
        'required': ['route_id', 'process_id', 'unit_price'],
        'properties': {
            'route_id': {'type': 'integer', 'minimum': 1},
            'process_id': {'type': 'integer', 'minimum': 1},
            'unit_price': {'type': 'number', 'minimum': 0},
        },
        'additionalProperties': False,
    },
    'process_route': {
        'type': 'object',
        'required': ['name'],
        'properties': {
            'name': {'type': 'string', 'minLength': 1, 'maxLength': 128},
            'description': {'type': 'string', 'maxLength': 512},
            'category': {'type': 'string', 'maxLength': 64},
            'processes': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'required': ['process_id'],
                    'properties': {
                        'process_id': {'type': 'integer', 'minimum': 1},
                        'required_audit': {'type': 'integer', 'minimum': 0, 'maximum': 1},
                    },
                    'additionalProperties': False,
                },
                'maxItems': 50,
            },
        },
        'additionalProperties': False,
    },
    'batch_orders': {
        'type': 'object',
        'required': ['orders'],
        'properties': {
            'orders': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'required': ['order_no'],
                    'properties': {
                        'order_no': {'type': 'string', 'minLength': 1, 'maxLength': 64},
                        'customer': {'type': 'string', 'maxLength': 128},
                        'product_name': {'type': 'string', 'maxLength': 128},
                        'quantity': {'type': 'integer', 'minimum': 1, 'maximum': 99999},
                        'plan_start': {'type': 'string', 'maxLength': 32},
                        'plan_end': {'type': 'string', 'maxLength': 32},
                        'deadline': {'type': 'string', 'maxLength': 32},
                        'remark': {'type': 'string', 'maxLength': 1024},
                    },
                    'additionalProperties': True,
                },
                'maxItems': 200,
            },
        },
        'additionalProperties': False,
    },

    'create_process': {
        'type': 'object',
        'required': ['name'],
        'properties': {
            'name': {'type': 'string', 'minLength': 1, 'maxLength': 64},
            'description': {'type': 'string', 'maxLength': 512},
            'category': {'type': 'string', 'maxLength': 64},
            'seq_order': {'type': 'integer', 'minimum': 0},
            'status': {'type': 'string', 'enum': ['active', 'inactive']},
        },
        'additionalProperties': False,
    },
    'update_process': {
        'type': 'object',
        'properties': {
            'name': {'type': 'string', 'minLength': 1, 'maxLength': 64},
            'description': {'type': 'string', 'maxLength': 512},
            'category': {'type': 'string', 'maxLength': 64},
            'seq_order': {'type': 'integer', 'minimum': 0},
            'status': {'type': 'string', 'enum': ['active', 'inactive']},
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

