"""Versioned performance ledger query and workflow HTTP API."""

from flask import g, jsonify, request

from modules.route_decorators import app, check_auth, safe_audit_log
from modules.services.performance_ledger_service import PerformanceLedgerService


def _actor():
    return getattr(g, "current_user", {}) or {}


def _forbidden(exc):
    return jsonify({"error": str(exc), "code": "forbidden"}), 403


def _command_data():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        raise ValueError("绩效批次请求体必须是对象")
    data = dict(data)
    header_key = request.headers.get("Idempotency-Key", "").strip()
    if header_key and not data.get("idempotency_key"):
        data["idempotency_key"] = header_key
    return data


def _audit(action, result, detail=""):
    safe_audit_log(
        action,
        "performance_batch",
        int(result.get("batch_id") or 0),
        detail,
    )


@app.route("/api/performance/batches", methods=["GET"])
@check_auth
def performance_batches():
    try:
        return jsonify(
            PerformanceLedgerService.list_batches(
                _actor(),
                production_month=request.args.get("production_month")
                or request.args.get("year_month", ""),
                status=request.args.get("status", ""),
                page=request.args.get("page", 1),
                per_page=request.args.get("per_page", 20),
            )
        )
    except PermissionError as exc:
        return _forbidden(exc)


@app.route("/api/performance/batches", methods=["POST"])
@check_auth
def performance_batch_create():
    try:
        result = PerformanceLedgerService.create_batch(_command_data(), _actor())
        _audit(
            "performance_batch_generate",
            result,
            result.get("production_month", ""),
        )
        return jsonify(result)
    except PermissionError as exc:
        return _forbidden(exc)


@app.route("/api/performance/batches/<int:batch_id>", methods=["GET"])
@check_auth
def performance_batch_detail(batch_id):
    try:
        return jsonify(
            PerformanceLedgerService.batch_detail(
                batch_id,
                _actor(),
                page=request.args.get("page", 1),
                per_page=request.args.get("per_page", 50),
            )
        )
    except PermissionError as exc:
        return _forbidden(exc)


def _batch_action(batch_id, action, audit_action):
    try:
        result = getattr(PerformanceLedgerService, action)(
            batch_id, _command_data(), _actor()
        )
        _audit(audit_action, result)
        return jsonify(result)
    except PermissionError as exc:
        return _forbidden(exc)


@app.route(
    "/api/performance/batches/<int:batch_id>/submit-supervisor-review",
    methods=["POST"],
)
@check_auth
def performance_batch_submit_supervisor_review(batch_id):
    return _batch_action(
        batch_id,
        "submit_supervisor_review",
        "performance_batch_submit_supervisor_review",
    )


@app.route(
    "/api/performance/batches/<int:batch_id>/members/<int:user_id>/reviews",
    methods=["POST"],
)
@check_auth
def performance_batch_member_review(batch_id, user_id):
    try:
        data = _command_data()
        data.update({"batch_id": batch_id, "user_id": user_id})
        result = PerformanceLedgerService.save_supervisor_review(data, _actor())
        _audit("performance_supervisor_review_save", result, str(user_id))
        return jsonify(result)
    except PermissionError as exc:
        return _forbidden(exc)


@app.route(
    "/api/performance/batches/<int:batch_id>/submit-approval",
    methods=["POST"],
)
@check_auth
def performance_batch_submit_approval(batch_id):
    return _batch_action(
        batch_id, "submit_approval", "performance_batch_submit_approval"
    )


@app.route(
    "/api/performance/batches/<int:batch_id>/approve", methods=["POST"]
)
@check_auth
def performance_batch_approve(batch_id):
    return _batch_action(batch_id, "approve_batch", "performance_batch_approve")


@app.route(
    "/api/performance/batches/<int:batch_id>/return", methods=["POST"]
)
@check_auth
def performance_batch_return(batch_id):
    return _batch_action(batch_id, "return_batch", "performance_batch_return")


@app.route(
    "/api/performance/batches/<int:batch_id>/cancel", methods=["POST"]
)
@check_auth
def performance_batch_cancel(batch_id):
    return _batch_action(batch_id, "cancel_batch", "performance_batch_cancel")


@app.route(
    "/api/performance/batches/<int:batch_id>/revisions", methods=["POST"]
)
@check_auth
def performance_batch_revision(batch_id):
    try:
        data = _command_data()
        if not data.get("reason") and data.get("revision_reason"):
            data["reason"] = data["revision_reason"]
        result = PerformanceLedgerService.create_revision(batch_id, data, _actor())
        _audit("performance_batch_revision_create", result, data.get("reason", ""))
        return jsonify(result)
    except PermissionError as exc:
        return _forbidden(exc)


@app.route(
    "/api/performance/batches/<int:batch_id>/exceptions", methods=["GET"]
)
@check_auth
def performance_batch_exceptions(batch_id):
    try:
        return jsonify(
            PerformanceLedgerService.list_exceptions(
                batch_id,
                _actor(),
                status=request.args.get("status", ""),
                page=request.args.get("page", 1),
                per_page=request.args.get("per_page", 50),
            )
        )
    except PermissionError as exc:
        return _forbidden(exc)


@app.route(
    "/api/performance/batches/<int:batch_id>/comparison", methods=["GET"]
)
@check_auth
def performance_batch_comparison(batch_id):
    compare_batch_id = request.args.get("compare_batch_id")
    try:
        compare_batch_id = int(compare_batch_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("对比绩效批次主键无效") from exc
    try:
        PerformanceLedgerService.require_visible_batch(batch_id, _actor())
        PerformanceLedgerService.require_visible_batch(compare_batch_id, _actor())
        return jsonify(
            PerformanceLedgerService.compare_batches(
                batch_id, compare_batch_id, actor=_actor()
            )
        )
    except PermissionError as exc:
        return _forbidden(exc)


@app.route(
    "/api/performance/batches/<int:batch_id>/integrity", methods=["GET"]
)
@check_auth
def performance_batch_integrity(batch_id):
    try:
        PerformanceLedgerService.require_visible_batch(batch_id, _actor())
        return jsonify(
            PerformanceLedgerService.check_batch_integrity(
                batch_id,
                include_current=request.args.get("include_current", "").lower()
                in {"1", "true", "yes"},
            )
        )
    except PermissionError as exc:
        return _forbidden(exc)
