"""Scoped HTTP API for versioned process configuration."""

from flask import g, jsonify, request

from modules.route_decorators import (
    app,
    check_auth,
    check_permission,
    get_json_body,
    validate_json,
)
from modules.services.process_config_service import ProcessConfigService


def _actor():
    return getattr(g, "current_user", {}) or {}


@app.route("/api/process-config", methods=["GET"])
@check_auth
@check_permission("process_config:view")
def get_process_config():
    return jsonify(ProcessConfigService.get_current())


@app.route("/api/process-config/revisions", methods=["GET"])
@check_auth
@check_permission("process_config:history")
def list_process_config_revisions():
    return jsonify(ProcessConfigService.list_revisions(request.args.get("limit", 100)))


@app.route("/api/process-config/revisions", methods=["POST"])
@check_auth
@check_permission("process_config:create")
@validate_json("process_config_revision_create")
def create_process_config_revision():
    result = ProcessConfigService.create_revision(get_json_body(), _actor())
    return jsonify(result), 201


@app.route("/api/process-config/revisions/<int:revision_id>", methods=["PUT"])
@check_auth
@check_permission("process_config:create")
@validate_json("process_config_revision_update")
def update_process_config_revision(revision_id):
    return jsonify(
        ProcessConfigService.update_draft(revision_id, get_json_body(), _actor())
    )


@app.route("/api/process-config/revisions/<int:revision_id>/submit", methods=["POST"])
@check_auth
@check_permission("process_config:submit")
@validate_json("process_config_transition")
def submit_process_config_revision(revision_id):
    return jsonify(ProcessConfigService.submit(revision_id, get_json_body(), _actor()))


@app.route("/api/process-config/revisions/<int:revision_id>/approve", methods=["POST"])
@check_auth
@check_permission("process_config:approve")
@validate_json("process_config_transition")
def approve_process_config_revision(revision_id):
    return jsonify(ProcessConfigService.approve(revision_id, get_json_body(), _actor()))


@app.route("/api/process-config/revisions/<int:revision_id>/reject", methods=["POST"])
@check_auth
@check_permission("process_config:reject")
@validate_json("process_config_reject")
def reject_process_config_revision(revision_id):
    return jsonify(ProcessConfigService.reject(revision_id, get_json_body(), _actor()))
