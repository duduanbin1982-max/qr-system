"""Product and order traceability HTTP routes."""
from flask import jsonify
from modules.route_decorators import app, check_auth, check_permission, handle_unexpected_error
from modules.services.trace_service import TraceService
from modules.domain.errors import DomainError


@app.route('/api/trace/<code>', methods=['GET'])
@check_auth
@check_permission('trace:view')
def trace_product(code):
    """Trace a product across order, work, quality, material, inventory, and shipment records."""
    try:
        result = TraceService.trace(code)
        return jsonify(result)
    except DomainError as e:
        return jsonify(e.to_payload()), e.status_code
    except Exception as e:
        return handle_unexpected_error(e, 'database operation')
@app.route("/api/trace/order/<order_no>", methods=["GET"])
@check_auth
@check_permission("trace:view")
def trace_order(order_no):
    """按订单号追溯整个订单的全部产品"""
    try:
        result = TraceService.trace_by_order(order_no)
        return jsonify(result)
    except DomainError as e:
        return jsonify(e.to_payload()), e.status_code
    except Exception as e:
        return handle_unexpected_error(e, "database operation")
