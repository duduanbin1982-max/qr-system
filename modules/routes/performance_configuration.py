"""Versioned performance rule and position target configuration API."""

from flask import g, jsonify, request

from modules.domain.errors import DomainError
from modules.domain.performance_policy import PerformanceConflictError
from modules.route_decorators import app, check_auth
from modules.services.performance_authorization_service import (
    PerformanceAuthorizationService,
)
from modules.services.performance_configuration_service import (
    PerformanceConfigurationService,
)


def _actor():
    return getattr(g, "current_user", {}) or {}


def _deny():
    return jsonify({"error": "无权限", "code": "forbidden"}), 403


def _can(action):
    return PerformanceAuthorizationService.can_perform(_actor(), action)


def _error(exc):
    if isinstance(exc, PerformanceConflictError):
        return jsonify({"error": str(exc), "code": "performance_conflict"}), 409
    if isinstance(exc, DomainError):
        return jsonify(exc.to_payload()), exc.status_code
    return jsonify({"error": str(exc), "code": "validation_error"}), 400


@app.route("/api/performance/rule-versions", methods=["GET"])
@check_auth
def list_performance_rule_versions():
    if not any(_can(action) for action in ("view_all", "prepare", "approve")):
        return _deny()
    return jsonify(
        PerformanceConfigurationService.list_rule_versions(
            request.args.get("status", "")
        )
    )


@app.route("/api/performance/rule-versions", methods=["POST"])
@check_auth
def create_performance_rule_version():
    if not _can("prepare"):
        return _deny()
    try:
        result = PerformanceConfigurationService.create_rule_version(
            request.get_json(silent=True) or {}, _actor()
        )
        return jsonify(result), 201
    except (ValueError, PermissionError) as exc:
        return _error(exc)


@app.route("/api/performance/rule-versions/<int:rule_id>", methods=["PUT"])
@check_auth
def update_performance_rule_version(rule_id):
    if not _can("prepare"):
        return _deny()
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(
            PerformanceConfigurationService.update_rule_version(
                rule_id, data, _actor(), data.get("row_version")
            )
        )
    except (ValueError, PermissionError) as exc:
        return _error(exc)


@app.route("/api/performance/rule-versions/<int:rule_id>/publish", methods=["POST"])
@check_auth
def publish_performance_rule_version(rule_id):
    if not _can("approve"):
        return _deny()
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(
            PerformanceConfigurationService.publish_rule_version(
                rule_id, _actor(), data.get("row_version")
            )
        )
    except (ValueError, PermissionError) as exc:
        return _error(exc)


@app.route("/api/performance/rule-versions/<int:rule_id>", methods=["DELETE"])
@check_auth
def delete_performance_rule_version(rule_id):
    if not _can("prepare"):
        return _deny()
    try:
        PerformanceConfigurationService.delete_rule_version(rule_id, _actor())
        return jsonify({"deleted": True})
    except (ValueError, PermissionError) as exc:
        return _error(exc)


@app.route("/api/performance/position-target-versions", methods=["GET"])
@check_auth
def list_performance_position_targets():
    if not any(_can(action) for action in ("view_all", "prepare", "approve")):
        return _deny()
    return jsonify(
        PerformanceConfigurationService.list_position_target_versions(
            request.args.get("position_id", type=int), request.args.get("status", "")
        )
    )


@app.route("/api/performance/position-target-versions", methods=["POST"])
@check_auth
def create_performance_position_target():
    if not _can("prepare"):
        return _deny()
    try:
        result = PerformanceConfigurationService.create_position_target_version(
            request.get_json(silent=True) or {}, _actor()
        )
        return jsonify(result), 201
    except (ValueError, PermissionError) as exc:
        return _error(exc)


@app.route("/api/performance/position-target-versions/<int:target_id>", methods=["PUT"])
@check_auth
def update_performance_position_target(target_id):
    if not _can("prepare"):
        return _deny()
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(
            PerformanceConfigurationService.update_position_target_version(
                target_id, data, _actor(), data.get("row_version")
            )
        )
    except (ValueError, PermissionError) as exc:
        return _error(exc)


@app.route(
    "/api/performance/position-target-versions/<int:target_id>/approve",
    methods=["POST"],
)
@check_auth
def approve_performance_position_target(target_id):
    if not _can("approve"):
        return _deny()
    data = request.get_json(silent=True) or {}
    try:
        return jsonify(
            PerformanceConfigurationService.approve_position_target_version(
                target_id, _actor(), data.get("row_version")
            )
        )
    except (ValueError, PermissionError) as exc:
        return _error(exc)


@app.route("/api/performance/position-target-versions/<int:target_id>", methods=["DELETE"])
@check_auth
def delete_performance_position_target(target_id):
    if not _can("prepare"):
        return _deny()
    try:
        PerformanceConfigurationService.delete_position_target_version(
            target_id, _actor()
        )
        return jsonify({"deleted": True})
    except (ValueError, PermissionError) as exc:
        return _error(exc)


@app.route("/api/performance/position-target-versions/resolve", methods=["GET"])
@check_auth
def resolve_performance_position_target():
    if not any(_can(action) for action in ("view_all", "prepare", "approve")):
        return _deny()
    try:
        return jsonify(
            PerformanceConfigurationService.get_position_target(
                request.args.get("position_id", type=int),
                request.args.get("production_month", ""),
            )
        )
    except (ValueError, PermissionError) as exc:
        return _error(exc)
