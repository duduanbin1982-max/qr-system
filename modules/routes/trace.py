"""
qr-system ? ???????Refactored: SQL ? TraceService?
"""
from flask import jsonify
from modules.app import app
from modules.middleware.auth import check_auth, check_permission
from modules.middleware.error_handler import handle_unexpected_error
from modules.services.trace_service import TraceService


@app.route('/api/trace/<code>', methods=['GET'])
@check_auth
@check_permission('trace:view')
def trace_product(code):
    """??????????????? ? ?? ? ?? ? ?? ? ???"""
    try:
        result = TraceService.trace(code)
        return jsonify(result)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')
