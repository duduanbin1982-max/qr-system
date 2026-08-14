"""HTTP adapters for immutable process revisions and lifecycle requests."""

from flask import g, jsonify

from modules.route_decorators import (
    app,
    check_auth,
    check_permission,
    get_json_body,
    require_versioned_master_data_write,
    safe_audit_log,
    validate_json,
)
from modules.services.master_data_lifecycle_service import MasterDataLifecycleService
from modules.services.process_version_service import ProcessVersionService


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
    safe_audit_log(action, "process_version", int(resource_id), detail)


@app.route("/api/processes/<int:process_id>/versions", methods=["GET"])
@check_auth
@check_permission("process_versions:view")
def list_process_versions(process_id):
    return jsonify(ProcessVersionService.list_versions(process_id))


@app.route("/api/process-versions/<int:version_id>", methods=["GET"])
@check_auth
@check_permission("process_versions:view")
def get_process_version(version_id):
    return jsonify(ProcessVersionService.get_version(version_id))


@app.route("/api/processes/<int:process_id>/revisions", methods=["POST"])
@check_auth
@check_permission("process_versions:create")
@require_versioned_master_data_write
@validate_json("process_revision_create")
def create_process_revision(process_id):
    command = get_json_body()
    result = ProcessVersionService.create_revision(process_id, command, _actor())
    _audit("process_revision_create", result["id"], command["revision_reason"])
    return jsonify(result), 201


@app.route("/api/process-versions/<int:version_id>", methods=["PUT"])
@check_auth
@check_permission("process_versions:create")
@require_versioned_master_data_write
@validate_json("process_version_update")
def update_process_version(version_id):
    command = get_json_body()
    result = ProcessVersionService.update_draft(version_id, command, _actor())
    _audit("process_revision_update", version_id)
    return jsonify(result)


@app.route("/api/process-versions/<int:version_id>/submit", methods=["POST"])
@check_auth
@check_permission("process_versions:submit")
@require_versioned_master_data_write
@validate_json("version_transition")
def submit_process_version(version_id):
    result = ProcessVersionService.submit(version_id, get_json_body(), _actor())
    _audit("process_revision_submit", version_id)
    return jsonify(result)


@app.route("/api/process-versions/<int:version_id>/approve", methods=["POST"])
@check_auth
@check_permission("process_versions:approve")
@require_versioned_master_data_write
@validate_json("version_transition")
def approve_process_version(version_id):
    result = ProcessVersionService.approve(version_id, get_json_body(), _actor())
    _audit("process_revision_approve", version_id)
    return jsonify(result)


@app.route("/api/process-versions/<int:version_id>/reject", methods=["POST"])
@check_auth
@check_permission("process_versions:reject")
@require_versioned_master_data_write
@validate_json("version_reject")
def reject_process_version(version_id):
    command = get_json_body()
    result = ProcessVersionService.reject(version_id, command, _actor())
    _audit("process_revision_reject", version_id, command["reason"])
    return jsonify(result)


@app.route("/api/process-versions/<int:version_id>/impact", methods=["GET"])
@check_auth
@check_permission("process_versions:impact")
def process_version_impact(version_id):
    return jsonify(ProcessVersionService.impact(version_id))


def _request_process_lifecycle(process_id, action):
    command = _lifecycle_command()
    result = MasterDataLifecycleService.request_process(
        process_id, action, command, _actor()
    )
    _audit(f"process_{action}_request", result["id"], command["reason"])
    return jsonify(result), 201


@app.route("/api/processes/<int:process_id>/retirement-requests", methods=["POST"])
@check_auth
@check_permission("processes:retire")
@require_versioned_master_data_write
@validate_json("lifecycle_request")
def request_process_retirement(process_id):
    return _request_process_lifecycle(process_id, "retire")


@app.route("/api/processes/<int:process_id>/reactivation-requests", methods=["POST"])
@check_auth
@check_permission("processes:reactivate")
@require_versioned_master_data_write
@validate_json("lifecycle_request")
def request_process_reactivation(process_id):
    return _request_process_lifecycle(process_id, "reactivate")


def _approve_process_lifecycle(request_id, action):
    result = MasterDataLifecycleService.approve_process(
        request_id, get_json_body(), _actor()
    )
    _audit(f"process_{action}_approve", request_id)
    return jsonify(result)


@app.route("/api/process-retirement-requests/<int:request_id>/approve", methods=["POST"])
@check_auth
@check_permission("processes:retire")
@require_versioned_master_data_write
@validate_json("lifecycle_approve")
def approve_process_retirement(request_id):
    return _approve_process_lifecycle(request_id, "retire")


@app.route("/api/process-reactivation-requests/<int:request_id>/approve", methods=["POST"])
@check_auth
@check_permission("processes:reactivate")
@require_versioned_master_data_write
@validate_json("lifecycle_approve")
def approve_process_reactivation(request_id):
    return _approve_process_lifecycle(request_id, "reactivate")
