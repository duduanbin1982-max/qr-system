"""HTTP adapters for immutable position revisions and lifecycle requests."""

from flask import g, jsonify, request

from modules.route_decorators import (
    app,
    check_auth,
    check_permission,
    get_json_body,
    require_position_versioned_write,
    validate_json,
)
from modules.services.position_lifecycle_service import PositionLifecycleService
from modules.services.position_version_service import PositionVersionService


def _actor():
    return getattr(g, "current_user", {}) or {}


def _request_id():
    return request.headers.get("X-Request-ID", "")


@app.route("/api/positions/<int:position_id>/versions", methods=["GET"])
@check_auth
@check_permission("positions:history")
def list_position_versions(position_id):
    return jsonify(PositionVersionService.list_versions(position_id))


@app.route("/api/position-versions/<int:version_id>", methods=["GET"])
@check_auth
@check_permission("positions:history")
def get_position_version(version_id):
    return jsonify(PositionVersionService.get_version(version_id))


@app.route("/api/position-versions/<int:version_id>/impact", methods=["GET"])
@check_auth
@check_permission("positions:impact")
def position_version_impact(version_id):
    return jsonify(PositionVersionService.impact(version_id))


@app.route("/api/positions/<int:position_id>/revisions", methods=["POST"])
@check_auth
@check_permission("positions:create")
@require_position_versioned_write
@validate_json("position_revision_create")
def create_position_revision(position_id):
    return (
        jsonify(
            PositionVersionService.create_revision(
                position_id, get_json_body(), _actor(), _request_id()
            )
        ),
        201,
    )


@app.route("/api/position-versions/<int:version_id>", methods=["PUT"])
@check_auth
@check_permission("positions:create")
@require_position_versioned_write
@validate_json("position_version_update")
def update_position_version(version_id):
    return jsonify(
        PositionVersionService.update_draft(
            version_id, get_json_body(), _actor(), _request_id()
        )
    )


@app.route("/api/position-versions/<int:version_id>/submit", methods=["POST"])
@check_auth
@check_permission("positions:submit")
@require_position_versioned_write
@validate_json("position_version_transition")
def submit_position_version(version_id):
    return jsonify(
        PositionVersionService.submit(
            version_id, get_json_body(), _actor(), _request_id()
        )
    )


@app.route("/api/position-versions/<int:version_id>/approve", methods=["POST"])
@check_auth
@check_permission("positions:approve")
@require_position_versioned_write
@validate_json("position_version_transition")
def approve_position_version(version_id):
    return jsonify(
        PositionVersionService.approve(
            version_id, get_json_body(), _actor(), _request_id()
        )
    )


@app.route("/api/position-versions/<int:version_id>/reject", methods=["POST"])
@check_auth
@check_permission("positions:reject")
@require_position_versioned_write
@validate_json("position_version_terminal")
def reject_position_version(version_id):
    return jsonify(
        PositionVersionService.reject(
            version_id, get_json_body(), _actor(), _request_id()
        )
    )


@app.route("/api/position-versions/<int:version_id>/cancel", methods=["POST"])
@check_auth
@check_permission("positions:submit")
@require_position_versioned_write
@validate_json("position_version_terminal")
def cancel_position_version(version_id):
    return jsonify(
        PositionVersionService.cancel(
            version_id, get_json_body(), _actor(), _request_id()
        )
    )


@app.route(
    "/api/positions/<int:position_id>/lifecycle-requests", methods=["GET"]
)
@check_auth
@check_permission("positions:history")
def list_position_lifecycle_requests(position_id):
    return jsonify(PositionLifecycleService.list_requests(position_id))


@app.route(
    "/api/positions/<int:position_id>/retirement-requests", methods=["POST"]
)
@check_auth
@check_permission("positions:retire")
@require_position_versioned_write
@validate_json("position_lifecycle_request")
def request_position_retirement(position_id):
    result = PositionLifecycleService.request_retirement(
        position_id, get_json_body(), _actor(), _request_id()
    )
    return jsonify(result), 201


@app.route(
    "/api/positions/<int:position_id>/reactivation-requests", methods=["POST"]
)
@check_auth
@check_permission("positions:reactivate")
@require_position_versioned_write
@validate_json("position_lifecycle_request")
def request_position_reactivation(position_id):
    result = PositionLifecycleService.request_reactivation(
        position_id, get_json_body(), _actor(), _request_id()
    )
    return jsonify(result), 201


@app.route(
    "/api/position-lifecycle-requests/<int:lifecycle_request_id>/approve",
    methods=["POST"],
)
@check_auth
@check_permission("positions:approve")
@require_position_versioned_write
@validate_json("position_lifecycle_approve")
def approve_position_lifecycle(lifecycle_request_id):
    return jsonify(
        PositionLifecycleService.approve_request(
            lifecycle_request_id, get_json_body(), _actor(), _request_id()
        )
    )


@app.route(
    "/api/position-lifecycle-requests/<int:lifecycle_request_id>/reject",
    methods=["POST"],
)
@check_auth
@check_permission("positions:reject")
@require_position_versioned_write
@validate_json("position_lifecycle_reject")
def reject_position_lifecycle(lifecycle_request_id):
    return jsonify(
        PositionLifecycleService.reject_request(
            lifecycle_request_id, get_json_body(), _actor(), _request_id()
        )
    )
