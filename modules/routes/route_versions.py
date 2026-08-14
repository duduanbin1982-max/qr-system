"""HTTP adapters for immutable route revisions and lifecycle requests."""

from flask import g, jsonify

from modules.route_decorators import (
    app,
    check_auth,
    check_permission,
    get_json_body,
    safe_audit_log,
    validate_json,
)
from modules.services.master_data_lifecycle_service import MasterDataLifecycleService
from modules.services.route_version_service import RouteVersionService


def _actor():
    return getattr(g, "current_user", {}) or {}


def _lifecycle_command():
    command = dict(get_json_body())
    if not command.get("reason"):
        command["reason"] = command.pop("lifecycle_reason", "")
    else:
        command.pop("lifecycle_reason", None)
    return command


def _audit(action, resource_id, detail=""):
    safe_audit_log(action, "route_version", int(resource_id), detail)


@app.route("/api/process-routes/<int:route_id>/versions", methods=["GET"])
@check_auth
@check_permission("route_versions:view")
def list_route_versions(route_id):
    return jsonify(RouteVersionService.list_versions(route_id))


@app.route("/api/process-route-versions/<int:version_id>", methods=["GET"])
@check_auth
@check_permission("route_versions:view")
def get_route_version(version_id):
    return jsonify(RouteVersionService.get_version(version_id))


@app.route("/api/process-routes/<int:route_id>/revisions", methods=["POST"])
@check_auth
@check_permission("route_versions:create")
@validate_json("route_revision_create")
def create_route_revision(route_id):
    command = get_json_body()
    result = RouteVersionService.create_revision(route_id, command, _actor())
    _audit("route_revision_create", result["id"], command["revision_reason"])
    return jsonify(result), 201


@app.route("/api/process-route-versions/<int:version_id>", methods=["PUT"])
@check_auth
@check_permission("route_versions:create")
@validate_json("route_version_update")
def update_route_version(version_id):
    result = RouteVersionService.update_draft(version_id, get_json_body(), _actor())
    _audit("route_revision_update", version_id)
    return jsonify(result)


@app.route("/api/process-route-versions/<int:version_id>/submit", methods=["POST"])
@check_auth
@check_permission("route_versions:submit")
@validate_json("version_transition")
def submit_route_version(version_id):
    result = RouteVersionService.submit(version_id, get_json_body(), _actor())
    _audit("route_revision_submit", version_id)
    return jsonify(result)


@app.route("/api/process-route-versions/<int:version_id>/approve", methods=["POST"])
@check_auth
@check_permission("route_versions:approve")
@validate_json("route_version_approve")
def approve_route_version(version_id):
    result = RouteVersionService.approve(version_id, get_json_body(), _actor())
    _audit("route_revision_approve", version_id)
    return jsonify(result)


@app.route("/api/process-route-versions/<int:version_id>/reject", methods=["POST"])
@check_auth
@check_permission("route_versions:reject")
@validate_json("version_reject")
def reject_route_version(version_id):
    command = get_json_body()
    result = RouteVersionService.reject(version_id, command, _actor())
    _audit("route_revision_reject", version_id, command["reason"])
    return jsonify(result)


@app.route("/api/process-route-versions/<int:version_id>/impact", methods=["GET"])
@check_auth
@check_permission("route_versions:impact")
def route_version_impact(version_id):
    return jsonify(RouteVersionService.impact(version_id))


def _request_route_lifecycle(route_id, action):
    command = _lifecycle_command()
    result = MasterDataLifecycleService.request_route(route_id, action, command, _actor())
    _audit(f"route_{action}_request", result["id"], command["reason"])
    return jsonify(result), 201


@app.route("/api/process-routes/<int:route_id>/retirement-requests", methods=["POST"])
@check_auth
@check_permission("process_routes:retire")
@validate_json("lifecycle_request")
def request_route_retirement(route_id):
    return _request_route_lifecycle(route_id, "retire")


@app.route("/api/process-routes/<int:route_id>/reactivation-requests", methods=["POST"])
@check_auth
@check_permission("process_routes:reactivate")
@validate_json("lifecycle_request")
def request_route_reactivation(route_id):
    return _request_route_lifecycle(route_id, "reactivate")


def _approve_route_lifecycle(request_id, action):
    result = MasterDataLifecycleService.approve_route(
        request_id, get_json_body(), _actor()
    )
    _audit(f"route_{action}_approve", request_id)
    return jsonify(result)


@app.route(
    "/api/process-route-retirement-requests/<int:request_id>/approve",
    methods=["POST"],
)
@check_auth
@check_permission("process_routes:retire")
@validate_json("lifecycle_approve")
def approve_route_retirement(request_id):
    return _approve_route_lifecycle(request_id, "retire")


@app.route(
    "/api/process-route-reactivation-requests/<int:request_id>/approve",
    methods=["POST"],
)
@check_auth
@check_permission("process_routes:reactivate")
@validate_json("lifecycle_approve")
def approve_route_reactivation(request_id):
    return _approve_route_lifecycle(request_id, "reactivate")
