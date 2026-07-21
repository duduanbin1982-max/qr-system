"""Product and order traceability HTTP routes."""
from flask import jsonify
from modules.route_decorators import app, check_auth, check_permission
from modules.services.trace_service import TraceService
@app.route('/api/trace/<code>', methods=['GET'])
@check_auth
@check_permission('trace:view')
def trace_product(code):
    """Trace a product across order, work, quality, material, inventory, and shipment records."""
    result = TraceService.trace(code)
    return jsonify(result)
@app.route("/api/trace/order/<order_no>", methods=["GET"])
@check_auth
@check_permission("trace:view")
def trace_order(order_no):
    """按订单号追溯整个订单的全部产品"""
    result = TraceService.trace_by_order(order_no)
    return jsonify(result)
