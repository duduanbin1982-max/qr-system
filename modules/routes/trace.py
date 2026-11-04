"""Product and order traceability HTTP routes."""
from flask import g, jsonify, request
from modules.route_decorators import (
    app,
    check_auth,
    check_permission,
)
from modules.services.trace_service import TraceService


@app.route('/api/trace/<code>', methods=['GET'])
@check_auth
@check_permission('trace:view')
def trace_product(code):
    """Trace a product across order, work, quality, material, inventory, and shipment records."""
    result = TraceService.trace(
        code,
        actor=g.current_user,
    )
    return jsonify(result)


@app.route("/api/trace/order/<order_no>", methods=["GET"])
@check_auth
@check_permission("trace:view")
def trace_order(order_no):
    """按订单号追溯整个订单的全部产品"""
    collection_names = (
        "items",
        "work_records",
        "rework_records",
        "quality_inspections",
        "quality_tasks",
        "quality_nonconformances",
        "quality_capa",
        "material_consumptions",
        "inventory_logs",
        "shipments",
    )
    collection_pages = {
        name: request.args.get(f"{name}_page", 1)
        for name in collection_names
        if f"{name}_page" in request.args
    }
    collection_per_pages = {
        name: request.args.get(f"{name}_per_page", 100)
        for name in collection_names
        if f"{name}_per_page" in request.args
    }
    result = TraceService.trace_by_order(
        order_no,
        page=request.args.get("page", 1),
        per_page=request.args.get("per_page", 100),
        actor=g.current_user,
        collection_pages=collection_pages,
        collection_per_pages=collection_per_pages,
    )
    return jsonify(result)
