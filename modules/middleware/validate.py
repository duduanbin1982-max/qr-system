"""
qr-system — 请求体验证中间件

基于 jsonschema 的请求体校验装饰器。
"""
from functools import wraps
from flask import request, jsonify
import json
import jsonschema


# ============================================================
# JSON Schema 定义
# ============================================================
from modules.schemas import SCHEMAS

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
                import logging
                logging.getLogger('qr').error(f'SCHEMA_VALIDATE_FAILED: {schema_name} | path: {list(e.absolute_path)} | msg: {e.message} | instance_keys: {list(data.keys()) if isinstance(data, dict) else  not dict} | body(raw): {json.dumps(data, ensure_ascii=False, default=str)[:300]}')
                # Friendly error message
                path = ' → '.join(str(p) for p in e.absolute_path) if e.absolute_path else '根对象'
                return jsonify({'error': f'参数校验失败: {path} — {e.message}'}), 400
            return f(*args, **kwargs)
        return decorated
    return decorator

