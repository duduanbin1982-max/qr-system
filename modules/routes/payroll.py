"""Versioned payroll ledger HTTP API."""

import csv
import io

from flask import g, jsonify, request, send_file

from modules.middleware.auth import has_permission
from modules.route_decorators import app, check_auth, safe_audit_log
from modules.services.payroll_service import PayrollWorkflowService
from modules.services.price_version_service import PriceVersionService
from modules.domain.payroll_policy import PayrollConflictError


def _allowed(*permissions):
    user = getattr(g, "current_user", {}) or {}
    return any(has_permission(user, permission) for permission in permissions)


def _deny():
    return jsonify({"error": "无权限"}), 403


def _json_error(exc):
    if isinstance(exc, PayrollConflictError):
        return jsonify({"error": str(exc)}), 409
    return jsonify({"error": str(exc)}), 400


def _actor():
    return getattr(g, "current_user", {}) or {}


@app.route("/api/payroll/me", methods=["GET"])
@check_auth
def payroll_me():
    if not _allowed("wages:view_self", "wages:view_all", "wages:prepare", "wages:approve"):
        return _deny()
    try:
        return jsonify(PayrollWorkflowService.my_payroll(_actor(), request.args.get("payroll_month", "")))
    except ValueError as exc:
        return _json_error(exc)


@app.route("/api/payroll/batches", methods=["GET"])
@check_auth
def payroll_batches():
    if not _allowed("wages:view_all", "wages:prepare", "wages:approve"):
        return _deny()
    return jsonify(PayrollWorkflowService.list_batches(
        request.args.get("payroll_month", ""), request.args.get("status", "")
    ))


@app.route("/api/payroll/batches", methods=["POST"])
@check_auth
def payroll_batch_create():
    if not _allowed("wages:prepare"):
        return _deny()
    data = request.get_json() or {}
    key = request.headers.get("Idempotency-Key") or data.get("idempotency_key")
    try:
        result = PayrollWorkflowService.create_batch(
            data.get("payroll_month") or data.get("year_month"), _actor(), key,
            str(data.get("revision_reason") or ""), data.get("supersedes_batch_id"),
        )
        safe_audit_log("payroll_batch_generate", "payroll_batch", result.get("id", result.get("batch_id", 0)), "")
        return jsonify(result)
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/payroll/batches/<int:batch_id>", methods=["GET"])
@check_auth
def payroll_batch_detail(batch_id):
    if not _allowed("wages:view_all", "wages:prepare", "wages:approve"):
        return _deny()
    try:
        return jsonify(PayrollWorkflowService.batch_detail(batch_id))
    except ValueError as exc:
        return _json_error(exc)


@app.route("/api/payroll/batches/<int:batch_id>/lines", methods=["GET"])
@check_auth
def payroll_batch_lines(batch_id):
    employee_id = request.args.get("employee_id", type=int)
    if _allowed("wages:view_all", "wages:prepare", "wages:approve"):
        pass
    elif _allowed("wages:view_self") and employee_id == _actor().get("id"):
        pass
    else:
        return _deny()
    try:
        return jsonify(PayrollWorkflowService.batch_detail(batch_id, employee_id))
    except ValueError as exc:
        return _json_error(exc)


@app.route("/api/payroll/batches/<int:batch_id>/regenerate", methods=["POST"])
@check_auth
def payroll_batch_regenerate(batch_id):
    if not _allowed("wages:prepare"):
        return _deny()
    data = request.get_json() or {}
    try:
        result = PayrollWorkflowService.regenerate(batch_id, _actor(), data.get("row_version"))
        safe_audit_log("payroll_batch_regenerate", "payroll_batch", batch_id, "")
        return jsonify(result)
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


def _transition_route(batch_id, action):
    if not _allowed("wages:approve"):
        return _deny()
    data = request.get_json() or {}
    try:
        result = getattr(PayrollWorkflowService, action)(batch_id, _actor(), data.get("row_version"))
        safe_audit_log("payroll_batch_" + action, "payroll_batch", batch_id, "")
        return jsonify(result)
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/payroll/batches/<int:batch_id>/submit", methods=["POST"])
@check_auth
def payroll_batch_submit(batch_id):
    if not _allowed("wages:prepare"):
        return _deny()
    data = request.get_json() or {}
    try:
        return jsonify(PayrollWorkflowService.submit(batch_id, _actor(), data.get("row_version")))
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/payroll/batches/<int:batch_id>/lock", methods=["POST"])
@check_auth
def payroll_batch_lock(batch_id):
    return _transition_route(batch_id, "lock")


@app.route("/api/payroll/batches/<int:batch_id>/confirm", methods=["POST"])
@check_auth
def payroll_batch_confirm(batch_id):
    return _transition_route(batch_id, "confirm")


@app.route("/api/payroll/batches/<int:batch_id>/void", methods=["POST"])
@check_auth
def payroll_batch_void(batch_id):
    if not _allowed("wages:approve"):
        return _deny()
    data = request.get_json() or {}
    try:
        return jsonify(PayrollWorkflowService.void(batch_id, _actor(), data.get("row_version"), data.get("reason")))
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/payroll/batches/<int:batch_id>/revisions", methods=["POST"])
@check_auth
def payroll_batch_revision(batch_id):
    if not _allowed("wages:prepare"):
        return _deny()
    data = request.get_json() or {}
    key = request.headers.get("Idempotency-Key") or data.get("idempotency_key")
    try:
        source = PayrollWorkflowService.batch_detail(batch_id)["batch"]
        result = PayrollWorkflowService.create_batch(
            source["payroll_month"], _actor(), key, data.get("revision_reason", ""), batch_id
        )
        return jsonify(result)
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/payroll/batches/<int:batch_id>/compare/<int:other_id>", methods=["GET"])
@check_auth
def payroll_batch_compare(batch_id, other_id):
    if not _allowed("wages:view_all", "wages:prepare", "wages:approve"):
        return _deny()
    try:
        return jsonify(PayrollWorkflowService.compare_batches(batch_id, other_id))
    except ValueError as exc:
        return _json_error(exc)


@app.route("/api/payroll/batches/<int:batch_id>/export", methods=["GET"])
@check_auth
def payroll_batch_export(batch_id):
    if not _allowed("wages:export"):
        return _deny()
    from modules.domain.payroll_policy import cents_to_yuan

    try:
        batch, lines = PayrollWorkflowService.export_data(batch_id)
    except ValueError as exc:
        return _json_error(exc)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["工资月", "版本", "员工", "工号", "正常工资", "返工工资", "奖金", "补贴", "扣款", "应发工资"])
    for line in lines:
        values = [
            batch["payroll_month"], batch["version"], line["employee_name_snapshot"], line["employee_no_snapshot"],
            cents_to_yuan(line["normal_wage_cents"]), cents_to_yuan(line["rework_wage_cents"]),
            cents_to_yuan(line["bonus_cents"]), cents_to_yuan(line["allowance_cents"]),
            cents_to_yuan(line["deduction_cents"]), cents_to_yuan(line["payable_wage_cents"]),
        ]
        safe_values = [("'" + str(value)) if str(value).startswith(("=", "+", "-", "@")) else value for value in values]
        writer.writerow(safe_values)
    output.seek(0)
    safe_audit_log("payroll_export", "payroll_batch", batch_id, "formal payroll export")
    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8-sig")),
        mimetype="text/csv; charset=utf-8-sig", as_attachment=True,
        download_name=f"payroll_{batch['payroll_month']}_v{batch['version']}.csv",
    )


@app.route("/api/payroll/exceptions", methods=["GET"])
@check_auth
def payroll_exceptions():
    if not _allowed("wages:view_all", "wages:prepare", "wages:approve"):
        return _deny()
    return jsonify(PayrollWorkflowService.list_exceptions(
        request.args.get("payroll_month", ""), request.args.get("batch_id", type=int), request.args.get("status", "")
    ))


@app.route("/api/payroll/exceptions/<int:exception_id>/propose", methods=["POST"])
@check_auth
def payroll_exception_propose(exception_id):
    if not _allowed("wages:prepare"):
        return _deny()
    try:
        return jsonify(PayrollWorkflowService.propose_exception(exception_id, _actor(), request.get_json() or {}))
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/payroll/exceptions/<int:exception_id>/approve", methods=["POST"])
@check_auth
def payroll_exception_approve(exception_id):
    if not _allowed("wages:approve"):
        return _deny()
    try:
        return jsonify(PayrollWorkflowService.approve_exception(exception_id, _actor()))
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/payroll/adjustments", methods=["GET"])
@check_auth
def payroll_adjustments():
    if not _allowed("wages:view_all", "wages:prepare", "wages:approve"):
        return _deny()
    return jsonify(PayrollWorkflowService.list_adjustments(
        request.args.get("payroll_month", ""), request.args.get("employee_id", type=int)
    ))


@app.route("/api/payroll/adjustments", methods=["POST"])
@check_auth
def payroll_adjustment_create():
    if not _allowed("wages:prepare"):
        return _deny()
    try:
        return jsonify(PayrollWorkflowService.create_adjustment(_actor(), request.get_json() or {}))
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/payroll/adjustments/<int:adjustment_id>/reverse", methods=["POST"])
@check_auth
def payroll_adjustment_reverse(adjustment_id):
    if not _allowed("wages:prepare"):
        return _deny()
    try:
        return jsonify(PayrollWorkflowService.reverse_adjustment(
            adjustment_id, _actor(), (request.get_json() or {}).get("reason")
        ))
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/route-price-versions", methods=["GET"])
@check_auth
def route_price_versions():
    if not _allowed("wages:view_all", "wages:prepare", "wages:approve"):
        return _deny()
    return jsonify({"versions": PriceVersionService.list_versions(
        request.args.get("route_id", type=int), request.args.get("status", "")
    )})


@app.route("/api/route-price-versions/reference", methods=["GET"])
@check_auth
def route_price_version_reference():
    if not _allowed("wages:prepare", "wages:approve"):
        return _deny()
    return jsonify({"items": PriceVersionService.reference_items()})


@app.route("/api/route-price-versions", methods=["POST"])
@check_auth
def route_price_version_create():
    if not _allowed("wages:prepare"):
        return _deny()
    try:
        return jsonify(PriceVersionService.create(request.get_json() or {}, _actor()))
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)


@app.route("/api/route-price-versions/<int:version_id>/approve", methods=["POST"])
@check_auth
def route_price_version_approve(version_id):
    if not _allowed("wages:approve"):
        return _deny()
    try:
        return jsonify(PriceVersionService.approve(
            version_id, _actor(), (request.get_json() or {}).get("row_version")
        ))
    except (ValueError, RuntimeError) as exc:
        return _json_error(exc)
