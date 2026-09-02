"""
qr-system — 请求体验证中间件

基于 jsonschema 的请求体校验装饰器。
"""
import logging
from functools import wraps

import jsonschema
from flask import jsonify, request


# ============================================================
# JSON Schema 定义
# ============================================================
from modules.schemas import SCHEMAS


def _payload_shape(value):
    """Return request structure metadata without including request values."""
    if isinstance(value, dict):
        return f"object(fields={len(value)})"
    if isinstance(value, list):
        return f"array(items={len(value)})"
    return type(value).__name__


def _safe_validation_message(error):
    """Build a useful validation message without echoing the invalid value."""
    validator = error.validator

    if validator == 'required':
        required = error.validator_value if isinstance(error.validator_value, (list, tuple)) else []
        instance = error.instance if isinstance(error.instance, dict) else {}
        missing = [str(field) for field in required if field not in instance]
        if missing:
            return f"缺少必填字段: {', '.join(missing)}"
        return '缺少必填字段'
    if validator == 'additionalProperties':
        return '包含不允许的字段'
    if validator == 'type':
        expected = error.validator_value
        if isinstance(expected, (list, tuple)):
            expected = '/'.join(str(item) for item in expected)
        return f'类型不正确，应为 {expected}'
    if validator == 'enum':
        return '值不在允许范围内'
    if validator == 'const':
        return '值不符合固定约束'
    if validator == 'minLength':
        return f'长度不能少于 {error.validator_value} 个字符'
    if validator == 'maxLength':
        return f'长度不能超过 {error.validator_value} 个字符'
    if validator == 'minimum':
        return f'数值不能小于 {error.validator_value}'
    if validator == 'maximum':
        return f'数值不能大于 {error.validator_value}'
    if validator == 'exclusiveMinimum':
        return f'数值必须大于 {error.validator_value}'
    if validator == 'exclusiveMaximum':
        return f'数值必须小于 {error.validator_value}'
    if validator == 'minItems':
        return f'项目数量不能少于 {error.validator_value}'
    if validator == 'maxItems':
        return f'项目数量不能超过 {error.validator_value}'
    if validator == 'uniqueItems':
        return '不允许包含重复项'
    if validator == 'format':
        return f'格式不正确，应为 {error.validator_value}'
    if validator == 'pattern':
        return '格式不正确'
    if validator in {'allOf', 'anyOf', 'oneOf', 'not'}:
        return '数据组合不符合约束'
    return '数据不符合约束'


def _log_validation_failure(schema_name, error, data):
    """Log validation diagnostics while excluding all request values."""
    logging.getLogger('qr').error(
        'SCHEMA_VALIDATE_FAILED: %s | path: %s | validator: %s | '
        'instance_type: %s | payload_shape: %s',
        schema_name,
        list(error.absolute_path),
        error.validator or 'unknown',
        type(error.instance).__name__,
        _payload_shape(data),
    )


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
                _log_validation_failure(schema_name, e, data)
                # Friendly error message
                path = ' → '.join(str(p) for p in e.absolute_path) if e.absolute_path else '根对象'
                message = _safe_validation_message(e)
                return jsonify({'error': f'参数校验失败: {path} — {message}'}), 400
            return f(*args, **kwargs)
        return decorated
    return decorator
