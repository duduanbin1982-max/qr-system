"""HTTP adapters for production-node administration."""

from flask import g, jsonify, request

from modules.route_decorators import (
    app,
    check_auth,
    check_permission,
    get_json_body,
    validate_json,
)
from modules.services.production_node_service import ProductionNodeService


def _actor_id():
    actor = getattr(g, "current_user", {}) or {}
    return actor.get("id")


@app.route("/api/production-nodes", methods=["GET"])
@check_auth
@check_permission("production_nodes:view")
def list_production_nodes():
    return jsonify(
        ProductionNodeService.list_nodes(
            process_id=request.args.get("process_id"),
            status=request.args.get("status"),
            limit=request.args.get("limit", 500),
        )
    )


@app.route("/api/production-nodes", methods=["POST"])
@check_auth
@check_permission("production_nodes:manage")
@validate_json("production_node_write")
def create_production_node():
    data = get_json_body()
    return (
        jsonify(
            ProductionNodeService.create_node(data, _actor_id())
        ),
        201,
    )


@app.route("/api/production-nodes/<int:node_id>", methods=["PUT"])
@check_auth
@check_permission("production_nodes:manage")
@validate_json("production_node_write")
def update_production_node(node_id):
    return jsonify(
        ProductionNodeService.update_node(node_id, get_json_body(), _actor_id())
    )


@app.route(
    "/api/production-nodes/<int:node_id>/capabilities", methods=["PUT"]
)
@check_auth
@check_permission("production_nodes:capability_manage")
@validate_json("production_node_capabilities_replace")
def replace_production_node_capabilities(node_id):
    return jsonify(
        ProductionNodeService.replace_capabilities(
            node_id, get_json_body(), _actor_id()
        )
    )


@app.route(
    "/api/production-nodes/<int:node_id>/calendar-overrides", methods=["GET"]
)
@check_auth
@check_permission("production_nodes:view")
def list_production_node_calendar_overrides(node_id):
    return jsonify(
        ProductionNodeService.list_calendar_overrides(
            node_id,
            start_at=request.args.get("start_at", ""),
            end_at=request.args.get("end_at", ""),
            limit=request.args.get("limit", 500),
        )
    )


@app.route(
    "/api/production-nodes/<int:node_id>/calendar-overrides", methods=["POST"]
)
@check_auth
@check_permission("production_nodes:calendar_manage")
@validate_json("production_node_calendar_override_create")
def create_production_node_calendar_override(node_id):
    return (
        jsonify(
            ProductionNodeService.create_calendar_override(
                node_id, get_json_body(), _actor_id()
            )
        ),
        201,
    )


@app.route(
    "/api/production-node-calendar-overrides/<int:override_id>/cancel",
    methods=["POST"],
)
@check_auth
@check_permission("production_nodes:calendar_manage")
@validate_json("production_node_calendar_override_cancel")
def cancel_production_node_calendar_override(override_id):
    return jsonify(
        ProductionNodeService.cancel_calendar_override(
            override_id, get_json_body(), _actor_id()
        )
    )


@app.route(
    "/api/production-nodes/<int:node_id>/audit-events", methods=["GET"]
)
@check_auth
@check_permission("production_nodes:view")
def list_production_node_audit_events(node_id):
    return jsonify(
        ProductionNodeService.list_audit_events(
            node_id, limit=request.args.get("limit", 500)
        )
    )
