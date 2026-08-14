"""HTTP adapters for atomic process master-data release batches."""

from flask import g, jsonify, request

from modules.route_decorators import (
    app,
    check_auth,
    check_permission,
    get_json_body,
    safe_audit_log,
    validate_json,
)
from modules.services.master_data_release_service import MasterDataReleaseService


def _actor():
    return getattr(g, "current_user", {}) or {}


def _audit(action, batch_id, detail=""):
    safe_audit_log(action, "master_data_release_batch", int(batch_id), detail)


@app.route("/api/master-data-release-batches", methods=["GET"])
@check_auth
@check_permission("master_data_releases:view")
def list_master_data_release_batches():
    return jsonify(MasterDataReleaseService.list_batches(request.args.get("status", "")))


@app.route("/api/master-data-release-batches/<int:batch_id>", methods=["GET"])
@check_auth
@check_permission("master_data_releases:view")
def get_master_data_release_batch(batch_id):
    return jsonify(MasterDataReleaseService.get_batch(batch_id))


@app.route("/api/master-data-release-batches", methods=["POST"])
@check_auth
@check_permission("master_data_releases:create")
@validate_json("master_data_release_create")
def create_master_data_release_batch():
    command = get_json_body()
    result = MasterDataReleaseService.create_batch(command, _actor())
    _audit("master_data_release_create", result["id"], command["revision_reason"])
    return jsonify(result), 201


@app.route("/api/master-data-release-batches/<int:batch_id>/submit", methods=["POST"])
@check_auth
@check_permission("master_data_releases:submit")
@validate_json("master_data_release_submit")
def submit_master_data_release_batch(batch_id):
    result = MasterDataReleaseService.submit(batch_id, get_json_body(), _actor())
    _audit("master_data_release_submit", batch_id)
    return jsonify(result)


@app.route("/api/master-data-release-batches/<int:batch_id>/approve", methods=["POST"])
@check_auth
@check_permission("master_data_releases:approve")
@validate_json("master_data_release_approve")
def approve_master_data_release_batch(batch_id):
    result = MasterDataReleaseService.approve(batch_id, get_json_body(), _actor())
    _audit("master_data_release_approve", batch_id)
    return jsonify(result)


@app.route("/api/master-data-release-batches/<int:batch_id>/reject", methods=["POST"])
@check_auth
@check_permission("master_data_releases:reject")
@validate_json("master_data_release_reject")
def reject_master_data_release_batch(batch_id):
    command = get_json_body()
    result = MasterDataReleaseService.reject(batch_id, command, _actor())
    _audit("master_data_release_reject", batch_id, command["reason"])
    return jsonify(result)
